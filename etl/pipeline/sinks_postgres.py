"""The Postgres implementation of the `Sink` protocol (CS-006).

`pipeline.sinks` holds the protocol and the in-memory reference. This module is
the half that talks to PostGIS, and it lives in its own file so that importing
`pipeline.sinks` — which every adapter and every test does — stays free of a
database driver. The connection is a Protocol here for the same reason it is one
in `pipeline.dasymetric.postgis`.

It reproduces the two properties the reference sink has and CS-006 asks for:

**Upsert on the natural key.** Every table's conflict target is the constraint
that matches its record's `natural_key`, so re-running a source updates rows
instead of duplicating them. `tri_release` is the one table whose primary key is
a surrogate; it conflicts on its natural-key unique constraint instead.

**All-or-nothing commit with the metadata.** Records are staged in memory during
`write` and flushed inside one transaction at `commit`, after the
`source_snapshot` row exists. That ordering is forced rather than chosen: every
fact table carries `snapshot_id NOT NULL REFERENCES source_snapshot`, and the
snapshot is built from the `PullMetadata` that only arrives at `commit`. A
rollback therefore leaves the previous pull in place, whole.

Two things this module does not decide on its own, both flagged at their call
sites: `vintage_end`, which the adapter interface does not yet carry and which
`_vintage_end` derives with a documented rule, and the mapping from registry
source names to the eight `source_snapshot.source` values the schema allows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable

from pipeline.metadata import PullMetadata
from pipeline.records import Measurement, NormalizedRecord

__all__ = ["Connection", "PostgresSink", "SNAPSHOT_SOURCE", "UnmappedTable"]


@runtime_checkable
class Connection(Protocol):
    """The slice of asyncpg this module needs."""

    async def fetchval(self, query: str, *args: Any) -> Any: ...

    async def executemany(self, query: str, args: Iterable[Sequence[Any]]) -> Any: ...

    def transaction(self) -> AbstractAsyncContextManager[Any]: ...


class UnmappedTable(LookupError):
    """A record arrived for a table this module has no column mapping for.

    Raised rather than skipped. A sink that silently drops a table it does not
    recognise is a sink that reports a successful load of nothing, which is the
    failure the CS-108 gate exists to catch and should never have to.
    """


#: Registry source name to the value `source_snapshot.source` permits.
#:
#: The schema's CHECK predates the registry and spells four of the six sources
#: differently. Mapping here rather than widening the CHECK keeps the stored
#: vocabulary the one the methodology paper uses. `fake` is deliberately absent:
#: the reference adapter writes to `fake_station_readings`, which is not a table
#: in any migration, so `make ingest-fake` stays an in-memory exercise.
SNAPSHOT_SOURCE: Mapping[str, str] = {
    "epa_echo": "echo",
    "epa_tri": "tri",
    "epa_rsei": "rsei",
    "airtoxscreen": "airtoxscreen",
    "openaq": "openaq",
    "census_acs": "acs",
    "census_block": "census_block",
}


def _point(longitude: float | None, latitude: float | None) -> str | None:
    """A lon/lat pair as EWKT, or None when either half is missing.

    None rather than a point at the origin: `facility_geom_matches_status`
    requires geom to be NULL exactly when coordinate_status is 'missing', and
    (0, 0) is a real place in the Gulf of Guinea.
    """
    if longitude is None or latitude is None:
        return None
    return f"SRID=4326;POINT({longitude} {latitude})"


def _observed(measurement: Measurement) -> float | None:
    """The value, or None when upstream said nothing. Section 11, in one place."""
    return measurement.value if measurement.observed else None


def _quantity(measurement: Measurement) -> float:
    """A reported quantity for one of TRI's two `NOT NULL DEFAULT 0` columns.

    Raises on an absence rather than writing the zero the column would force.
    `tri_release` cannot represent "did not report": the two media are NOT NULL
    and `air_lb` is `GENERATED ALWAYS AS (fugitive_air_lb + stack_air_lb)`, so a
    Form A written here becomes an observed zero and E3 reads a facility that
    declined to state a quantity as one that released nothing. Section 11 exists
    to prevent exactly that.

    Filtering those filings out is `TriAdapter.load`'s job and it does it, on the
    stated grounds that it is the only stage that knows what the table can hold.
    This is the backstop for that contract, not a second copy of the decision: an
    absence arriving here means the adapter stopped filtering, and a loud failure
    is the only safe response to a row that would otherwise be silently false.
    """
    if measurement.observed and measurement.value is not None:
        return measurement.value
    raise ValueError(
        "tri_release cannot store an unreported quantity; "
        "TriAdapter.load is responsible for excluding Form A filings"
    )


@dataclass(frozen=True)
class TableSpec:
    """How one record type becomes one row.

    `row` is explicit per table rather than derived from the pydantic field
    names. Three tables would defeat a generic mapper anyway — `hex_air_quality`
    renames `annual_mean` to a value/observed pair, `tri_release` splits a
    `Measurement` across three columns, and every geometry column is built from
    fields that are not it — and an explicit mapping is one a reviewer can check
    against the migration in a diff.
    """

    conflict: tuple[str, ...]
    row: Any  # Callable[[NormalizedRecord], dict[str, Any]]
    geometry: frozenset[str] = field(default_factory=frozenset)
    #: Columns written on insert and left alone on conflict.
    keep_on_update: frozenset[str] = field(default_factory=frozenset)
    #: Columns set to an expression on update only, e.g. a last-seen stamp.
    touch_on_update: Mapping[str, str] = field(default_factory=dict)


def _facility(r: Any) -> dict[str, Any]:
    # `air_source_ids` and `operating_status` are on the record and in no
    # column. Dropped here on purpose: adding columns for them is a migration
    # and a methodology question, not something a sink should do on the way past.
    return {
        "facility_id": r.facility_id,
        "registry_id": r.registry_id,
        "tri_facility_id": r.tri_facility_id,
        "name": r.name,
        "street": r.street,
        "city": r.city,
        "state": r.state,
        "zip5": r.zip5,
        "county_fips": r.county_fips,
        "naics_code": r.naics_code,
        "geom": _point(r.longitude, r.latitude),
        "h3": r.h3,
        "coordinate_status": r.coordinate_status,
        "geocode_quality": r.geocode_quality,
        "geocode_accuracy_m": r.geocode_accuracy_m,
        "reported_latitude": r.reported_latitude,
        "reported_longitude": r.reported_longitude,
        "is_major_source": r.is_major_source,
        "has_title_v": r.has_title_v,
        "is_rcra_lqg": r.is_rcra_lqg,
        "is_rcra_tsdf": r.is_rcra_tsdf,
        "echo_url": r.echo_url,
    }


def _compliance_quarter(r: Any) -> dict[str, Any]:
    return {
        "facility_id": r.facility_id,
        "quarter": r.quarter,
        "program": r.program,
        "status": r.status,
    }


def _enforcement_action(r: Any) -> dict[str, Any]:
    return {
        "action_id": r.action_id,
        "facility_id": r.facility_id,
        "program": r.program,
        "action_type": r.action_type,
        "settled_on": r.settled_on,
        "penalty_usd": r.penalty_usd,
        "is_formal": r.is_formal,
    }


def _tri_release(r: Any) -> dict[str, Any]:
    # `air_lb` is GENERATED ALWAYS AS (fugitive_air_lb + stack_air_lb) STORED and
    # is absent here for that reason: Postgres refuses a non-DEFAULT value for it.
    # It is therefore not a column that can hold an absence either, which is what
    # `_tri_is_storable` below exists to deal with.
    return {
        "facility_id": r.facility_id,
        "reporting_year": r.reporting_year,
        "cas_number": r.cas_number,
        "chemical_name": r.chemical_name,
        "fugitive_air_lb": _quantity(r.fugitive_air),
        "stack_air_lb": _quantity(r.stack_air),
    }


def _chemical_toxicity_weight(r: Any) -> dict[str, Any]:
    return {
        "cas_number": r.cas_number,
        "chemical_name": r.chemical_name,
        "rsei_weight": r.rsei_weight,
        "source_edition": r.source_edition,
    }


def _tract_exposure(r: Any) -> dict[str, Any]:
    return {
        "tract_geoid": r.tract_geoid,
        "vintage_year": r.vintage_year,
        "cancer_risk_per_million": _observed(r.cancer_risk_per_million),
        "respiratory_hazard_index": _observed(r.respiratory_hazard_index),
    }


def _hex_exposure(r: Any) -> dict[str, Any]:
    return {
        "h3": r.h3,
        "vintage_year": r.vintage_year,
        "cancer_risk_per_million": _observed(r.cancer_risk_per_million),
        "respiratory_hazard_index": _observed(r.respiratory_hazard_index),
        "cancer_risk_absence": r.cancer_risk_absence,
        "respiratory_hazard_absence": r.respiratory_hazard_absence,
        "tract_count": r.tract_count,
        "population": r.population,
    }


def _census_tract(r: Any) -> dict[str, Any]:
    return {
        "geoid": r.geoid,
        "state_fips": r.state_fips,
        "county_fips": r.county_fips,
        "name": r.name,
        "geom": f"SRID=4326;{r.geom_wkt}",
        "aland_m2": r.aland_m2,
        "awater_m2": r.awater_m2,
        "tiger_year": r.tiger_year,
    }


def _census_block(r: Any) -> dict[str, Any]:
    return {
        "geoid": r.geoid,
        "tract_geoid": r.tract_geoid,
        "geom": f"SRID=4326;{r.geom_wkt}",
        "population": r.population,
        "aland_m2": r.aland_m2,
    }


def _tract_variable(r: Any) -> dict[str, Any]:
    return {
        "tract_geoid": r.tract_geoid,
        "acs_vintage": r.acs_vintage,
        "variable": r.variable,
        "estimate": _observed(r.estimate),
        "margin_of_error": _observed(r.margin_of_error),
        "is_extensive": r.is_extensive,
    }


def _monitor(r: Any) -> dict[str, Any]:
    return {
        "monitor_id": r.monitor_id,
        "openaq_sensor_id": r.openaq_sensor_id,
        "name": r.name,
        "parameter": r.parameter,
        "geom": _point(r.longitude, r.latitude),
        "h3": r.h3,
        "is_regulatory": r.is_regulatory,
        "first_seen_on": r.first_seen_on,
        "last_seen_on": r.last_seen_on,
    }


def _monitor_measurement(r: Any) -> dict[str, Any]:
    return {
        "monitor_id": r.monitor_id,
        "parameter": r.parameter,
        "measured_on": r.measured_on,
        "value": r.value,
        "unit": r.unit,
        "observation_count": r.observation_count,
    }


def _hex_air_quality(r: Any) -> dict[str, Any]:
    return {
        "h3": r.h3,
        "parameter": r.parameter,
        # The record calls it `annual_mean`; the table splits it in two. This
        # rename is why the mapping is per table rather than by field name.
        "value": _observed(r.annual_mean),
        "observed": r.annual_mean.observed,
        "unit": r.unit,
        "window_start": r.window_start,
        "window_end": r.window_end,
        "nearest_monitor_id": r.nearest_monitor_id,
        "nearest_monitor_km": r.nearest_monitor_km,
        "monitors_used": r.monitors_used,
        "day_count": r.day_count,
        "observation_count": r.observation_count,
        "latest_measured_on": r.latest_measured_on,
    }


SPECS: Mapping[str, TableSpec] = {
    "facility": TableSpec(
        conflict=("facility_id",),
        row=_facility,
        geometry=frozenset({"geom"}),
        # A facility first seen in March did not start existing tonight.
        keep_on_update=frozenset({"first_seen_at"}),
        touch_on_update={"last_seen_at": "now()"},
    ),
    "facility_compliance_quarter": TableSpec(
        conflict=("facility_id", "quarter", "program"), row=_compliance_quarter
    ),
    "enforcement_action": TableSpec(conflict=("action_id",), row=_enforcement_action),
    # The surrogate `release_id` is a bigserial nothing upstream knows. Conflict
    # on the natural key the unique constraint carries instead.
    "tri_release": TableSpec(
        conflict=("facility_id", "reporting_year", "cas_number"), row=_tri_release
    ),
    "chemical_toxicity_weight": TableSpec(conflict=("cas_number",), row=_chemical_toxicity_weight),
    "tract_exposure": TableSpec(conflict=("tract_geoid", "vintage_year"), row=_tract_exposure),
    "hex_exposure": TableSpec(conflict=("h3", "vintage_year"), row=_hex_exposure),
    "census_tract": TableSpec(conflict=("geoid",), row=_census_tract, geometry=frozenset({"geom"})),
    "census_block": TableSpec(conflict=("geoid",), row=_census_block, geometry=frozenset({"geom"})),
    "tract_demographics": TableSpec(
        conflict=("tract_geoid", "acs_vintage", "variable"), row=_tract_variable
    ),
    "tract_race_ethnicity": TableSpec(
        conflict=("tract_geoid", "acs_vintage", "variable"), row=_tract_variable
    ),
    "monitor": TableSpec(conflict=("monitor_id",), row=_monitor, geometry=frozenset({"geom"})),
    "monitor_measurement": TableSpec(
        conflict=("monitor_id", "parameter", "measured_on"), row=_monitor_measurement
    ),
    "hex_air_quality": TableSpec(conflict=("h3", "parameter"), row=_hex_air_quality),
}

#: Parents before children, because every child here carries a real foreign key.
#: Tables absent from a run are skipped; the order is a sort key, not a schedule.
WRITE_ORDER: tuple[str, ...] = (
    "census_tract",
    # After tracts: census_block.tract_geoid is a real foreign key.
    "census_block",
    "facility",
    "facility_compliance_quarter",
    "enforcement_action",
    "chemical_toxicity_weight",
    "tri_release",
    "tract_exposure",
    "hex_exposure",
    "tract_demographics",
    "tract_race_ethnicity",
    "monitor",
    "monitor_measurement",
    "hex_air_quality",
)


def _vintage_end(metadata: PullMetadata) -> date:
    """The last date the data describes, for `source_snapshot.vintage_end`.

    **This is a derivation, not a reported value, and it wants methodology
    sign-off.** The column is `NOT NULL` and drives the `c_recency` term of
    section 12, but `PullMetadata` carries only a free-text `vintage` and the
    pull timestamp. The honest fix is a `vintage_end` field on the adapter
    interface, set per source by the adapter that knows what its release covers;
    until that exists this rule stands in for it:

    the last four-digit year in the vintage string, taken as 31 December of that
    year, and the pull date when the vintage names no year — then clamped so it
    is never later than the day the data was retrieved. So "TRI 2023" and "ACS
    2019-2023" both end 2023-12-31, while ECHO's "weekly/2026-09-20" ends on the
    day it was pulled rather than at the end of the year it names.

    That clamp is not a detail. Without it a source whose vintage carries the
    current year dates itself into the future, and `c_recency` reads the load as
    fresher than it is for as long as the year lasts. A vintage_end after the
    retrieval is a statement about data nobody has yet.

    The failure mode that remains: a source whose vintage names a *model*
    version that happens to look like a year would date itself wrongly, and the
    recency term would drift. `epa_rsei` is the candidate.
    """
    years = _year_tokens(metadata.vintage)
    pulled_on = metadata.pulled_at.date()
    if years:
        return min(date(max(years), 12, 31), pulled_on)
    return pulled_on


def _year_tokens(vintage: str) -> list[int]:
    """Every plausible four-digit calendar year in a vintage string."""
    found: list[int] = []
    digits = ""
    for char in vintage + " ":
        if char.isdigit():
            digits += char
        else:
            if len(digits) == 4 and 1900 <= int(digits) <= 2100:
                found.append(int(digits))
            digits = ""
    return found


def _snapshot_fields(metadata: PullMetadata) -> dict[str, Any]:
    """The `source_snapshot` row for this pull.

    A pull with no artifact still gets a row: the fact tables cannot be written
    without one, and a load whose provenance is thin should be visible as thin
    rather than absent. `url` and `checksum` are NOT NULL, so an artifact-less
    pull records the sentinels below and says so in `notes`.
    """
    artifact = metadata.artifacts[0] if metadata.artifacts else None
    try:
        source = SNAPSHOT_SOURCE[metadata.source]
    except KeyError:
        raise UnmappedTable(
            f"{metadata.source!r} has no source_snapshot.source value; "
            f"known: {', '.join(sorted(SNAPSHOT_SOURCE))}"
        ) from None
    notes = "; ".join(metadata.notes) or None
    if artifact is None:
        notes = "; ".join(filter(None, [notes, "pull recorded no artifact"]))
    return {
        "source": source,
        "url": artifact.url if artifact else "",
        "retrieved_at": artifact.retrieved_at if artifact else metadata.pulled_at,
        "checksum": artifact.sha256 if artifact else "",
        "record_count": metadata.record_count,
        "vintage": metadata.vintage,
        "vintage_end": _vintage_end(metadata),
        "is_mirror": bool(artifact and artifact.from_snapshot),
        "notes": notes,
    }


def _insert(table: str, spec: TableSpec, columns: Sequence[str]) -> str:
    """One upsert statement, built for the columns this run actually carries."""
    placeholders: list[str] = []
    for index, column in enumerate(columns, start=1):
        if column in spec.geometry:
            placeholders.append(f"ST_GeomFromEWKT(${index})")
        else:
            placeholders.append(f"${index}")

    updatable = [
        column
        for column in columns
        if column not in spec.conflict and column not in spec.keep_on_update
    ]
    assignments = [f"{column} = EXCLUDED.{column}" for column in updatable] + [
        f"{column} = {expression}" for column, expression in spec.touch_on_update.items()
    ]

    # A row whose every column is part of the key has nothing to update, and
    # `DO UPDATE SET` with an empty list is a syntax error.
    action = f"DO UPDATE SET {', '.join(assignments)}" if assignments else "DO NOTHING"
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT ({', '.join(spec.conflict)}) {action}"
    )


class PostgresSink:
    """Transactional destination for one adapter run, backed by PostGIS.

    Staging is in memory and keyed by natural key, exactly as `InMemorySink`
    does it, so a source that emits the same record twice in one pull writes it
    once. `commit` is where the database is touched at all.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._staged: dict[str, dict[tuple[str, ...], NormalizedRecord]] = {}
        self._open: str | None = None
        self.snapshot_id: int | None = None

    async def begin(self, source: str) -> None:
        if source not in SNAPSHOT_SOURCE:
            raise UnmappedTable(
                f"{source!r} cannot be written to Postgres; "
                f"source_snapshot.source allows: {', '.join(sorted(SNAPSHOT_SOURCE))}"
            )
        self._open = source
        self._staged = {}
        self.snapshot_id = None

    async def write(self, table: str, records: Sequence[NormalizedRecord]) -> int:
        if table not in SPECS:
            raise UnmappedTable(f"no column mapping for table {table!r}")
        staged = self._staged.setdefault(table, {})
        for record in records:
            staged[record.natural_key()] = record
        return len(records)

    async def commit(self, metadata: PullMetadata) -> None:
        """Write the snapshot, then every staged table, in one transaction."""
        snapshot = _snapshot_fields(metadata)
        async with self._connection.transaction():
            # `source_snapshot_content_key` is unique on (source, checksum), on
            # the stated ground that two pulls of the same bytes are the same
            # snapshot. So a re-pull of an unchanged file reuses the row rather
            # than failing or minting a second identity for one artifact. The
            # update refreshes what the pull learned and leaves `retrieved_at`
            # alone: the first sighting of these bytes is the honest answer to
            # when this version of upstream appeared.
            snapshot_id = await self._connection.fetchval(
                "INSERT INTO source_snapshot "
                "(source, url, retrieved_at, checksum, record_count, vintage, "
                " vintage_end, is_mirror, notes) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                "ON CONFLICT (source, checksum) DO UPDATE SET "
                "  record_count = EXCLUDED.record_count, "
                "  vintage = EXCLUDED.vintage, "
                "  vintage_end = EXCLUDED.vintage_end, "
                "  is_mirror = EXCLUDED.is_mirror, "
                "  notes = EXCLUDED.notes "
                "RETURNING snapshot_id",
                *(
                    snapshot[key]
                    for key in (
                        "source",
                        "url",
                        "retrieved_at",
                        "checksum",
                        "record_count",
                        "vintage",
                        "vintage_end",
                        "is_mirror",
                        "notes",
                    )
                ),
            )
            for table in WRITE_ORDER:
                records = self._staged.get(table)
                if not records:
                    continue
                await self._flush(table, list(records.values()), snapshot_id)
            self.snapshot_id = snapshot_id
        self._staged = {}
        self._open = None

    async def _flush(
        self, table: str, records: Sequence[NormalizedRecord], snapshot_id: int
    ) -> None:
        spec = SPECS[table]
        rows = [{**spec.row(record), "snapshot_id": snapshot_id} for record in records]
        columns = tuple(rows[0])
        statement = _insert(table, spec, columns)
        await self._connection.executemany(
            statement, [tuple(row[column] for column in columns) for row in rows]
        )

    async def rollback(self) -> None:
        """Discard the staged rows. Nothing reached the database to undo."""
        self._staged = {}
        self._open = None
        self.snapshot_id = None
