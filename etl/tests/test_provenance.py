"""Where every number came from, kept and rendered.

Two failure modes drive most of what is asserted here. A provenance page that
quietly omits the night a source could not be reached tells the reader the data
is more complete than it is. And a page that keeps only the latest pull cannot
answer a question about a claim made last month, which is the question it exists
to answer.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline.metadata import Artifact, KnownGap, PullMetadata, RecordCounts, RunStatus
from pipeline.provenance import (
    BEGIN,
    END,
    ProvenanceStore,
    latest_per_source,
    payload,
    render_block,
    rows_for_sql,
    update_page,
    write_page,
)

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=UTC)

PAGE = f"""# Provenance

Prose a person wrote, which the generator must not touch.

{BEGIN}

| Source | Vintage | Pulled | Records | Status | Checksum | Known gaps |
|---|---|---|---|---|---|---|

_Nothing yet._

{END}

## More prose

Also not to be touched.
"""


def pull(
    source: str,
    *,
    status: RunStatus = "ok",
    vintage: str = "2024",
    loaded: int = 100,
    at: datetime = NOW,
    gaps: tuple[KnownGap, ...] = (),
    artifacts: tuple[Artifact, ...] = (),
) -> PullMetadata:
    return PullMetadata(
        source=source,
        source_title=source.replace("_", " ").title(),
        vintage=vintage,
        pulled_at=at,
        status=status,
        counts=RecordCounts(fetched=loaded, validated=loaded, normalized=loaded, loaded=loaded),
        known_gaps=gaps,
        artifacts=artifacts,
    )


def artifact(sha: str = "a" * 64) -> Artifact:
    return Artifact(
        url="https://example.invalid/data.csv",
        retrieved_at=NOW,
        sha256=sha,
        size_bytes=1024,
    )


# ---- history ------------------------------------------------------------


def test_a_pull_is_recorded_and_read_back(tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path)
    store.record([pull("epa_echo")])
    assert [p.source for p in store.history()] == ["epa_echo"]


def test_history_outlives_the_run_that_wrote_it(tmp_path: Path) -> None:
    """The whole point: a claim from last month needs last month's manifest."""
    store = ProvenanceStore(tmp_path)
    store.record([pull("epa_echo", vintage="2023", at=NOW - timedelta(days=30))])
    store.record([pull("epa_echo", vintage="2024")])

    assert [p.vintage for p in store.history("epa_echo")] == ["2023", "2024"]


def test_history_can_be_narrowed_to_one_source(tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path)
    store.record([pull("epa_echo"), pull("openaq")])
    assert [p.source for p in store.history("openaq")] == ["openaq"]


def test_recording_nothing_writes_nothing(tmp_path: Path) -> None:
    ProvenanceStore(tmp_path).record([])
    assert ProvenanceStore(tmp_path).history() == []


def test_the_run_each_pull_belonged_to_is_kept(tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path)
    store.record([pull("epa_echo")], run_id="20260911T070000Z")
    assert store.run_ids() == ["20260911T070000Z"]


def test_latest_is_per_source(tmp_path: Path) -> None:
    store = ProvenanceStore(tmp_path)
    store.record([pull("epa_echo", vintage="old", at=NOW - timedelta(days=7)), pull("openaq")])
    store.record([pull("epa_echo", vintage="new")])

    latest = {p.source: p.vintage for p in store.latest()}
    assert latest == {"epa_echo": "new", "openaq": "2024"}


def test_a_failed_pull_is_published_rather_than_hidden_behind_an_older_success() -> None:
    """A green row from three nights ago would read as "this data is current"."""
    pulls = [
        pull("epa_echo", status="ok", at=NOW - timedelta(days=3)),
        pull("epa_echo", status="failed", loaded=0),
    ]
    assert [p.status for p in latest_per_source(pulls)] == ["failed"]


def test_latest_is_sorted_by_source_so_the_page_is_stable() -> None:
    pulls = [pull("openaq"), pull("census_acs"), pull("epa_echo")]
    assert [p.source for p in latest_per_source(pulls)] == ["census_acs", "epa_echo", "openaq"]


