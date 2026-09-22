"""The H3 hex grid for the pilot state (CS-007).

Everything else in the project joins against this table, so it is built once and
rebuilt only deliberately. Section 5 fixes the resolution at 8, roughly 0.737
km² per cell, which puts something near 190,000 cells over Louisiana and its
coastal water.

**Cells are computed in Python, not by h3-pg.** The extension is installed and is
useful for ad-hoc queries, but the pipeline must not depend on it: the grid has
to be reproducible from a machine with h3-py and a plain PostGIS, and a job that
silently needs a database extension is a job that breaks on the first deployment
that lacks one. So `h3shape_to_cells` runs here and the database receives
finished geometry.

**Where the state boundary comes from.** `census_tract`, dissolved. TIGER tracts
tile the state exactly, including the water tracts that reach out to the
territorial line, so their union is the boundary section 5 asks for — land plus
coastal water — without introducing a second boundary source that could disagree
with the one every tract-sourced indicator is already keyed to. It costs a
dependency on the ACS load having run.

**Two kinds of cell, and why the grid holds both.** `h3shape_to_cells` selects a
cell when its *centre* falls inside the shape, which is exactly section 5's rule
for percentile denominators. Storing only those would leave every cell that
straddles the state line out of the grid entirely, and
`pipeline.dasymetric.postgis` warns what that costs: the population of a block on
the line lands in no hexagon and surfaces as `uncovered_blocks`. So the grid also
holds the ring of cells that overlap the state without being centred in it, and
`in_pilot_state` is what tells them apart. CS-201 filters on that flag when it
computes percentiles; the interpolation does not, and neither does a proximity
query. A column that were always true would make both the flag and its partial
index pointless.

`parish_name` and `land_fraction` are left NULL. Neither has a source in the
database today — the tract layer carries tract names rather than parish names,
and a per-cell land share needs a water layer that nothing has loaded. Both are
nullable, and filling them is a later, separate job.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import h3

from pipeline.parishes import as_arrays

__all__ = [
    "Connection",
    "GridReport",
    "RESOLUTION",
    "UNSCORED_REASON",
    "assign_parishes",
    "build_grid",
    "cells_for",
    "export_for_tiles",
]

#: Methodology section 5. The table's CHECK constraint says the same thing.
RESOLUTION = 8

#: Louisiana's published total area, land plus water, in km². The grid covers
#: this, so a total wildly away from it means the boundary was wrong before the
#: cells were. Source: Census state area measurements.
LOUISIANA_AREA_KM2 = 135_659.0

#: How far the loaded total may sit from the published figure before the build
#: refuses to call itself sane. Generous, because the grid tiles the boundary
#: with hexagons rather than following it: the edge is a staircase either way.
AREA_TOLERANCE = 0.05


@runtime_checkable
class Connection(Protocol):
    """The slice of asyncpg this module needs. See `pipeline.sinks_postgres`."""

    async def fetchval(self, query: str, *args: Any) -> Any: ...

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]: ...

    async def fetchrow(self, query: str, *args: Any) -> Mapping[str, Any] | None: ...

    async def executemany(self, query: str, args: Iterable[Sequence[Any]]) -> Any: ...

    async def execute(self, query: str, *args: Any) -> Any: ...

    def transaction(self) -> AbstractAsyncContextManager[Any]: ...


@dataclass(frozen=True)
class GridReport:
    """What one build produced, and whether it looks right."""

    in_pilot: int
    fringe: int
    area_km2: float
    parishes: int

    @property
    def total(self) -> int:
        return self.in_pilot + self.fringe

    @property
    def mean_cell_km2(self) -> float:
        return self.area_km2 / self.in_pilot if self.in_pilot else 0.0

    @property
    def area_error(self) -> float:
        return abs(self.area_km2 - LOUISIANA_AREA_KM2) / LOUISIANA_AREA_KM2

    @property
    def plausible(self) -> bool:
        return self.area_error <= AREA_TOLERANCE

    def summary(self) -> str:
        verdict = "ok" if self.plausible else "IMPLAUSIBLE"
        return (
            f"{self.total} cells: {self.in_pilot} in pilot state, {self.fringe} on the line. "
            f"{self.area_km2:,.0f} km² against {LOUISIANA_AREA_KM2:,.0f} published "
            f"({self.area_error:.1%} off, {verdict}). "
            f"mean cell {self.mean_cell_km2:.3f} km², {self.parishes} parishes assigned."
        )


BOUNDARY = """
SELECT ST_AsGeoJSON(ST_Union(geom)) AS boundary
FROM census_tract
WHERE state_fips = $1
"""


def cells_for(boundary: Mapping[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """The grid for one boundary, split into centred cells and the fringe.

    Returns `(in_pilot, fringe)`. The first is what `h3shape_to_cells` selects,
    which is centre-containment and therefore section 5's rule exactly. The
    second is the one-ring dilation of that set minus the set itself: every cell
    adjacent to the state, before any test of whether it actually touches it.
    Pruning the ones that do not is left to PostGIS, which has the boundary
    indexed and does not need it shipped back over the wire.
    """
    in_pilot = frozenset(h3.geo_to_cells(boundary, RESOLUTION))
    if not in_pilot:
        return frozenset(), frozenset()

    dilated: set[str] = set()
    for cell in in_pilot:
        dilated.update(h3.grid_disk(cell, 1))
    return in_pilot, frozenset(dilated - in_pilot)


def _row(cell: str, *, state_fips: str, in_pilot: bool) -> tuple[Any, ...]:
    """One cell as the tuple the insert below binds.

    h3-py yields (lat, lng) and EWKT wants (lng, lat); the boundary ring is
    closed explicitly because `cell_to_boundary` returns the seven-vertex hexagon
    as six points and PostGIS will not accept an open polygon.
    """
    lat, lng = h3.cell_to_latlng(cell)
    ring = h3.cell_to_boundary(cell)
    points = ", ".join(f"{vertex_lng} {vertex_lat}" for vertex_lat, vertex_lng in ring)
    first_lat, first_lng = ring[0]
    boundary = f"SRID=4326;POLYGON(({points}, {first_lng} {first_lat}))"
    return (cell, RESOLUTION, f"SRID=4326;POINT({lng} {lat})", boundary, state_fips, in_pilot)


def rows_for(
    in_pilot: Iterable[str], fringe: Iterable[str], *, state_fips: str
) -> Iterator[tuple[Any, ...]]:
    for cell in in_pilot:
        yield _row(cell, state_fips=state_fips, in_pilot=True)
    for cell in fringe:
        yield _row(cell, state_fips=state_fips, in_pilot=False)


# `h3` is an `h3_cell`, an extension type, so the text has to be cast. The upsert
# is what makes a rebuild idempotent: CS-007 asks that re-running not duplicate
# rows, and a grid is a fixed set that should converge rather than accumulate.
INSERT = """
INSERT INTO hex (h3, resolution, centroid, boundary, state_fips, in_pilot_state)
VALUES ($1::h3_cell, $2, ST_GeomFromEWKT($3), ST_GeomFromEWKT($4), $5, $6)
ON CONFLICT (h3) DO UPDATE SET
    resolution     = EXCLUDED.resolution,
    centroid       = EXCLUDED.centroid,
    boundary       = EXCLUDED.boundary,
    state_fips     = EXCLUDED.state_fips,
    in_pilot_state = EXCLUDED.in_pilot_state
