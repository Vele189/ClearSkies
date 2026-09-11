"""The gate, what it persists, and the command the nightly job actually runs.

The gate's job is to turn a pile of checks into one decision and then make that
decision impossible to miss. Most of what is asserted here is about the ways a
gate can be worse than useless: reporting green because the data never arrived,
losing the measurement that would have shown a slow decline, or failing in a way
that only appears in a log nobody reads.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pipeline.metadata import PullMetadata, RecordCounts, RunStatus
from pipeline.quality import DictDataset, JsonQualityStore, run_gate, summarise_history
from pipeline.quality.checks import (
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
)
from pipeline.quality.store import rows_for_sql, run_row_for_sql
from pipeline.records import NormalizedRecord

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


class Facility(NormalizedRecord):
    table: ClassVar[str] = "facility"
    facility_id: str
    name: str | None = None

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id,)


def manifest(source: str, *, status: RunStatus = "ok", loaded: int = 100) -> PullMetadata:
    return PullMetadata(
        source=source,
        source_title=source.upper(),
        vintage="2026",
        pulled_at=NOW,
        status=status,
        counts=RecordCounts(fetched=loaded, validated=loaded, normalized=loaded, loaded=loaded),
    )


def facilities(count: int) -> DictDataset:
    return DictDataset(
        {"facility": [Facility(facility_id=f"F{i}", name="site") for i in range(count)]}
    )


class Adapter:
    """An adapter that declares its own expectations, as the interface intends."""

    expectations = SourceExpectations(
        source="demo",
        tables=(
            TableExpectations(
                table="facility",
                rows=RowCount(10, 1_000),
                null_rates=(NullRate("name", 0.0),),
            ),
        ),
    )


# ---- the verdict -------------------------------------------------------


def test_a_clean_load_passes() -> None:
    report = run_gate(
        manifests=[manifest("demo")],
        data=facilities(50),
        now=NOW,
        adapters={"demo": Adapter},
    )
    assert report.passed
    assert not report.failures and not report.warnings
    assert {r.status for r in report.results if r.scope == "demo"} == {"pass"}


def test_a_run_with_unrun_checks_does_not_report_a_clean_pass() -> None:
    """A skip is not a pass, including in the verdict.

    The cross-source checks cannot run without the other sources, so a night that
    loaded one source reads as `skip`: nothing failed, and not everything was
    looked at. It still loads — `passed` is about failures — but the top line
    never claims a completeness the run did not have.
    """
    report = run_gate(
        manifests=[manifest("demo")],
        data=facilities(50),
        now=NOW,
        adapters={"demo": Adapter},
    )
    assert report.status == "skip"
    assert report.passed
    assert report.skipped


def test_a_load_outside_its_row_range_fails_the_gate() -> None:
    report = run_gate(
        manifests=[manifest("demo", loaded=3)],
        data=facilities(3),
        now=NOW,
        adapters={"demo": Adapter},
    )
    assert not report.passed
    assert [r.check for r in report.failures] == ["row_count"]


def test_a_failed_pull_fails_the_gate() -> None:
    report = run_gate(
        manifests=[manifest("demo", status="failed", loaded=0)],
        data=facilities(50),
        now=NOW,
        adapters={"demo": Adapter},
    )
    assert not report.passed
    assert any(r.check == "pull_status" for r in report.failures)


def test_a_stale_pull_warns_rather_than_failing() -> None:
    """Section 6: the pipeline continues on the last good snapshot. It says so."""
    report = run_gate(
        manifests=[manifest("demo", status="stale")],
        data=facilities(50),
        now=NOW,
        adapters={"demo": Adapter},
    )
    assert report.passed
    status = next(r for r in report.results if r.check == "pull_status")
    assert status.status == "warn"
    assert "recency term degrades" in status.detail


# ---- the ways a gate can be worse than useless ------------------------


def test_a_required_source_that_produced_no_manifest_fails() -> None:
    report = run_gate(
        manifests=[manifest("demo")],
        data=facilities(50),
        now=NOW,
        required=["epa_echo"],
        adapters={"demo": Adapter},
    )
    assert not report.passed
    assert any("produced no manifest" in r.detail for r in report.failures)


def test_a_skipped_check_on_a_required_source_becomes_a_failure() -> None:
    """The dangerous state: the report is green and the data is missing."""
    report = run_gate(
        manifests=[manifest("epa_echo")],
        data=DictDataset(),
        now=NOW,
        required=["epa_echo"],
    )
    assert not report.passed
    assert any("was required for this run" in r.detail for r in report.failures)


def test_the_same_skip_is_only_a_skip_when_the_source_was_not_required() -> None:
    report = run_gate(manifests=[manifest("epa_echo")], data=DictDataset(), now=NOW)
    assert report.passed
    assert report.skipped
    assert not report.failures


def test_a_source_with_no_expectations_is_reported_as_a_gap_not_a_pass() -> None:
    report = run_gate(manifests=[manifest("brand_new")], data=facilities(50), now=NOW)
    warning = next(r for r in report.warnings if r.check == "expectations_declared")
    assert "checked only by the interface" in warning.detail


def test_an_empty_run_says_so_rather_than_reporting_success() -> None:
    report = run_gate(manifests=[], data=DictDataset(), now=NOW)
    assert report.status == "skip"
    assert any("Nothing was loaded" in note for note in report.notes)


# ---- making the failure visible ---------------------------------------


def test_the_report_renders_a_page_naming_its_failures() -> None:
    report = run_gate(
        manifests=[manifest("demo", loaded=3)],
        data=facilities(3),
        now=NOW,
        adapters={"demo": Adapter},
    )
    page = report.markdown()
    assert "# Data quality gate: FAILED" in page
    assert "## Failures" in page
    assert "3 rows, below the expected 10 to 1000" in page


def test_failures_become_workflow_annotations_that_attach_to_the_run() -> None:
    report = run_gate(
        manifests=[manifest("demo", loaded=3)],
        data=facilities(3),
        now=NOW,
        adapters={"demo": Adapter},
    )
    expected = "::error title=Quality gate: demo / facility / row_count"
    assert any(a.startswith(expected) for a in report.annotations())


# ---- persistence -------------------------------------------------------


def test_a_run_is_saved_next_to_its_manifests(tmp_path: Path) -> None:
    report = run_gate(
        manifests=[manifest("demo")], data=facilities(50), now=NOW, adapters={"demo": Adapter}
    )
    store = JsonQualityStore(tmp_path)
    store.save(report, [manifest("demo")])

    run_dir = store.path_for(report.run_id)
    assert json.loads((run_dir / "report.json").read_text())["run_id"] == report.run_id
    assert json.loads((run_dir / "manifests.json").read_text())[0]["source"] == "demo"
    assert "Data quality gate" in (run_dir / "report.md").read_text()


def test_passing_measurements_are_kept_so_a_threshold_can_be_narrowed(tmp_path: Path) -> None:
    """A store that keeps only failures cannot show a count declining for a month."""
    store = JsonQualityStore(tmp_path)
    for day, count in enumerate((900, 800, 700), start=11):
        moment = NOW.replace(day=day)
        report = run_gate(
            manifests=[manifest("demo", loaded=count)],
            data=facilities(count),
            now=moment,
            adapters={"demo": Adapter},
        )
        assert report.passed
        store.save(report, [])

    assert store.observations("row_count", scope="demo") == [900.0, 800.0, 700.0]
    stats = summarise_history(store.history())["demo/row_count"]
    assert stats == {"runs": 3.0, "low": 700.0, "high": 900.0, "mean": 800.0}


def test_history_is_empty_rather_than_an_error_before_the_first_run(tmp_path: Path) -> None:
    assert JsonQualityStore(tmp_path / "nothing").history() == []


def test_the_sql_payload_matches_the_migration(tmp_path: Path) -> None:
    """`rows_for_sql` is what the Postgres store will insert into 0015."""
    report = run_gate(
        manifests=[manifest("demo")], data=facilities(50), now=NOW, adapters={"demo": Adapter}
    )
    row = rows_for_sql(report)[0]
    assert set(row) == {
        "run_id",
        "checked_at",
        "scope",
        "table_name",
        "check",
        "field_name",
        "status",
        "observed",
        "expected",
        "detail",
    }

    run_row = run_row_for_sql(report, git_sha="abc123")
    # The migration's CHECK constraint, asserted on the payload that will meet it.
    assert run_row["passed"] == (run_row["verdict"] != "fail")
    assert run_row["checks_passed"] + run_row["checks_warned"] + run_row["checks_failed"] + run_row[
        "checks_skipped"
    ] == len(report.results)


# ---- the command the nightly job runs ---------------------------------


def test_check_exits_zero_on_the_reference_adapter(tmp_path: Path) -> None:
    from pipeline.__main__ import main

    assert main(["check", "fake", "--store", str(tmp_path)]) == 0
    assert list(tmp_path.glob("*/report.json"))


def test_check_exits_one_when_a_required_source_is_absent(tmp_path: Path) -> None:
    """The exit status is what stops a bad night becoming the current run."""
    from pipeline.__main__ import main

    assert main(["check", "fake", "--require", "epa_echo", "--store", str(tmp_path)]) == 1


def test_history_command_reads_back_what_check_wrote(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from pipeline.__main__ import main

    main(["check", "fake", "--store", str(tmp_path)])
    assert main(["history", "--store", str(tmp_path)]) == 0
    assert "fake/pull_status" in capsys.readouterr().out
