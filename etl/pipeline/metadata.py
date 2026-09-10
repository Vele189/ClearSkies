"""What every adapter must say about a pull, in one shape.

A number in this project is worth nothing without its provenance. The map claims
a hexagon is in the 95th percentile for air toxics cancer risk; a reader is
entitled to ask which release of AirToxScreen that came from, when it was
downloaded, how many records it contained, and what it is known not to cover.
`PullMetadata` is that answer, and the runner produces it whether the pull
succeeded, degraded, or failed.

The five fields the interface requires of every adapter are `source`, `vintage`,
`pulled_at`, the record counts, and `known_gaps`. The rest the runner fills in.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# ok      every record survived
# partial some records were rejected, within the configured tolerance
# stale   upstream was unavailable and the last good snapshot was used
# failed  nothing was loaded; the sink was rolled back
RunStatus = Literal["ok", "partial", "stale", "failed"]

GapScope = Literal["geographic", "temporal", "attribute", "population", "methodological"]


def _require_utc(value: datetime) -> datetime:
    """Naive timestamps are a provenance bug, not a formatting preference.

    A pull timestamp without a zone cannot be compared against a vintage to
    produce the recency term in methodology section 12.
    """
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class SourceSpec(Frozen):
    """The static identity of a source. Declared on the adapter class."""

    name: str = Field(description="Registry key, lowercase with underscores, e.g. epa_tri")
    title: str = Field(description="Human name, e.g. EPA Toxics Release Inventory")
    homepage: str = Field(description="Where a reader goes to check the source themselves")
    cadence: str = Field(description="How often upstream republishes, e.g. annual, ~18-month lag")
    native_geography: str = Field(description="e.g. point (facility lat/lon), census tract")
    provides: tuple[str, ...] = Field(
        default=(), description="Indicator ids this source feeds, e.g. ('E1', 'E2')"
    )
    licence: str = "US public domain (federal government work)"


class KnownGap(Frozen):
    """Something this pull does not cover, recorded rather than smoothed over.

    A gap is not a failure. It is the difference between a value that is absent
    and a value that is zero, carried forward so the confidence term and the
    drill-down panel can both show it (methodology sections 11 and 12).
    """

    scope: GapScope
    detail: str
    affects: tuple[str, ...] = Field(
        default=(), description="Indicator ids degraded by this gap, e.g. ('E4',)"
    )
    since: date | None = None


class Artifact(Frozen):
    """One downloaded file, checksummed.

    Adapters record the exact URL and date they used because several EPA
    datasets have moved or been withdrawn (methodology section 6). The checksum
    is what lets a later run tell "upstream republished" from "upstream is the
    same file with a new URL".
    """

    url: str
    retrieved_at: UtcDatetime
    sha256: str
    size_bytes: int
    media_type: str | None = None
    from_snapshot: bool = Field(
        default=False, description="True when served from the last good snapshot, not the network"
    )

    @property
    def short_sha(self) -> str:
        return self.sha256[:12]


class RecordCounts(Frozen):
    """Where records went. `loaded` is the count that reached the sink."""

    fetched: int = 0
    validated: int = 0
    rejected: int = 0
    normalized: int = 0
    loaded: int = 0


class Rejection(Frozen):
    """One rejected record, kept as a sample so a schema change is diagnosable."""

    index: int
    reason: str
    field: str | None = None
    record_id: str | None = None


# Enough to see a pattern, few enough that a manifest stays readable when an
# upstream schema change rejects everything.
REJECTION_SAMPLE_LIMIT = 20


class PullMetadata(Frozen):
    """The provenance record for a single adapter run."""

    source: str
    source_title: str
    vintage: str = Field(
        description="Upstream release identifier: a year, a quarter, a version, a date"
    )
    pulled_at: UtcDatetime
    status: RunStatus
    counts: RecordCounts
    known_gaps: tuple[KnownGap, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    rejections: tuple[Rejection, ...] = ()
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    duration_s: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def record_count(self) -> int:
        """The count that matters downstream: records actually in the database."""
        return self.counts.loaded

    @property
    def ok(self) -> bool:
        return self.status != "failed"

    def summary(self) -> str:
        return (
            f"{self.source} {self.vintage}: {self.status}, "
            f"{self.record_count} records, {self.counts.rejected} rejected, "
            f"{self.duration_s:.1f}s"
        )

    def provenance_row(self) -> str:
        """One row for the table in docs/provenance.md.

        Generated rather than hand-written, because a hand-written provenance
        page is a provenance page that stops matching the data.
        """
        checksums = ", ".join(a.short_sha for a in self.artifacts) or "n/a"
        gaps = "; ".join(g.detail for g in self.known_gaps) or "none recorded"
        return (
            f"| {self.source} | {self.vintage} | "
            f"{self.pulled_at.strftime('%Y-%m-%d %H:%M')} | {self.record_count} | "
            f"{self.status} | {checksums} | {gaps} |"
        )


def tally(reasons: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return counts
