"""The geometry half of section 7 step 2, and storing what comes out of it.

Intersecting a quarter of a million census blocks with a hex grid is a job for
PostGIS, not for Python, so this module is thin: it holds the SQL, hands the
rows to `pipeline.dasymetric.weights` as `BlockOverlap` values, and writes the
folded result back to `tract_hex_weight`. No arithmetic happens here that the
unit tests cannot reach, which is the point of the split.

**Areas are computed in an equal-area projection.** The stored geometries are
EPSG:4326, where a square degree near the Gulf coast is a different amount of
ground from a square degree near the Arkansas line. Area shares taken in
degrees would therefore be wrong in a way that varies systematically with
latitude, and the whole apportionment is a ratio of areas. EPSG:5070, NAD83
Conus Albers, is the standard equal-area projection for the continental United
States and is what the areas below are measured in.

**The intersection is taken in 4326 and only then projected.** That is
deliberate: the join predicate can use the GiST indexes declared in migration
0003, which are on the 4326 geometries, and projecting a hundred thousand hex
boundaries to test intersection would throw those indexes away. The difference
between clipping before and after projection is far below the precision of the
block boundaries themselves.

**On the pilot-state boundary.** The query joins every hexagon in the grid,
including any whose centroid falls outside Louisiana. Section 5's rule that
such hexes are excluded is a rule about percentile denominators, and CS-201
applies it there. Applying it here instead would strand the population of every
block straddling the state line, which would show up as a coverage shortfall
that is a boundary rule rather than a defect. If the grid built by CS-007
stores only in-state hexes, blocks on the line will appear in
`CrosswalkReport.uncovered_blocks` for exactly that reason, and that is the
signal to read before treating them as a grid defect.
"""

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, runtime_checkable

from pipeline.dasymetric.quantities import Kind, TractEstimate
from pipeline.dasymetric.weights import (
    BlockOverlap,
    Crosswalk,
    TractHexWeight,
    crosswalk_from_weights,
)

#: NAD83 / Conus Albers. Equal-area, continental US. See the module docstring.
EQUAL_AREA_SRID = 5070


@runtime_checkable
class Connection(Protocol):
    """The slice of asyncpg this module needs.

    A protocol rather than an import, for the same reason `pipeline.sinks` uses
    one: the transformation should be testable and importable without a
    database driver, and the ETL package does not otherwise depend on asyncpg.
    """

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]: ...

    async def execute(self, query: str, *args: Any) -> Any: ...

    async def executemany(self, query: str, args: Iterable[Sequence[Any]]) -> Any: ...

    # `store_crosswalk` deletes a county's weights before inserting its new
    # ones, and a reader between those two statements would see the county as
    # empty rather than as mid-rebuild. Wrapping the pair is not optional, so
    # the protocol asks for it rather than trusting the caller to remember.
    def transaction(self) -> AbstractAsyncContextManager[Any]: ...


COUNTIES_IN_STATE = """
SELECT DISTINCT state_fips || county_fips AS county
FROM census_tract
WHERE state_fips = $1
ORDER BY county
"""

#: One row per block-hex overlap for one county. Run per county rather than
#: statewide: the intersection is the expensive part of the whole pipeline, and
#: a county at a time keeps the working set in memory and makes a failure
#: resumable instead of restarting a multi-hour statewide join.
BLOCK_HEX_OVERLAPS = f"""
SELECT block_geoid, tract_geoid, h3, block_population, block_area_m2, overlap_area_m2
FROM (
    SELECT
        b.geoid       AS block_geoid,
        b.tract_geoid AS tract_geoid,
        h.h3::text    AS h3,
        b.population  AS block_population,
        ST_Area(ST_Transform(b.geom, {EQUAL_AREA_SRID}))  AS block_area_m2,
        ST_Area(
            ST_Transform(ST_Intersection(b.geom, h.boundary), {EQUAL_AREA_SRID})
        ) AS overlap_area_m2
    FROM census_block b
    JOIN hex h
      ON b.geom && h.boundary
     AND ST_Intersects(b.geom, h.boundary)
    WHERE left(b.tract_geoid, 5) = $1
) overlaps
WHERE overlap_area_m2 > 0
ORDER BY block_geoid, h3
"""

#: Idempotent by the (tract_geoid, h3) primary key of migration 0003, so a
#: re-run replaces the crosswalk in place rather than doubling it.
UPSERT_TRACT_HEX_WEIGHT = """
INSERT INTO tract_hex_weight (
    tract_geoid, h3, population, pop_weight, area_weight, block_count, mean_block_area_m2
)
VALUES ($1, $2::h3_cell, $3, $4, $5, $6, $7)
ON CONFLICT (tract_geoid, h3) DO UPDATE SET
    population         = EXCLUDED.population,
    pop_weight         = EXCLUDED.pop_weight,
    area_weight        = EXCLUDED.area_weight,
    block_count        = EXCLUDED.block_count,
    mean_block_area_m2 = EXCLUDED.mean_block_area_m2
"""

