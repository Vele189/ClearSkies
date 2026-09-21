"""The hex grid builder (CS-007).

The cell mathematics is h3-py's and is not retested here. What these cover is
what CS-007 actually asks of the build: resolution 8 and nothing else, geometry
Postgres will accept, the in-pilot rule matching section 5, a fringe that exists
at all, an idempotent write, and an area check that can fail.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import h3
import pytest

from pipeline.grid import (
    LOUISIANA_AREA_KM2,
    RESOLUTION,
    GridReport,
    build_grid,
    cells_for,
    rows_for,
)

# A square degree in the Gulf, well clear of any real coastline, so the counts
# below depend on h3 and not on which TIGER vintage drew Louisiana.
BOX = {
    "type": "Polygon",
    "coordinates": [[[-92.0, 29.0], [-91.8, 29.0], [-91.8, 29.2], [-92.0, 29.2], [-92.0, 29.0]]],
}


class FakeConnection:
    """Enough asyncpg to drive `build_grid` without a database."""

    def __init__(self, boundary: str | None, measured: dict[str, Any] | None = None) -> None:
        self.boundary = boundary
        self.measured = measured or {
            "in_pilot": 2,
            "fringe": 1,
            "area_km2": LOUISIANA_AREA_KM2,
            "parishes": 64,
        }
        self.inserted: list[tuple[Any, ...]] = []
        self.executed: list[str] = []
        self.transactions = 0
        self.rows: list[dict[str, Any]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.boundary

    async def fetch(self, query: str, *args: Any) -> Any:
        return self.rows

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return self.measured

    async def executemany(self, query: str, args: Any) -> Any:
        self.inserted.extend(args)

    async def execute(self, query: str, *args: Any) -> Any:
        self.executed.append(query)

    @asynccontextmanager
    async def _transaction(self) -> Any:
        self.transactions += 1
        yield self

    def transaction(self) -> Any:
        return self._transaction()


def test_in_pilot_cells_are_the_centre_contained_ones() -> None:
    """Section 5's rule, which is also h3shape_to_cells' own semantics."""
    in_pilot, _ = cells_for(BOX)
    assert in_pilot
    for cell in in_pilot:
        lat, lng = h3.cell_to_latlng(cell)
        assert 29.0 <= lat <= 29.2 and -92.0 <= lng <= -91.8


def test_the_fringe_surrounds_the_centred_set_without_overlapping_it() -> None:
    in_pilot, fringe = cells_for(BOX)
    assert fringe, "a bounded shape always has neighbours"
    assert not (in_pilot & fringe), "a cell is in one set or the other, never both"
    for cell in fringe:
        assert set(h3.grid_disk(cell, 1)) & in_pilot, "every fringe cell touches the centred set"


def test_every_cell_is_resolution_eight() -> None:
    """The table's CHECK rejects anything else, so the builder must not emit it."""
    in_pilot, fringe = cells_for(BOX)
    for cell in in_pilot | fringe:
        assert h3.get_resolution(cell) == RESOLUTION


def test_rows_close_the_boundary_ring() -> None:
    """PostGIS refuses an open polygon; cell_to_boundary returns six points."""
    in_pilot, _ = cells_for(BOX)
    cell = next(iter(in_pilot))
    (_, _, centroid, boundary, state, flag) = next(rows_for([cell], [], state_fips="22"))
    assert centroid.startswith("SRID=4326;POINT(")
    assert boundary.startswith("SRID=4326;POLYGON((")
    points = boundary.split("((")[1].removesuffix("))").split(", ")
    assert len(points) == 7, "six vertices plus the repeated first"
    assert points[0] == points[-1], "the ring is closed"
    assert state == "22"
    assert flag is True


def test_rows_are_lng_lat_not_lat_lng() -> None:
    """The commonest way to build a grid that lands in the Indian Ocean."""
    in_pilot, _ = cells_for(BOX)
    cell = next(iter(in_pilot))
    (_, _, centroid, _, _, _) = next(rows_for([cell], [], state_fips="22"))
    lng, lat = (float(part) for part in centroid.split("(")[1].rstrip(")").split())
    expected_lat, expected_lng = h3.cell_to_latlng(cell)
    assert lat == pytest.approx(expected_lat)
    assert lng == pytest.approx(expected_lng)


