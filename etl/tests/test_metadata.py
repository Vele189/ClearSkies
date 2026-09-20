from datetime import datetime

import pytest
from pydantic import ValidationError

from pipeline.metadata import (
    Artifact,
    KnownGap,
    PullMetadata,
    RecordCounts,
    tally,
)
from tests.conftest import FIXED_NOW


def manifest(**overrides: object) -> PullMetadata:
    defaults: dict[str, object] = {
        "source": "fake",
        "source_title": "Fake air quality stations",
        "vintage": "daily/2026-09-09",
        "pulled_at": FIXED_NOW,
        "status": "ok",
        "counts": RecordCounts(fetched=7, validated=4, rejected=3, normalized=4, loaded=4),
    }
    return PullMetadata.model_validate(defaults | overrides)


def test_a_naive_pull_timestamp_is_rejected() -> None:
    # A timestamp without a zone cannot be differenced against a vintage, and
    # the recency term in the confidence score is exactly that difference.
    with pytest.raises(ValidationError):
        manifest(pulled_at=datetime(2026, 9, 10, 7, 0))


def test_record_count_is_what_reached_the_database() -> None:
    assert manifest().record_count == 4


def test_a_failed_run_is_not_ok() -> None:
    assert manifest().ok
    assert not manifest(status="failed").ok


def test_provenance_row_carries_source_vintage_checksum_and_gaps() -> None:
    row = manifest(
        artifacts=(
            Artifact(
                url="https://example.invalid/readings.csv",
                retrieved_at=FIXED_NOW,
                sha256="a" * 64,
                size_bytes=100,
            ),
        ),
        known_gaps=(KnownGap(scope="attribute", detail="one station offline"),),
    ).provenance_row()

    assert row.startswith("| fake | daily/2026-09-09 | 2026-09-10 07:00 | 4 | ok |")
    assert "aaaaaaaaaaaa |" in row
    assert "one station offline" in row


def test_provenance_row_says_so_when_there_is_nothing_to_report() -> None:
    row = manifest().provenance_row()
    assert "n/a" in row
    assert "none recorded" in row


def test_summary_is_one_line() -> None:
    line = manifest(duration_s=2.5).summary()
    assert "\n" not in line
    assert "4 records" in line
    assert "3 rejected" in line


def test_tally_counts_reasons() -> None:
    assert tally(["bad lat", "bad lat", "negative"]) == {"bad lat": 2, "negative": 1}


def test_gaps_and_artifacts_are_immutable() -> None:
    # Provenance that can be edited after the fact is not provenance.
    record = manifest()
    with pytest.raises(ValidationError):
        record.status = "failed"