#: Rows for tracts that no longer reach a given hex must go, or a re-run after
#: a grid change leaves weights that sum to more than 1 for a tract. Scoped to
#: the counties just rebuilt so a partial rebuild does not delete the rest.
DELETE_COUNTY_WEIGHTS = """
DELETE FROM tract_hex_weight WHERE left(tract_geoid, 5) = $1
"""

LOAD_TRACT_HEX_WEIGHT = """
SELECT tract_geoid, h3::text AS h3, population, pop_weight, area_weight,
       block_count, mean_block_area_m2
FROM tract_hex_weight
ORDER BY tract_geoid, h3
"""

#: One published ACS variable across every tract, with the kind it was stored
#: under. `is_extensive` is read rather than inferred here for the reason
#: migration 0008 gives: section 7 calls confusing extensive and intensive
#: quantities the most common error in this step, so the decision is made once
#: at ingest and carried, never re-guessed from a variable name.
LOAD_TRACT_ESTIMATES = """
SELECT tract_geoid, variable, estimate, margin_of_error, is_extensive
FROM tract_demographics
WHERE variable = $1 AND acs_vintage = $2
ORDER BY tract_geoid
"""


async def counties(conn: Connection, *, state_fips: str) -> tuple[str, ...]:
    """Five-digit county FIPS codes with tracts in the pilot state."""
    rows = await conn.fetch(COUNTIES_IN_STATE, state_fips)
    return tuple(str(row["county"]) for row in rows)


async def load_block_overlaps(conn: Connection, *, county_fips: str) -> list[BlockOverlap]:
    """Every block-hex intersection in one county, as plain numbers."""
    rows = await conn.fetch(BLOCK_HEX_OVERLAPS, county_fips)
    return [
        BlockOverlap(
            block_geoid=str(row["block_geoid"]),
            tract_geoid=str(row["tract_geoid"]),
            h3=str(row["h3"]),
            block_population=int(row["block_population"]),
            block_area_m2=float(row["block_area_m2"]),
            overlap_area_m2=float(row["overlap_area_m2"]),
        )
        for row in rows
    ]


async def load_tract_estimates(
    conn: Connection, *, variable: str, acs_vintage: str
) -> list[TractEstimate]:
    """One ACS variable across every tract, ready to interpolate.

    A NULL estimate stays None rather than becoming zero. Section 11 keeps
    absences and zeros apart, and a tract the ACS had nothing for is the first
    place that distinction gets quietly lost.
    """
    rows = await conn.fetch(LOAD_TRACT_ESTIMATES, variable, acs_vintage)
    return [
        TractEstimate(
            tract_geoid=str(row["tract_geoid"]),
            variable=str(row["variable"]),
            estimate=None if row["estimate"] is None else float(row["estimate"]),
            margin_of_error=(
                None if row["margin_of_error"] is None else float(row["margin_of_error"])
            ),
            kind=Kind.EXTENSIVE if row["is_extensive"] else Kind.INTENSIVE,
        )
        for row in rows
    ]


async def store_crosswalk(conn: Connection, crosswalk: Crosswalk, *, county_fips: str) -> int:
    """Replace one county's `tract_hex_weight` rows. Returns rows written.

    The delete and the insert belong to one transaction, opened by the caller.
    Between them the county has no crosswalk at all, and a reader that saw that
    state would silently score the county as empty.
    """
    await conn.execute(DELETE_COUNTY_WEIGHTS, county_fips)
    payload = [
        (
            weight.tract_geoid,
            weight.h3,
            weight.population,
            weight.pop_weight,
            weight.area_weight,
            weight.block_count,
            weight.mean_block_area_m2,
        )
        for weight in crosswalk.weights
    ]
    if payload:
        await conn.executemany(UPSERT_TRACT_HEX_WEIGHT, payload)
    return len(payload)


async def load_crosswalk(conn: Connection) -> Crosswalk:
    """Read the stored crosswalk back for a scoring run.

    The geometry runs once when the grid or the block layer changes; every run
    after that reads these rows. Nothing is recomputed on the way back in, so
    a score built from a stored crosswalk is the score that would have been
    built from a fresh one.
    """
    rows = await conn.fetch(LOAD_TRACT_HEX_WEIGHT)
    return crosswalk_from_weights(
        TractHexWeight(
            tract_geoid=str(row["tract_geoid"]),
            h3=str(row["h3"]),
            population=float(row["population"]),
            pop_weight=float(row["pop_weight"]),
            area_weight=float(row["area_weight"]),
            block_count=int(row["block_count"]),
            mean_block_area_m2=float(row["mean_block_area_m2"] or 0.0),
        )
        for row in rows
    )
