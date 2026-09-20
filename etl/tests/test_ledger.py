"""The night's record, and the one flag that decides what gets served.

The property under test throughout is that a bad night changes nothing. Each
source's transaction closed hours before the gate ran, so "leaves the previous
dataset intact" cannot mean a rollback; it means a promotion that does not
happen. Everything here is about making that refusal impossible to bypass by
accident.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.ledger import (
    METHODOLOGY_VERSION,
    NightlyRun,
    RunLedger,
    SourceOutcome,
    carried,
    finish,
    outcome_from,
    row_for_sql,
    source_rows_for_sql,
)
from pipeline.metadata import PullMetadata, RecordCounts, RunStatus

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


def manifest(source: str, *, status: RunStatus = "ok", loaded: int = 100) -> PullMetadata:
    return PullMetadata(
        source=source,
        source_title=source.replace("_", " ").title(),
        vintage="2024",
        pulled_at=NOW,
        status=status,
        counts=RecordCounts(fetched=loaded, validated=loaded, normalized=loaded, loaded=loaded),
    )


def night(
    run_id: str,
    *,
    passed: bool = True,
    outcomes: tuple[SourceOutcome, ...] = (),
    at: datetime = NOW,
) -> NightlyRun:
    return finish(
        NightlyRun(run_id=run_id, started_at=at),
        outcomes=outcomes,
        passed=passed,
        verdict="pass" if passed else "fail",
        finished_at=at,
    )


# ---- promotion ----------------------------------------------------------


def test_a_passing_run_becomes_the_one_that_is_served(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path)
    run = night("first")
    ledger.record(run)

    assert ledger.promote(run) is True
    current = ledger.current()
    assert current is not None
    assert current.run_id == "first"


def test_a_failed_run_is_refused_promotion_and_leaves_the_previous_one_serving(
    tmp_path: Path,
) -> None:
    """The acceptance criterion, as the test that would catch its loss."""
    ledger = RunLedger(tmp_path)
    good = night("good")
    ledger.record(good)
    ledger.promote(good)

    bad = night("bad", passed=False)
    ledger.record(bad)
    assert ledger.promote(bad) is False

    current = ledger.current()
    assert current is not None
    assert current.run_id == "good", "a failed night replaced the served run"


def test_a_refused_promotion_is_not_an_error(tmp_path: Path) -> None:
    """A failed night behaving correctly must not read as a crash."""
    assert RunLedger(tmp_path).promote(night("bad", passed=False)) is False


def test_a_failed_run_is_still_recorded(tmp_path: Path) -> None:
    """Refusing to serve a night is not the same as forgetting it happened."""
    ledger = RunLedger(tmp_path)
    ledger.record(night("bad", passed=False))
    assert [r.run_id for r in ledger.runs()] == ["bad"]
    assert ledger.current() is None


def test_nothing_is_served_before_a_run_has_passed(tmp_path: Path) -> None:
    assert RunLedger(tmp_path).current() is None
    assert RunLedger(tmp_path).runs() == []


# ---- last success, which is what a cadence counts from ------------------


def test_last_success_is_the_most_recent_load_per_source(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path)
    earlier = NOW - timedelta(days=3)
    ledger.record(
        night(
            "one",
            at=earlier,
            outcomes=(
                outcome_from(manifest("epa_echo").model_copy(update={"pulled_at": earlier})),
            ),
        )
    )
    ledger.record(night("two", outcomes=(outcome_from(manifest("epa_echo")),)))

    assert ledger.last_success()["epa_echo"] == NOW


def test_a_carried_source_does_not_count_as_a_pull(tmp_path: Path) -> None:
    """Otherwise a carried night would reset the clock and carry forever."""
    ledger = RunLedger(tmp_path)
    ledger.record(night("one", outcomes=(carried("epa_tri", "not due"),)))
    assert "epa_tri" not in ledger.last_success()


def test_a_failed_pull_does_not_count_as_a_success(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path)
    ledger.record(night("one", outcomes=(outcome_from(manifest("openaq", status="failed")),)))
    assert "openaq" not in ledger.last_success()


def test_a_stale_pull_counts_as_a_success(tmp_path: Path) -> None:
    """Upstream was down and the snapshot served. Re-pulling nightly buys nothing.

    The recency term already records the staleness (methodology section 6), so
    the cadence does not also need to punish it with a nightly retry.
    """
    ledger = RunLedger(tmp_path)
    ledger.record(night("one", outcomes=(outcome_from(manifest("openaq", status="stale")),)))
    assert "openaq" in ledger.last_success()


def test_a_source_that_loaded_on_a_night_another_source_failed_still_counts(
    tmp_path: Path,
) -> None:
    """One bad source must not turn into a nightly full refresh of all six."""
    ledger = RunLedger(tmp_path)
    ledger.record(
        night(
            "mixed",
            passed=False,
            outcomes=(
                outcome_from(manifest("epa_echo")),
                outcome_from(manifest("openaq", status="failed")),
            ),
        )
    )
    success = ledger.last_success()
    assert "epa_echo" in success
    assert "openaq" not in success


# ---- run ids ------------------------------------------------------------


def test_a_run_id_already_in_the_ledger_gets_a_suffix(tmp_path: Path) -> None:
    """Two dispatches in the same second must not share an identity."""
    ledger = RunLedger(tmp_path)
    assert ledger.unique_run_id("20260911T070000Z") == "20260911T070000Z"

    ledger.record(night("20260911T070000Z"))
    assert ledger.unique_run_id("20260911T070000Z") == "20260911T070000Z-2"

    ledger.record(night("20260911T070000Z-2"))
    assert ledger.unique_run_id("20260911T070000Z") == "20260911T070000Z-3"


# ---- the shapes the database will take ----------------------------------


def test_the_run_row_matches_the_pipeline_run_table() -> None:
    run = night("first")
    row = row_for_sql(run)
    assert set(row) == {
        "started_at",
        "finished_at",
        "status",
        "git_sha",
        "methodology_version",
        "scored_hexes",
        "notes",
    }
    # migration 0002 constrains status to these three.
    assert row["status"] in {"running", "succeeded", "failed"}


def test_only_a_succeeded_run_can_be_current() -> None:
    """Mirrors pipeline_run_current_must_have_succeeded in migration 0002."""
    assert not night("bad", passed=False).succeeded
    assert night("good").succeeded


def test_source_rows_carry_the_vintage_the_detail_panel_needs() -> None:
    run = night("first", outcomes=(outcome_from(manifest("epa_tri")),))
    rows = source_rows_for_sql(run)
    assert rows[0]["source"] == "epa_tri"
    assert rows[0]["vintage"] == "2024"
    assert rows[0]["action"] == "pull"


def test_a_carried_source_is_distinguishable_from_a_failed_one() -> None:
    """The whole reason `action` exists on the outcome."""
    skipped = carried("epa_tri", "not due")
    broken = outcome_from(manifest("epa_tri", status="failed"))
    assert skipped.action == "carry" and skipped.status is None
    assert broken.action == "pull" and broken.status == "failed"
    assert not skipped.loaded and not broken.loaded


# ---- drift guard --------------------------------------------------------


def test_the_methodology_version_matches_the_document() -> None:
    """`etl` ships without the docs tree, so the constant is restated there.

    This reads the document off disk and fails if the two ever disagree, the same
    guard CS-108 uses to keep the indicator groups in step with the API.
    """
    doc = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"
    if not doc.exists():  # pragma: no cover - the docs tree is not always present
        return
    match = re.search(r"^\*\*Version:\*\*\s*([0-9]+\.[0-9]+\.[0-9]+)", doc.read_text(), re.M)
    assert match, "docs/methodology.md has no parseable version header"
    assert match.group(1) == METHODOLOGY_VERSION
