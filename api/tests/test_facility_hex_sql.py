"""The neighbour query, against a real PostGIS database.

Everything else under api/tests runs without a database on purpose. This file
cannot: the thing being checked is what PostGIS does with a geography index and
a spheroid distance, and a mock of that would only prove the mock agrees with
itself. It skips unless CLEARSKIES_TEST_DATABASE_URL names a database with the
migration set applied, which is what CI's `database` job has up already.

The seed is two hexagons, five named facilities and a few hundred background
ones, in a transaction that is always rolled back, so the same database can run
this repeatedly and still be the one the next job migrates.

What it assumes about the database it is pointed at is that no facility already
loaded sits within 10 km of either of the two hexagons, since the assertions are
about exactly which facilities come back. That is true of every ClearSkies
database today, because no pull has loaded one.
"""

import os
from collections.abc import AsyncIterator
from math import cos, radians

import asyncpg
import h3
import pytest

from app.facilities import contributing

DATABASE_URL = os.environ.get("CLEARSKIES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set CLEARSKIES_TEST_DATABASE_URL to a migrated database to run the spatial tests",
)

# Methodology section 8.1.
INTERACTION_RADIUS_M = 10_000.0
MIN_DISTANCE_M = 250.0

# Baton Rouge, and a point on the Louisiana side of the Sabine River near Vinton.
# The second is the case section 5 names: the nearest heavy industry to it is
# across the state line, in the Beaumont-Port Arthur corridor.
BATON_ROUGE = (30.4515, -91.1871)
SABINE_LINE = (30.1900, -93.7100)

METRES_PER_DEGREE_LAT = 111_194.9


def west_of(latitude: float, longitude: float, metres: float) -> tuple[float, float]:
    """A point `metres` due west, near enough for a test fixture."""
    degrees = metres / (METRES_PER_DEGREE_LAT * cos(radians(latitude)))
    return (latitude, longitude - degrees)


def boundary_wkt(cell: str) -> str:
    ring = [*h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{lon} {lat}" for lat, lon in ring) + "))"


async def seed_hex(
    conn: asyncpg.Connection, anchor: tuple[float, float]
) -> tuple[str, float, float]:
    """One hexagon at its own true centroid. Returns the cell and that centroid."""
    cell = str(h3.latlng_to_cell(anchor[0], anchor[1], 8))
    latitude, longitude = h3.cell_to_latlng(cell)
    await conn.execute(
        """
        INSERT INTO hex (h3, resolution, centroid, boundary, state_fips, in_pilot_state)
        VALUES ($1, 8, ST_SetSRID(ST_MakePoint($3, $2), 4326),
                ST_GeomFromText($4, 4326), '22', true)
        -- Both anchors are real Louisiana locations, so on a database that has
        -- had the grid generated these cells already exist. The transaction is
        -- rolled back either way.
        ON CONFLICT (h3) DO UPDATE
            SET centroid = EXCLUDED.centroid, boundary = EXCLUDED.boundary
        """,
        cell,
        latitude,
        longitude,
        boundary_wkt(cell),
    )
    return cell, latitude, longitude


async def seed_facility(
    conn: asyncpg.Connection,
    snapshot_id: int,
    facility_id: str,
    latitude: float,
    longitude: float,
    *,
    state: str = "LA",
    coordinate_status: str = "ok",
    geocode_quality: str = "plausible",
    is_major_source: bool = True,
) -> None:
    await conn.execute(
        """
        INSERT INTO facility (
            facility_id, registry_id, name, state, geom, h3,
            coordinate_status, geocode_quality, reported_latitude, reported_longitude,
            is_major_source, echo_url, snapshot_id
        )
        VALUES ($1, $1, $2, $3, ST_SetSRID(ST_MakePoint($5, $4), 4326), $6,
                $7, $8, $4, $5, $9, $10, $11)
        """,
        facility_id,
        f"TEST {facility_id}",
        state,
        latitude,
        longitude,
        str(h3.latlng_to_cell(latitude, longitude, 8)),
        coordinate_status,
        geocode_quality,
        is_major_source,
        f"https://echo.epa.gov/detailed-facility-report?fid={facility_id}",
        snapshot_id,
    )


