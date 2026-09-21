"""The Postgres sink's contract, without a Postgres.

The two properties CS-006 names are the two worth testing here: upsert on the
natural key, and all-or-nothing commit with the metadata. Both are observable
from the statements the sink emits and the order it emits them in, so these run
against a recording connection rather than a database. The statements that need
a real planner — the geometry expressions, the conflict targets actually
matching a constraint — are covered by `test_sinks_postgres_live.py`, which
skips unless a database URL is exported.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest

from pipeline.adapters.echo import ComplianceQuarter, EnforcementAction, Facility
from pipeline.adapters.tri import TriRelease
from pipeline.metadata import Artifact, PullMetadata, RecordCounts
from pipeline.records import Measurement
from pipeline.sinks_postgres import (
    SNAPSHOT_SOURCE,
    SPECS,
    WRITE_ORDER,
    PostgresSink,
    UnmappedTable,
    _insert,
    _vintage_end,
)


class RecordingConnection:
    """Captures what the sink would run. Raises on demand, to test rollback."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.transactions = 0
        self.fail_on = fail_on
        self.next_snapshot_id = 7

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return self.next_snapshot_id

    async def executemany(self, query: str, args: Any) -> Any:
        rows = list(args)
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("upstream of the commit")
        self.calls.append((query, rows))
        return None

    @asynccontextmanager
    async def _transaction(self) -> Any:
        self.transactions += 1
        yield self

    def transaction(self) -> Any:
        return self._transaction()

    def statements(self) -> list[str]:
        return [query for query, _ in self.calls]

    def rows_for(self, table: str) -> list[Any]:
        for query, payload in self.calls:
            if query.startswith(f"INSERT INTO {table} "):
                return list(payload)
        return []


def facility(facility_id: str, *, name: str = "A Plant", lat: float | None = 30.2) -> Facility:
    return Facility(
        facility_id=facility_id,
        registry_id=f"reg-{facility_id}",
        name=name,
        street=None,
        city="GEISMAR",
        state="LA",
        zip5="70734",
        county_fips="047",
        naics_code=None,
        latitude=lat,
        longitude=-91.0 if lat is not None else None,
        reported_latitude=lat,
        reported_longitude=-91.0 if lat is not None else None,
        h3=None,
        coordinate_status="ok" if lat is not None else "missing",
        geocode_quality="ok" if lat is not None else "absent",
        geocode_accuracy_m=None,
        is_major_source=True,
        has_title_v=True,
        echo_url="https://echo.epa.gov/x",
        air_source_ids=("LA0001",),
        operating_status="Operating",
    )


def metadata(source: str = "epa_echo", *, vintage: str = "2026-09-12") -> PullMetadata:
    return PullMetadata(
        source=source,
        source_title="EPA ECHO",
        vintage=vintage,
        pulled_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        status="ok",
        counts=RecordCounts(loaded=1),
        artifacts=(
            Artifact(
                url="https://echodata.epa.gov/x",
                retrieved_at=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
                sha256="abc123",
                size_bytes=10,
            ),
        ),
    )


async def test_commit_writes_snapshot_before_facts() -> None:
    """Every fact row carries snapshot_id NOT NULL, so the order is not optional."""
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    await sink.write("facility", [facility("F1")])
    await sink.commit(metadata())

    statements = connection.statements()
    assert "source_snapshot" in statements[0]
    assert statements[1].startswith("INSERT INTO facility ")
    assert connection.transactions == 1
    assert sink.snapshot_id == 7


async def test_an_unchanged_re_pull_reuses_its_snapshot_row() -> None:
    """(source, checksum) is unique: the same bytes are the same snapshot.

    A source whose artifact does not change between runs — TRI publishes one
    stable file — would otherwise fail on `source_snapshot_content_key` the
    second night.
    """
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_tri")
    await sink.write("facility", [facility("F1")])
    await sink.commit(metadata("epa_tri", vintage="TRI 2023"))

    statement = connection.statements()[0]
    assert "ON CONFLICT (source, checksum) DO UPDATE" in statement
    # retrieved_at is deliberately not refreshed; it dates the bytes, not the run.
    assert "retrieved_at = EXCLUDED" not in statement


async def test_every_fact_row_carries_the_new_snapshot_id() -> None:
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    await sink.write("facility", [facility("F1"), facility("F2")])
    await sink.commit(metadata())

    rows = connection.rows_for("facility")
    assert len(rows) == 2
    assert all(row[-1] == 7 for row in rows), "snapshot_id is appended last"