# ---- the page -----------------------------------------------------------


def test_the_block_is_replaced_and_nothing_else_is() -> None:
    updated = update_page(PAGE, [pull("epa_echo")])
    assert "Prose a person wrote" in updated
    assert "## More prose" in updated
    assert "epa_echo" in updated
    assert "_Nothing yet._" not in updated


def test_the_markers_survive_so_the_page_can_be_regenerated_again() -> None:
    once = update_page(PAGE, [pull("epa_echo")])
    twice = update_page(once, [pull("openaq")])
    assert BEGIN in twice and END in twice
    assert "epa_echo" not in twice, "the previous generation was left behind"
    assert "openaq" in twice


def test_a_page_without_markers_raises_rather_than_guessing() -> None:
    """A generator that invents a place to write duplicates the table later."""
    with pytest.raises(ValueError, match="generated block"):
        update_page("# Provenance\n\nNo markers here.\n", [pull("epa_echo")])


def test_an_empty_history_renders_the_note_not_a_bare_header() -> None:
    block = render_block([])
    assert "| Source | Vintage |" in block
    assert "No pipeline run has happened yet" in block


def test_a_row_carries_the_vintage_the_status_and_the_checksum() -> None:
    block = render_block(
        [pull("epa_tri", vintage="2023", artifacts=(artifact("bee5" + "0" * 60),))]
    )
    assert "2023" in block
    assert "| ok |" in block
    assert "bee500000000" in block, "the short checksum is missing"


def test_writing_reports_whether_the_file_changed(tmp_path: Path) -> None:
    """What lets the nightly job avoid an empty commit every night."""
    page = tmp_path / "provenance.md"
    page.write_text(PAGE, encoding="utf-8")

    assert write_page(page, [pull("epa_echo")]) is True
    assert write_page(page, [pull("epa_echo")]) is False


# ---- the shapes the database will take ----------------------------------


def test_the_pull_row_matches_migration_0012() -> None:
    rows = rows_for_sql(pull("epa_echo"), run_id="20260911T070000Z")
    assert set(rows) == {"source_pull", "source_pull_gap", "source_pull_artifact"}
    assert set(rows["source_pull"]) == {
        "run_id",
        "source",
        "source_title",
        "vintage",
        "pulled_at",
        "status",
        "records_fetched",
        "records_validated",
        "records_rejected",
        "records_normalized",
        "records_loaded",
        "rejection_reasons",
        "duration_s",
        "notes",
    }


def test_a_failed_pull_reports_no_loaded_rows() -> None:
    """Migration 0012 constrains this; a row count for absent data is a lie."""
    rows = rows_for_sql(pull("epa_echo", status="failed", loaded=0))
    assert rows["source_pull"]["status"] == "failed"
    assert rows["source_pull"]["records_loaded"] == 0


def test_gaps_and_artifacts_come_out_as_their_own_rows() -> None:
    manifest = pull(
        "openaq",
        gaps=(KnownGap(scope="geographic", detail="two dozen monitors", affects=("E4",)),),
        artifacts=(artifact(),),
    )
    rows = rows_for_sql(manifest)
    assert rows["source_pull_gap"][0]["scope"] == "geographic"
    assert rows["source_pull_gap"][0]["affects"] == ["E4"]
    assert rows["source_pull_artifact"][0]["sha256"] == "a" * 64


def test_the_api_payload_carries_the_same_facts_as_the_page() -> None:
    """A reader checking one against the other must not have to reconcile them."""
    manifest = pull(
        "epa_tri",
        gaps=(KnownGap(scope="temporal", detail="18-month lag"),),
        artifacts=(artifact(),),
    )
    body = payload([manifest])["sources"][0]
    assert body["source"] == "epa_tri"
    assert body["vintage"] == "2024"
    assert body["status"] == "ok"
    assert body["known_gaps"][0]["scope"] == "temporal"
    assert body["artifacts"][0]["short_sha"] == "a" * 12