@pytest.fixture
async def seeded() -> AsyncIterator[tuple[asyncpg.Connection, dict[str, str]]]:
    """A rolled-back transaction holding two hexagons and five named facilities.

    Each named facility is one case: inside the hexagon, within the radius,
    outside it, quarantined, and out of state. A few hundred background
    facilities follow, for the planner's benefit rather than the assertions'.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    transaction = conn.transaction()
    await transaction.start()
    try:
        snapshot_id: int = await conn.fetchval(
            """
            INSERT INTO source_snapshot (source, url, retrieved_at, checksum, vintage, vintage_end)
            VALUES ('echo', 'test://seed', now(), 'seed', 'test', current_date)
            RETURNING snapshot_id
            """
        )

        inland, inland_lat, inland_lon = await seed_hex(conn, BATON_ROUGE)
        line, line_lat, line_lon = await seed_hex(conn, SABINE_LINE)

        # Inside the hexagon it will be scored against: the 250 m floor case.
        await seed_facility(conn, snapshot_id, "INSIDE", inland_lat, inland_lon)
        # Comfortably inside the interaction radius.
        await seed_facility(conn, snapshot_id, "NEAR", *west_of(inland_lat, inland_lon, 5_000))
        # Outside it. Section 8.1 says it contributes nothing.
        await seed_facility(conn, snapshot_id, "FAR", *west_of(inland_lat, inland_lon, 15_000))
        # Close enough to matter, and quarantined by section 6, so it must not.
        await seed_facility(
            conn,
            snapshot_id,
            "SUSPECT",
            *west_of(inland_lat, inland_lon, 1_000),
            coordinate_status="zip_mismatch",
            geocode_quality="suspect",
        )
        # Across the Sabine, in Texas, 6 km from a Louisiana hexagon.
        await seed_facility(
            conn,
            snapshot_id,
            "BEAUMONT",
            *west_of(line_lat, line_lon, 6_000),
            state="TX",
        )

        await conn.execute(
            """
            INSERT INTO facility_compliance_quarter (facility_id, quarter, program, status,
                                                     snapshot_id)
            VALUES ('NEAR', date '2025-01-01', 'CAA', 'high_priority_violation', $1),
                   ('NEAR', date '2025-04-01', 'CAA', 'violation', $1),
                   ('NEAR', date '2025-07-01', 'CAA', 'in_compliance', $1)
            """,
            snapshot_id,
        )
        await conn.execute(
            """
            INSERT INTO enforcement_action (action_id, facility_id, program, settled_on,
                                            penalty_usd, is_formal, snapshot_id)
            VALUES ('a1', 'NEAR', 'CAA', current_date - 100, 25000, true, $1)
            """,
            snapshot_id,
        )

        # Background, so the planner faces the question it faces in production.
        # Scattered over a degree box well away from both hexagons, so no row
        # here joins to either and the assertions above stay about the five named
        # facilities. Louisiana has on the order of 13,000 air facilities; a few
        # hundred is already past the point where a sequential scan stops being
        # the cheapest way to answer a 10 km radius.
        await conn.execute(
            """
            INSERT INTO facility (facility_id, registry_id, name, state, geom,
                                  coordinate_status, geocode_quality, snapshot_id)
            SELECT 'BG' || g, 'BG' || g, 'background', 'LA',
                   ST_SetSRID(ST_MakePoint(-92.2 + random(), 31.4 + random()), 4326),
                   'ok', 'plausible', $1
              FROM generate_series(1, 500) AS g
            """,
            snapshot_id,
        )
        await conn.execute("ANALYZE facility")

        yield conn, {"inland": inland, "line": line}
    finally:
        await transaction.rollback()
        await conn.close()


# ---- the neighbour relation ---------------------------------------------


async def test_only_facilities_inside_the_interaction_radius_are_linked(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    conn, cells = seeded
    rows = await conn.fetch(
        "SELECT facility_id, distance_m FROM hex_facility_links($1, $2) ORDER BY distance_m",
        cells["inland"],
        INTERACTION_RADIUS_M,
    )

    assert [r["facility_id"] for r in rows] == ["INSIDE", "NEAR"]


async def test_a_quarantined_facility_is_not_linked_however_close_it_is(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """Section 6: flagged facilities stay in the table and out of the indicators.

    SUSPECT sits a kilometre from the centroid, nearer than NEAR, and must still
    be absent. Its row is still there to be counted.
    """
    conn, cells = seeded
    linked = await conn.fetch(
        "SELECT facility_id FROM hex_facility_links($1, $2)", cells["inland"], INTERACTION_RADIUS_M
    )
    still_stored = await conn.fetchval(
        "SELECT coordinate_status FROM facility WHERE facility_id = 'SUSPECT'"
    )

    assert "SUSPECT" not in {r["facility_id"] for r in linked}
    assert still_stored == "zip_mismatch"


async def test_an_out_of_state_facility_reaches_a_hex_on_the_state_line(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """Methodology section 5, the case it names.

    Nothing in the neighbour query filters on state. A hex on the Texas line near
    a Beaumont-area facility is not artificially clean, and this is the query
    property that makes that true rather than a promise about it.
    """
    conn, cells = seeded
    rows = await conn.fetch(
        """
        SELECT link.facility_id, link.distance_m, f.state
          FROM hex_facility_links($1, $2) AS link
          JOIN facility f ON f.facility_id = link.facility_id
         ORDER BY link.distance_m
        """,
        cells["line"],
        INTERACTION_RADIUS_M,
    )

    assert [r["facility_id"] for r in rows] == ["BEAUMONT"]
    assert rows[0]["state"] == "TX"
    assert rows[0]["distance_m"] == pytest.approx(6_000, abs=50)


async def test_the_containing_hex_is_marked_on_the_link(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """What the panel's contributing-facilities list needs to say "in this hexagon"."""
    conn, cells = seeded
    rows = await conn.fetch(
        "SELECT facility_id, is_containing FROM hex_facility_links($1, $2)",
        cells["inland"],
        INTERACTION_RADIUS_M,
    )
    containing = {r["facility_id"]: r["is_containing"] for r in rows}

    assert containing == {"INSIDE": True, "NEAR": False}