"""

# The fringe was dilated blindly, so most of it is a ring of cells that never
# touch the state. A cell is kept only if its hexagon actually overlaps a tract,
# which the GiST index on census_tract.geom answers cheaply.
PRUNE = """
DELETE FROM hex h
WHERE NOT h.in_pilot_state
  AND NOT EXISTS (
      SELECT 1 FROM census_tract t
      WHERE t.state_fips = $1 AND ST_Intersects(t.geom, h.boundary)
  )
"""

# The parish a cell sits in, by its centre. Fringe cells centred outside the
# state get no parish, which is correct: they belong to a neighbouring one.
#
# The name comes from `pipeline.parishes`, passed as two arrays rather than
# written into the statement, because the mapping has one home and a copy of it
# here would be a copy that drifts. A LEFT JOIN, so a code with no name still
# gets its `county_fips`: the geometry is the fact and the label is a
# convenience, and losing the first to a missing second would be the wrong way
# round (CP-26).
ASSIGN_PARISH = """
UPDATE hex h
SET county_fips = t.county_fips,
    parish_name = p.name
FROM census_tract t
LEFT JOIN unnest($2::text[], $3::text[]) AS p(fips, name) ON p.fips = t.county_fips
WHERE ST_Contains(t.geom, h.centroid)
  AND t.state_fips = $1
  AND (h.county_fips IS DISTINCT FROM t.county_fips
       OR h.parish_name IS DISTINCT FROM p.name)
"""

MEASURE = """
SELECT
    count(*) FILTER (WHERE in_pilot_state)                      AS in_pilot,
    count(*) FILTER (WHERE NOT in_pilot_state)                  AS fringe,
    COALESCE(SUM(ST_Area(boundary::geography)) FILTER (WHERE in_pilot_state), 0) / 1e6 AS area_km2,
    count(DISTINCT county_fips)                                 AS parishes