async def test_duplicate_natural_keys_collapse_to_one_row() -> None:
    """The in-memory reference dedupes by natural key; so does this one."""
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    written = await sink.write(
        "facility", [facility("F1", name="First"), facility("F1", name="Second")]
    )
    await sink.commit(metadata())

    assert written == 2, "write reports what it was handed"
    rows = connection.rows_for("facility")
    assert len(rows) == 1, "but only the last record for a key is staged"
    assert "Second" in rows[0]


async def test_parents_are_written_before_children() -> None:
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    await sink.write(
        "enforcement_action",
        [
            EnforcementAction(
                action_id="A1",
                facility_id="F1",
                program="CAA",
                action_type="FRV",
                settled_on=date(2025, 1, 1),
                penalty_usd=100.0,
                is_formal=True,
            )
        ],
    )
    await sink.write(
        "facility_compliance_quarter",
        [
            ComplianceQuarter(
                facility_id="F1", quarter=date(2025, 1, 1), program="CAA", status="violation"
            )
        ],
    )
    await sink.write("facility", [facility("F1")])
    await sink.commit(metadata())

    order = [s.split()[2] for s in connection.statements() if s.startswith("INSERT INTO")]
    assert order.index("facility") < order.index("facility_compliance_quarter")
    assert order.index("facility") < order.index("enforcement_action")


async def test_a_failed_flush_leaves_nothing_committed() -> None:
    connection = RecordingConnection(fail_on="INSERT INTO facility ")
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    await sink.write("facility", [facility("F1")])

    with pytest.raises(RuntimeError):
        await sink.commit(metadata())
    # The transaction context manager is what unwinds the snapshot row; the
    # sink's job is not to have recorded a successful commit.
    assert sink.snapshot_id is None


async def test_rollback_discards_staged_records() -> None:
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_echo")
    await sink.write("facility", [facility("F1")])
    await sink.rollback()
    await sink.begin("epa_echo")
    await sink.commit(metadata())

    assert connection.rows_for("facility") == []


async def test_unknown_table_raises_rather_than_dropping() -> None:
    sink = PostgresSink(RecordingConnection())
    await sink.begin("epa_echo")
    with pytest.raises(UnmappedTable):
        await sink.write("fake_station_readings", [])


async def test_unknown_source_is_refused_at_begin() -> None:
    """`fake` has no source_snapshot.source value, so it cannot load."""
    sink = PostgresSink(RecordingConnection())
    with pytest.raises(UnmappedTable):
        await sink.begin("fake")


async def test_tri_never_inserts_the_generated_column() -> None:
    """`air_lb` is GENERATED ALWAYS; naming it in an INSERT is an error."""
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_tri")
    await sink.write(
        "tri_release",
        [
            TriRelease(
                facility_id="F1",
                reporting_year=2023,
                cas_number="71-43-2",
                chemical_name="Benzene",
                fugitive_air=Measurement.of(1.5),
                stack_air=Measurement.of(2.5),
            )
        ],
    )
    await sink.commit(metadata("epa_tri", vintage="TRI 2023"))

    statement = next(s for s in connection.statements() if s.startswith("INSERT INTO tri_release"))
    assert "air_lb" not in statement.split("VALUES")[0].replace("fugitive_air_lb", "").replace(
        "stack_air_lb", ""
    )


async def test_an_unreported_quantity_fails_loudly() -> None:
    """Section 11's backstop.

    `TriAdapter.load` excludes Form A filings and says it is the only stage
    entitled to. If one reaches the sink anyway, writing it would make `air_lb`
    compute to 0 — indistinguishable from a Form R that genuinely reported
    nothing. Raising is the only safe answer.
    """
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_tri")
    await sink.write(
        "tri_release",
        [
            TriRelease(
                facility_id="F1",
                reporting_year=2023,
                cas_number="71-43-2",
                chemical_name="Benzene",
                fugitive_air=Measurement.absent(),
                stack_air=Measurement.absent(),
            )
        ],
    )
    with pytest.raises(ValueError, match="unreported quantity"):
        await sink.commit(metadata("epa_tri", vintage="TRI 2023"))


async def test_a_reported_zero_is_still_written() -> None:
    """The other half of section 11: zero is a perfectly good observation."""
    connection = RecordingConnection()
    sink = PostgresSink(connection)
    await sink.begin("epa_tri")
    await sink.write(
        "tri_release",
        [
            TriRelease(
                facility_id="F1",
                reporting_year=2023,
                cas_number="71-43-2",
                chemical_name="Benzene",
                fugitive_air=Measurement.of(0.0),
                stack_air=Measurement.of(0.0),
            )
        ],
    )
    await sink.commit(metadata("epa_tri", vintage="TRI 2023"))

    assert len(connection.rows_for("tri_release")) == 1