# ---- the decay kernel ----------------------------------------------------


async def test_a_facility_in_the_hexagon_is_floored_rather_than_infinite(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """The 250 m floor of section 8.1, which exists to stop a singularity."""
    conn, cells = seeded
    weight = await conn.fetchval(
        """
        SELECT decay_weight FROM hex_facility_links($1, $2) WHERE facility_id = 'INSIDE'
        """,
        cells["inland"],
        INTERACTION_RADIUS_M,
    )

    assert weight == pytest.approx(1.0 / MIN_DISTANCE_M**2)


async def test_the_weight_falls_with_the_square_of_the_distance(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    conn, _ = seeded
    near, far = await conn.fetchrow(
        "SELECT facility_decay_weight(1000.0), facility_decay_weight(2000.0)"
    )

    assert near == pytest.approx(far * 4)


async def test_the_floor_applies_below_it_and_not_above(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    conn, _ = seeded
    at_zero, at_floor, above = await conn.fetchrow(
        """
        SELECT facility_decay_weight(0.0),
               facility_decay_weight(250.0),
               facility_decay_weight(500.0)
        """
    )

    assert at_zero == at_floor
    assert above < at_floor


# ---- the whole grid ------------------------------------------------------


async def test_the_bulk_relation_reaches_every_hexagon_not_only_the_one_asked_for(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """What the scoring step reads: E3 and F1 to F4 are each one aggregate over this."""
    conn, cells = seeded
    rows = await conn.fetch(
        """
        SELECT h3, count(*) AS links
          FROM hex_facility_links_all($1)
         WHERE h3 = ANY($2::text[])
         GROUP BY h3
        """,
        INTERACTION_RADIUS_M,
        [cells["inland"], cells["line"]],
    )

    assert {r["h3"]: r["links"] for r in rows} == {cells["inland"]: 2, cells["line"]: 1}


async def test_the_bulk_relation_and_the_single_hex_one_agree(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """They are one definition of "near", so a disagreement would be a bug in that claim."""
    conn, cells = seeded
    bulk = await conn.fetch(
        """
        SELECT facility_id, distance_m FROM hex_facility_links_all($1)
         WHERE h3 = $2 ORDER BY distance_m
        """,
        INTERACTION_RADIUS_M,
        cells["inland"],
    )
    single = await conn.fetch(
        "SELECT facility_id, distance_m FROM hex_facility_links($1, $2) ORDER BY distance_m",
        cells["inland"],
        INTERACTION_RADIUS_M,
    )

    assert [tuple(r) for r in bulk] == [tuple(r) for r in single]


# ---- what the panel renders ----------------------------------------------


async def test_the_panel_query_returns_facilities_nearest_first(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    conn, cells = seeded
    rows = await conn.fetch(
        "SELECT * FROM facilities_near_hex($1, $2)", cells["inland"], INTERACTION_RADIUS_M
    )

    assert [r["facility_id"] for r in rows] == ["INSIDE", "NEAR"]
    assert rows[0]["distance_m"] < rows[1]["distance_m"]
    assert rows[0]["echo_url"].endswith("fid=INSIDE")


async def test_the_panel_query_carries_the_compliance_history_behind_f2_and_f3(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """Two bad quarters of three, and one formal action inside the five-year window."""
    conn, cells = seeded
    rows = {
        r["facility_id"]: r
        for r in await conn.fetch(
            "SELECT * FROM facilities_near_hex($1, $2)", cells["inland"], INTERACTION_RADIUS_M
        )
    }

    assert rows["NEAR"]["quarters_in_noncompliance"] == 2
    assert rows["NEAR"]["formal_actions"] == 1
    assert rows["NEAR"]["penalty_usd"] == 25000
    # A facility with no history reports zero, not null: nothing was found, and
    # the panel renders a count.
    assert rows["INSIDE"]["quarters_in_noncompliance"] == 0
    assert rows["INSIDE"]["formal_actions"] == 0


async def test_the_enforcement_window_is_a_parameter_not_todays_date(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """A run scoring last night's data asks about that night's five years."""
    conn, cells = seeded
    rows = {
        r["facility_id"]: r
        for r in await conn.fetch(
            "SELECT * FROM facilities_near_hex($1, $2, current_date - 10)",
            cells["inland"],
            INTERACTION_RADIUS_M,
        )
    }

    # The action settled 100 days ago, so a ten-day window excludes it.
    assert rows["NEAR"]["formal_actions"] == 0


# ---- the index the read path depends on ----------------------------------


async def test_the_neighbour_query_reaches_facilities_through_the_geography_index(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """An expression index whose cast does not match the query is silently unused.

    That is the failure this catches, and it is silent in the worst way:
    everything still returns the right rows, over a sequential scan of every
    facility in the state, once per hexagon. Nothing fails, the nightly scoring
    job just takes hours.

    The seeded background above is what makes this a real question. On five rows
    the planner would rightly scan the table, so what is asserted would be
    whichever plan the seed happened to produce. `_st_expand` is the part that
    matters: it is the index condition, not merely the index being read.
    """
    conn, cells = seeded
    plan = "\n".join(
        row["QUERY PLAN"]
        for row in await conn.fetch(
            "EXPLAIN SELECT * FROM hex_facility_links($1, $2)",
            cells["inland"],
            INTERACTION_RADIUS_M,
        )
    )

    assert "facility_geography_idx" in plan
    assert "_st_expand" in plan


# ---- the module GET /hex/{h3} calls --------------------------------------


async def test_the_api_read_path_returns_the_panel_payload(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """app.facilities end to end, against the function it is a thin wrapper over."""
    conn, cells = seeded
    found = await contributing(conn, cells["inland"], radius_m=INTERACTION_RADIUS_M)

    assert [f.registry_id for f in found] == ["INSIDE", "NEAR"]
    assert found[0].in_hex and not found[1].in_hex
    assert found[0].distance_km < found[1].distance_km
    assert found[1].quarters_in_noncompliance == 2
    assert found[1].formal_actions_5yr == 1
    assert found[0].program == "CAA major source"


async def test_the_api_read_path_includes_the_out_of_state_contributor(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    conn, cells = seeded
    found = await contributing(conn, cells["line"], radius_m=INTERACTION_RADIUS_M)

    assert [f.registry_id for f in found] == ["BEAUMONT"]
    assert found[0].distance_km == pytest.approx(6.0, abs=0.05)


async def test_the_api_read_path_caps_what_it_shows_without_capping_the_score(
    seeded: tuple[asyncpg.Connection, dict[str, str]],
) -> None:
    """A hexagon in the industrial corridor has more facilities than a panel can list."""
    conn, cells = seeded
    found = await contributing(conn, cells["inland"], radius_m=INTERACTION_RADIUS_M, limit=1)

    assert [f.registry_id for f in found] == ["INSIDE"]
