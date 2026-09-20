"""The drill-down query, against a real database.

Same bargain as test_facility_hex_sql.py: everything else under api/tests runs
without a database, and this cannot, because what is being checked is the join
across hex, hex_score, hex_indicator, hex_demographics and the facility
geography, and a mock of that would only prove the mock agrees with itself.

It skips unless CLEARSKIES_TEST_DATABASE_URL names a database with the
migration set applied, which is what CI's `database` job already has up. The
seed lives in a transaction that is always rolled back.

Three hexagons, because there are three distinct answers a valid resolution 8
cell can get and they are easy to confuse:

    scored      a score, and the fifteen indicators behind it
    unscorable  no score, and a reason, which is an answer and so is a 200
    ungraded    in the grid, nothing recorded for this run, which is a 404
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from math import cos, radians

import asyncpg
import h3
import pytest

from app import hex_detail, runs

log = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("CLEARSKIES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set CLEARSKIES_TEST_DATABASE_URL to a migrated database to run the spatial tests",
)

BATON_ROUGE = (30.4515, -91.1871)
LAKE_CHARLES = (30.2266, -93.2174)
MONROE = (32.5093, -92.1193)

METRES_PER_DEGREE_LAT = 111_194.9

# Every indicator that is seeded as observed. The remainder are left out of
# hex_indicator entirely, which is how an absent indicator is recorded.
OBSERVED = {
    "E1": (42.0, 88.1),
    "E2": (1.4, 71.2),
    "E3": (9100.0, 95.5),
    "F1": (3.2, 80.0),
    "F2": (1.1, 66.4),
    "S1": (7.4, 55.0),
    "S2": (14.1, 48.3),
    "P1": (41.2, 84.7),
    "P2": (18.0, 77.9),
    "P3": (4.5, 61.1),
    "P4": (9.8, 82.4),
}


def west_of(latitude: float, longitude: float, metres: float) -> tuple[float, float]:
    degrees = metres / (METRES_PER_DEGREE_LAT * cos(radians(latitude)))
    return (latitude, longitude - degrees)


def boundary_wkt(cell: str) -> str:
    ring = [*h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{lon} {lat}" for lat, lon in ring) + "))"


async def seed_hex(conn: asyncpg.Connection, anchor: tuple[float, float]) -> str:
    cell = str(h3.latlng_to_cell(anchor[0], anchor[1], 8))
    latitude, longitude = h3.cell_to_latlng(cell)
    await conn.execute(
        """
        INSERT INTO hex (h3, resolution, centroid, boundary, state_fips, county_fips,
                         parish_name, in_pilot_state, land_fraction)
        VALUES ($1, 8, ST_SetSRID(ST_MakePoint($3, $2), 4326),
                ST_GeomFromText($4, 4326), '22', '033', 'East Baton Rouge', true, 0.98)
        ON CONFLICT (h3) DO UPDATE
            SET centroid = EXCLUDED.centroid, boundary = EXCLUDED.boundary
        """,
        cell,
        latitude,
        longitude,
        boundary_wkt(cell),
    )
    return cell


@dataclass
class Seed:
    conn: asyncpg.Connection
    run_id: int
    scored: str
    unscorable: str
    ungraded: str


@pytest.fixture
async def seeded() -> AsyncIterator[Seed]:
    conn = await asyncpg.connect(DATABASE_URL)
    transaction = conn.transaction()
    await transaction.start()
    runs.reset_cache()
    try:
        # Every source behind an observed indicator below. A run that scored E3
        # and read no TRI snapshot would be a run whose panel cannot cite what
        # it displays, which is the thing this file is checking.
        snapshots: dict[str, int] = {}
        for source, vintage, vintage_end in (
            ("echo", "ECHO 2026Q1", date(2026, 3, 31)),
            ("tri", "TRI 2023", date(2023, 12, 31)),
            ("airtoxscreen", "AirToxScreen 2020", date(2020, 12, 31)),
            ("acs", "ACS 2019-2023", date(2023, 12, 31)),
        ):
            snapshots[source] = await conn.fetchval(
                """
                INSERT INTO source_snapshot (source, url, retrieved_at, checksum,
                                             vintage, vintage_end)
                VALUES ($1, 'test://' || $1, now(), 'seed-' || $1, $2, $3)
                RETURNING snapshot_id
                """,
                source,
                vintage,
                vintage_end,
            )
        echo_snapshot = snapshots["echo"]

        run_id: int = await conn.fetchval(
            """
            INSERT INTO pipeline_run (started_at, finished_at, status, git_sha,
                                      methodology_version, scored_hexes, is_current)
            VALUES (now() - interval '1 hour', now(), 'succeeded', 'abc1234', '0.1.0', 2, true)
            RETURNING run_id
            """
        )
        await conn.executemany(
            "INSERT INTO pipeline_run_source (run_id, snapshot_id) VALUES ($1, $2)",
            [(run_id, snapshot_id) for snapshot_id in snapshots.values()],
        )

        scored = await seed_hex(conn, BATON_ROUGE)
        unscorable = await seed_hex(conn, LAKE_CHARLES)
        ungraded = await seed_hex(conn, MONROE)

        await conn.execute(
            """
            INSERT INTO hex_score (run_id, h3, score, percentile, pollution_burden,
                                   population_characteristics, exposures_mean, env_effects_mean,
                                   sensitive_mean, socioeconomic_mean, confidence,
                                   confidence_band, c_coverage, c_recency, c_spatial, c_monitor,
                                   nearest_monitor_km)
            VALUES ($1, $2, 71.4, 93.2, 8.4, 8.5, 84.9, 73.2, 51.7, 76.5, 0.72,
                    'moderate', 0.80, 0.65, 0.70, 0.75, 12.4)
            """,
            run_id,
            scored,
        )
        # Scored as unscorable: no score, and the reason why.
        await conn.execute(
            """
            INSERT INTO hex_score (run_id, h3, no_score_reason)
            VALUES ($1, $2, 'low_population')
            """,
            run_id,
            unscorable,
        )

        await conn.executemany(
            """
            INSERT INTO hex_indicator (run_id, h3, indicator_id, value, percentile, observed)
            VALUES ($1, $2, $3, $4, $5, true)
            """,
            [(run_id, scored, key, v, p) for key, (v, p) in OBSERVED.items()],
        )

        await conn.execute(
            """
            INSERT INTO hex_demographics (run_id, h3, population, households, under_5_pct,
                                          over_64_pct, poverty_200pct, black_pct, hispanic_pct,
                                          people_of_color_pct, acs_vintage)
            VALUES ($1, $2, 2417, 940, 7.4, 14.1, 41.2, 62.8, 3.9, 68.1, '2019-2023')
            """,
            run_id,
            scored,
        )

        # Two facilities inside the radius of the scored hexagon and one well
        # outside it, so the panel's list is a claim the assertions can check.
        latitude, longitude = h3.cell_to_latlng(scored)
        for name, (lat, lon) in {
            "REFINERY": (latitude, longitude),
            "NEARBY": west_of(latitude, longitude, 4_000),
            "DISTANT": west_of(latitude, longitude, 40_000),
        }.items():
            await conn.execute(
                """
                INSERT INTO facility (facility_id, registry_id, name, state, geom, h3,
                                      coordinate_status, geocode_quality, is_major_source,
                                      has_title_v, echo_url, snapshot_id)
                VALUES ($1, $1, $2, 'LA', ST_SetSRID(ST_MakePoint($4, $3), 4326), $5,
                        'ok', 'verified', true, true, $6, $7)
                """,
                name,
                f"TEST {name}",
                lat,
                lon,
                str(h3.latlng_to_cell(lat, lon, 8)),
                f"https://echo.epa.gov/detailed-facility-report?fid={name}",
                echo_snapshot,
            )

        # Enforcement inside the five-year window ending at the run, and one
        # settled six years before it, which the window must exclude.
        await conn.execute(
            """
            INSERT INTO enforcement_action (action_id, facility_id, program, settled_on,
                                            penalty_usd, is_formal, snapshot_id)
            VALUES ('recent', 'NEARBY', 'CAA', current_date - 400, 50000, true, $1),
                   ('ancient', 'NEARBY', 'CAA', current_date - 2200, 90000, true, $1)
            """,
            echo_snapshot,
        )
        await conn.execute(
            """
            INSERT INTO facility_compliance_quarter (facility_id, quarter, program, status,
                                                     snapshot_id)
            VALUES ('NEARBY', date '2025-01-01', 'CAA', 'high_priority_violation', $1),
                   ('NEARBY', date '2025-04-01', 'CAA', 'violation', $1)
            """,
            echo_snapshot,
        )

        # Background facilities, so the planner faces a realistic table rather
        # than three rows it will always scan.
        await conn.execute(
            """
            INSERT INTO facility (facility_id, registry_id, name, state, geom,
                                  coordinate_status, geocode_quality, snapshot_id)
            SELECT 'BG' || g, 'BG' || g, 'background', 'LA',
                   ST_SetSRID(ST_MakePoint(-92.2 + random(), 31.4 + random()), 4326),
                   'ok', 'plausible', $1
              FROM generate_series(1, 500) AS g
            """,
            echo_snapshot,
        )
        await conn.execute("ANALYZE facility")

        yield Seed(conn, run_id, scored, unscorable, ungraded)
    finally:
        await transaction.rollback()
        await conn.close()
        runs.reset_cache()


# ---- the run the API serves ---------------------------------------------


async def test_the_current_run_carries_its_methodology_version(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)

    assert run is not None
    assert run.run_id == seeded.run_id
    assert run.methodology_version == "0.1.0"


async def test_the_vintage_map_is_keyed_the_way_the_indicators_are(seeded: Seed) -> None:
    """The panel cites a vintage per indicator, so the keys have to line up."""
    run = await runs.current(seeded.conn)
    assert run is not None

    assert run.data_vintage["EPA ECHO"] == "ECHO 2026Q1"
    assert run.data_vintage["US Census ACS"] == "ACS 2019-2023"

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None
    cited = {i.source for i in detail.indicators if i.observed}
    assert cited <= set(detail.data_vintage), "an indicator cites a source with no vintage"


# ---- the scored hexagon --------------------------------------------------


async def test_the_score_and_its_percentile_come_back(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)

    assert detail is not None
    assert detail.h3 == seeded.scored
    assert detail.resolution == 8
    assert detail.state == "22"
    assert detail.parish == "East Baton Rouge"
    assert detail.score == pytest.approx(71.4)
    assert detail.percentile == pytest.approx(93.2)
    assert detail.no_score_reason is None
    assert detail.methodology_version == "0.1.0"


async def test_all_fifteen_indicators_are_returned_present_or_not(seeded: Seed) -> None:
    """Section 11: an absent indicator is dropped, never imputed, and always shown."""
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    assert len(detail.indicators) == 15
    observed = {i.id for i in detail.indicators if i.observed}
    assert observed == set(OBSERVED)

    dropped = [i for i in detail.indicators if not i.observed]
    assert {i.id for i in dropped} == {"E4", "F3", "F4", "P5"}
    for indicator in dropped:
        assert indicator.value is None, "a dropped indicator must not carry a value"
        assert indicator.percentile is None


async def test_the_centroid_is_returned_as_lon_lat(seeded: Seed) -> None:
    """The schema says lon, lat. The map library reads it that way and a swap is silent."""
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    lon, lat = detail.centroid
    assert -94.5 < lon < -88.5, "longitude outside Louisiana; lon and lat look swapped"
    assert 28.5 < lat < 33.5


async def test_both_components_decompose_into_their_groups(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    by_component = {c.component.value: c for c in detail.components}
    assert set(by_component) == {"pollution_burden", "population_characteristics"}
    assert by_component["pollution_burden"].score == pytest.approx(8.4)

    groups = {g.group.value: g for c in detail.components for g in c.groups}
    assert groups["exposures"].mean_percentile == pytest.approx(84.9)
    assert groups["environmental_effects"].weight == 0.5

    # Three of four exposures observed, two required.
    assert groups["exposures"].indicators_present == 3
    assert groups["exposures"].computable is True
    # Four of five socioeconomic observed against a minimum of four.
    assert groups["socioeconomic_factors"].indicators_present == 4
    assert groups["socioeconomic_factors"].computable is True
    # Two of four environmental effects observed against a minimum of two.
    assert groups["environmental_effects"].indicators_present == 2
    assert groups["environmental_effects"].computable is True


async def test_the_confidence_breakdown_is_the_four_terms(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    assert detail.confidence.value == pytest.approx(0.72)
    assert detail.confidence.band == "moderate"
    assert detail.confidence.coverage == pytest.approx(0.80)
    assert detail.confidence.recency == pytest.approx(0.65)
    assert detail.confidence.spatial_support == pytest.approx(0.70)
    assert detail.confidence.monitor_support == pytest.approx(0.75)
    assert detail.confidence.nearest_monitor_km == pytest.approx(12.4)


async def test_demographics_are_returned_and_are_not_in_the_components(seeded: Seed) -> None:
    """Section 14: displayed, never scored."""
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    assert detail.demographics.population == 2417
    assert detail.demographics.black_pct == pytest.approx(62.8)

    scored_ids = {i.id for i in detail.indicators}
    assert "black_pct" not in scored_ids


# ---- the facilities ------------------------------------------------------


async def test_contributing_facilities_come_back_with_their_epa_links(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    names = {f.registry_id for f in detail.facilities}
    assert "REFINERY" in names
    assert "NEARBY" in names
    assert "DISTANT" not in names, "40 km away is outside the 10 km interaction radius"

    for facility in detail.facilities:
        assert facility.echo_url.startswith("https://echo.epa.gov/"), "no link to the EPA record"

    refinery = next(f for f in detail.facilities if f.registry_id == "REFINERY")
    assert refinery.in_hex is True
    assert refinery.program == "CAA Title V"

    nearby = next(f for f in detail.facilities if f.registry_id == "NEARBY")
    assert nearby.in_hex is False
    assert nearby.distance_km == pytest.approx(4.0, abs=0.2)
    assert nearby.quarters_in_noncompliance == 2


async def test_the_enforcement_window_is_five_years_from_the_run(seeded: Seed) -> None:
    """One action settled inside the window, one six years back that must not count."""
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.scored, run)
    assert detail is not None

    nearby = next(f for f in detail.facilities if f.registry_id == "NEARBY")
    assert nearby.formal_actions_5yr == 1


# ---- the other two answers -----------------------------------------------


async def test_an_unscorable_hexagon_is_a_200_with_its_reason(seeded: Seed) -> None:
    """ "Too few people live here" is an answer, and a 404 would discard it."""
    run = await runs.current(seeded.conn)
    assert run is not None

    detail = await hex_detail.load(seeded.conn, seeded.unscorable, run)

    assert detail is not None
    assert detail.score is None
    assert detail.no_score_reason == "low_population"
    assert detail.components == [], "no component score exists for an unscored hexagon"
    assert detail.confidence.band == "insufficient"
    assert detail.confidence.value == 0.0
    assert len(detail.indicators) == 15


async def test_a_hexagon_this_run_holds_nothing_about_is_not_found(seeded: Seed) -> None:
    run = await runs.current(seeded.conn)
    assert run is not None

    assert await hex_detail.load(seeded.conn, seeded.ungraded, run) is None


async def test_a_cell_outside_the_grid_is_not_found(seeded: Seed) -> None:
    """A valid resolution 8 cell in Kansas. Not an error, just not scored."""
    run = await runs.current(seeded.conn)
    assert run is not None

    kansas = str(h3.latlng_to_cell(38.5, -98.0, 8))
    assert await hex_detail.load(seeded.conn, kansas, run) is None


# ---- the query load ------------------------------------------------------


async def test_every_table_the_drill_down_filters_is_index_addressable(seeded: Seed) -> None:
    """The failure this guards against only appears once the real grid is loaded.

    Louisiana at resolution 8 is on the order of 90,000 hexagons with fifteen
    indicator rows each. The seed is three hexagons, and against three rows a
    sequential scan is genuinely the cheaper plan, so asserting on the plan the
    planner picks here would assert the opposite of what production needs.

    Disabling sequential scans is what makes the question answerable at this
    size. The setting is a preference and not a prohibition: if a table had no
    usable index for these predicates, Postgres would scan it anyway and the
    assertion would fail. So what this checks is that an index path exists on
    every table the query filters, which is the property that has to hold
    before the grid is loaded rather than after.
    """
    await seeded.conn.execute("SET LOCAL enable_seqscan = off")
    try:
        plans = await seeded.conn.fetch(
            "EXPLAIN (FORMAT TEXT) " + hex_detail.CORE, seeded.scored, seeded.run_id
        )
        text = "\n".join(r[0] for r in plans)
        assert "Seq Scan on hex " not in text, text
        assert "Seq Scan on hex_score" not in text, text
        assert "Seq Scan on hex_demographics" not in text, text

        rows = await seeded.conn.fetch(
            "EXPLAIN (FORMAT TEXT) " + hex_detail.INDICATOR_VALUES, seeded.run_id, seeded.scored
        )
        text = "\n".join(r[0] for r in rows)
        assert "Seq Scan on hex_indicator" not in text, text
    finally:
        await seeded.conn.execute("SET LOCAL enable_seqscan = on")


async def test_a_drill_down_answers_well_inside_a_click(seeded: Seed) -> None:
    """The panel opens on a map click, so this is in front of a person waiting.

    The bound is deliberately loose. It is here to catch an accidental N+1 or a
    dropped index, which cost an order of magnitude, not to police milliseconds
    on whatever hardware CI happens to run.
    """
    run = await runs.current(seeded.conn)
    assert run is not None

    # One warm call first, so the measurement is not the first parse and plan.
    await hex_detail.load(seeded.conn, seeded.scored, run)

    timings: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        await hex_detail.load(seeded.conn, seeded.scored, run)
        timings.append((time.perf_counter() - started) * 1000)

    timings.sort()
    median = timings[len(timings) // 2]
    worst = timings[-1]
    # Logged as well as asserted: the bound is loose enough that the numbers
    # are the interesting part, and `pytest --log-cli-level=INFO` prints them.
    log.info(
        "drill-down timings",
        extra={"median_ms": round(median, 2), "slowest_ms": round(worst, 2), "samples": 20},
    )
    assert median < 100.0, f"median {median:.1f} ms over 20 drill-downs"
    assert worst < 400.0, f"slowest {worst:.1f} ms over 20 drill-downs"


async def test_the_run_context_is_not_refetched_for_every_drill_down(seeded: Seed) -> None:
    """It is the same for every hexagon in a run, and two queries is two too many."""
    runs.reset_cache()

    first = await runs.current(seeded.conn)
    second = await runs.current(seeded.conn)

    assert first is not None
    assert first is second, "the run context was rebuilt rather than reused"