FROM hex
"""


#: Why a cell drawn from the grid alone carries no score. Written into every
#: feature so the map says "not scored yet" rather than leaving a reader to read
#: a grey hexagon as a low one.
UNSCORED_REASON = "pipeline_not_run"

EXPORT = """
SELECT h3::text AS h3
FROM hex
WHERE in_pilot_state
ORDER BY h3
"""

#: The scored grid, for the archive the map actually reads. Joined from the
#: promoted run only: `hex_score` holds one row per hexagon per run and drawing
#: two of them would put a cell on the map twice, at two different colours.
#: Unscored hexagons are kept and carry their reason, because a hexagon missing
#: from the archive is indistinguishable from one the tile build dropped.
EXPORT_SCORED = """
SELECT h.h3::text        AS h3,
       s.score           AS score,
       s.percentile      AS percentile,
       s.confidence      AS confidence,
       s.confidence_band AS confidence_band,
       s.no_score_reason AS no_score_reason
  FROM hex h
  JOIN hex_score s ON s.h3 = h.h3
 WHERE h.in_pilot_state
   AND s.run_id = (SELECT run_id FROM pipeline_run WHERE is_current)
 ORDER BY h.h3
"""


async def export_for_tiles(connection: Connection) -> dict[str, Any]:
    """The grid in the shape `pipeline tiles` reads.

    Prefers the promoted scoring run. Falls back to a bare, unscored grid when
    no run has been promoted, so the tile path can be exercised against real
    geometry before a score exists — which is worth doing, because a wrong
    boundary is cheap to fix then and expensive later.
    """
    current = await connection.fetchval("SELECT run_id FROM pipeline_run WHERE is_current")
    if current is not None:
        rows = await connection.fetch(EXPORT_SCORED)
        if rows:
            return {
                "generated_by": "pipeline grid-export",
                "scored": True,
                "run_id": int(current),
                "hexes": {
                    row["h3"]: {
                        **{
                            key: float(row[key])
                            for key in ("score", "percentile", "confidence")
                            if row[key] is not None
                        },
                        **{
                            key: row[key]
                            for key in ("confidence_band", "no_score_reason")
                            if row[key] is not None
                        },
                    }
                    for row in rows
                },
            }
    return await _export_unscored(connection)


async def _export_unscored(connection: Connection) -> dict[str, Any]:
    """The grid with nothing scored.

    A scaffold, and labelled as one. `ScoredHex` requires only `h3` and treats
    every other attribute as optional, so the grid can be drawn before a scoring
    run exists — which is worth doing, because it exercises the tile path
    against real geometry while a wrong boundary is still cheap to fix. Every
    feature carries `no_score_reason`, so nothing here can be mistaken for a
    measured zero.

    Only in-pilot cells. The fringe exists so the interpolation does not strand
    blocks on the state line; it is not part of the map.
    """
    rows = await connection.fetch(EXPORT)
    return {
        "generated_by": "pipeline grid-export",
        "scored": False,
        "hexes": {row["h3"]: {"no_score_reason": UNSCORED_REASON} for row in rows},
    }


async def assign_parishes(connection: Connection, *, state_fips: str = "22") -> int:
    """Give every cell the parish its centre falls in, and that parish's name.

    Separate from `build_grid` so it can be re-run over a grid that already
    exists, which is what fills `parish_name` on the 173,424 cells built before
    there was a name to fill it with. Idempotent: the `IS DISTINCT FROM` guard
    means a second run touches nothing, so it costs one scan and changes
    nothing when it has already been done.

    Returns how many rows it changed, for the caller's log.
    """
    codes, names = as_arrays(state_fips)
    status = await connection.execute(ASSIGN_PARISH, state_fips, codes, names)
    # asyncpg returns the command tag, "UPDATE <n>".
    return int(status.rsplit(" ", 1)[-1]) if status else 0


async def build_grid(
    connection: Connection, *, state_fips: str = "22", batch: int = 5_000
) -> GridReport:
    """Build the grid and return what it produced.

    One transaction. A half-written grid is worse than no grid, because every
    table that references `hex` would start accepting rows against a set of
    cells that is about to change.
    """
    raw = await connection.fetchval(BOUNDARY, state_fips)
    if raw is None:
        raise LookupError(
            f"no census_tract rows for state {state_fips!r}; "
            "the grid is cut from the tract layer, so load census_acs first"
        )
    boundary = json.loads(raw)

    in_pilot, fringe = cells_for(boundary)
    if not in_pilot:
        raise ValueError("the boundary produced no cells; it is probably empty or malformed")

    async with connection.transaction():
        pending: list[tuple[Any, ...]] = []
        for row in rows_for(in_pilot, fringe, state_fips=state_fips):
            pending.append(row)
            if len(pending) >= batch:
                await connection.executemany(INSERT, pending)
                pending.clear()
        if pending:
            await connection.executemany(INSERT, pending)

        await connection.execute(PRUNE, state_fips)
        await assign_parishes(connection, state_fips=state_fips)
        measured = await connection.fetchrow(MEASURE)

    assert measured is not None
    return GridReport(
        in_pilot=measured["in_pilot"],
        fringe=measured["fringe"],
        area_km2=float(measured["area_km2"]),
        parishes=measured["parishes"],
    )