def test_tri_conflicts_on_its_natural_key_not_its_surrogate() -> None:
    assert SPECS["tri_release"].conflict == ("facility_id", "reporting_year", "cas_number")


def test_geometry_columns_are_built_with_an_expression() -> None:
    statement = _insert("facility", SPECS["facility"], ("facility_id", "geom"))
    assert "ST_GeomFromEWKT($2)" in statement
    assert "ON CONFLICT (facility_id)" in statement


def test_first_seen_at_survives_an_update() -> None:
    statement = _insert("facility", SPECS["facility"], ("facility_id", "name", "first_seen_at"))
    assert "first_seen_at = EXCLUDED" not in statement
    assert "last_seen_at = now()" in statement


def test_a_key_only_table_does_nothing_on_conflict() -> None:
    """`DO UPDATE SET` with no assignments is a syntax error, not an empty update."""
    spec = SPECS["facility_compliance_quarter"]
    statement = _insert("facility_compliance_quarter", spec, ("facility_id", "quarter", "program"))
    assert statement.endswith("DO NOTHING")


@pytest.mark.parametrize(
    ("vintage", "expected"),
    [
        ("TRI 2023", date(2023, 12, 31)),
        ("ACS 2019-2023", date(2023, 12, 31)),
        ("AirToxScreen 2020", date(2020, 12, 31)),
        # No year in the string: falls back to the pull date.
        ("v2.3.11", date(2026, 9, 20)),
        # ECHO's vintage carries the current year. Without the clamp this dates
        # itself to 2026-12-31 and reads as fresher than it is until New Year.
        ("weekly/2026-09-20", date(2026, 9, 20)),
    ],
)
def test_vintage_end_takes_the_last_year_it_can_find(vintage: str, expected: date) -> None:
    assert _vintage_end(metadata(vintage=vintage)) == expected


def test_vintage_end_is_never_after_the_pull() -> None:
    """A snapshot cannot describe data that did not exist when it was fetched."""
    for vintage in ("weekly/2026-09-20", "TRI 2026", "ACS 2022-2026", "2099"):
        pull = metadata(vintage=vintage)
        assert _vintage_end(pull) <= pull.pulled_at.date()


def test_every_table_an_adapter_writes_has_a_column_mapping() -> None:
    """The mapping is what `--load` needs and only discovers at write time.

    Without this, a source whose table is missing from SPECS fetches its whole
    upstream — forty minutes, for the block layer — and then dies on the first
    `write`. The registry knows every adapter and every record type declares its
    table, so the pairing can be checked in a tenth of a second instead.
    """
    import importlib
    import pkgutil

    import pipeline.adapters as adapters_package
    from pipeline.records import NormalizedRecord

    # Importing every adapter module is what populates NormalizedRecord's
    # subclass list; the registry only holds the adapters themselves.
    for module in pkgutil.iter_modules(adapters_package.__path__):
        importlib.import_module(f"pipeline.adapters.{module.name}")

    def concrete(cls: type) -> list[type]:
        found = []
        for sub in cls.__subclasses__():
            # Only the shipped adapters. Test modules define their own record
            # types, and a full-suite run would otherwise demand sink mappings
            # for fixtures that no adapter ever writes.
            if getattr(sub, "table", None) and sub.__module__.startswith("pipeline."):
                found.append(sub)
            found.extend(concrete(sub))
        return found

    tables = {str(record.table) for record in concrete(NormalizedRecord)}  # type: ignore[attr-defined]
    # The reference adapter writes to a table no migration creates, and
    # SNAPSHOT_SOURCE already refuses it by name.
    tables.discard("fake_station_readings")

    missing = sorted(tables - set(SPECS))
    assert not missing, f"no sink column mapping for: {', '.join(missing)}"

    unordered = sorted(set(SPECS) - set(WRITE_ORDER))
    assert not unordered, f"mapped but never flushed, missing from WRITE_ORDER: {unordered}"


def test_every_registry_source_that_can_load_has_a_snapshot_name() -> None:
    """A source the schema's CHECK would reject must fail loudly, not at 3am."""
    from pipeline.adapters import names

    loadable = set(names()) - {"fake"}
    assert loadable == set(SNAPSHOT_SOURCE)