def test_fringe_rows_carry_the_flag_false() -> None:
    in_pilot, fringe = cells_for(BOX)
    rows = list(rows_for(in_pilot, fringe, state_fips="22"))
    flags = [row[-1] for row in rows]
    assert flags.count(True) == len(in_pilot)
    assert flags.count(False) == len(fringe)


async def test_build_writes_prunes_and_assigns_in_one_transaction() -> None:
    import json

    connection = FakeConnection(json.dumps(BOX))
    report = await build_grid(connection, state_fips="22")

    assert connection.transactions == 1
    assert connection.inserted, "cells were written"
    # The prune and the parish assignment both run, and after the insert.
    assert len(connection.executed) == 2
    assert "DELETE FROM hex" in connection.executed[0]
    assert "UPDATE hex" in connection.executed[1]
    assert report.parishes == 64


async def test_build_refuses_when_the_tract_layer_is_empty() -> None:
    """The boundary is cut from census_tract, so its absence is the real error."""
    connection = FakeConnection(None)
    with pytest.raises(LookupError, match="census_acs"):
        await build_grid(connection, state_fips="22")


async def test_build_refuses_a_boundary_that_yields_no_cells() -> None:
    """A valid polygon too small to contain any cell centre.

    Not a malformed one: h3 raises on its own for those, before this check is
    reached. This is the case that returns an empty set quietly, which would
    otherwise write a grid of nothing and report success.
    """
    import json

    tiny = {
        "type": "Polygon",
        "coordinates": [
            [
                [-92.0, 29.0],
                [-91.9999, 29.0],
                [-91.9999, 29.0001],
                [-92.0, 29.0001],
                [-92.0, 29.0],
            ]
        ],
    }
    connection = FakeConnection(json.dumps(tiny))
    with pytest.raises(ValueError, match="no cells"):
        await build_grid(connection, state_fips="22")


def test_the_area_check_can_actually_fail() -> None:
    """A sanity check that never fails is decoration."""
    good = GridReport(in_pilot=171_725, fringe=1_699, area_km2=135_653.0, parishes=64)
    assert good.plausible
    assert good.area_error < 0.001

    half = GridReport(in_pilot=85_000, fringe=800, area_km2=67_000.0, parishes=64)
    assert not half.plausible
    assert "IMPLAUSIBLE" in half.summary()


async def test_export_marks_every_cell_unscored() -> None:
    """A grey hexagon must not be readable as a measured low one."""
    from pipeline.grid import UNSCORED_REASON, export_for_tiles

    connection = FakeConnection(None)
    connection.rows = [{"h3": "88444c16b3fffff"}, {"h3": "884440a8c5fffff"}]
    payload = await export_for_tiles(connection)

    assert payload["scored"] is False
    assert len(payload["hexes"]) == 2
    for fields in payload["hexes"].values():
        assert fields["no_score_reason"] == UNSCORED_REASON
        assert "score" not in fields
        assert "percentile" not in fields, "a percentile would colour the cell"


async def test_export_is_json_serialisable_in_the_shape_tiles_reads() -> None:
    """`pipeline tiles` does payload['hexes'].items(); keep that contract."""
    import json as json_module

    from pipeline.grid import export_for_tiles

    connection = FakeConnection(None)
    connection.rows = [{"h3": "88444c16b3fffff"}]
    payload = await export_for_tiles(connection)

    reloaded = json_module.loads(json_module.dumps(payload))
    assert list(reloaded["hexes"]) == ["88444c16b3fffff"]


def test_report_arithmetic() -> None:
    report = GridReport(in_pilot=100, fringe=10, area_km2=79.0, parishes=64)
    assert report.total == 110
    assert report.mean_cell_km2 == pytest.approx(0.79)
