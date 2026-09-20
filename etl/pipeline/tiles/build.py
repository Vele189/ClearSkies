"""Build the PMTiles archive the map reads.

One file, written once per scoring run, served from object storage with no tile
server in front of it. The browser fetches the parts it needs with HTTP Range
requests, which is what PMTiles is for.

**Why an archive and not a server.** The tiles of a run never change: a scoring
run produces them and the next run replaces them wholesale. A tile server would
be a process to deploy, monitor, and pay for in order to hand out bytes that are
already decided. The trade is that the archive is one large object read in
pieces, which is why CS-207 puts it on R2 rather than behind the Railway edge
cache: that cache keys on whole URLs and would either miss on every Range request
or cache the whole archive to serve a kilobyte of it.

**Every hex with a row is in the tiles, scored or not.** `no_score_reason` is one
of the attributes precisely so the map can explain a hole rather than leave one.
A grey cell that says "fewer than 25 residents" is a different thing from a gap
where a cell failed to draw, and a reader cannot tell those apart unless the
unscored cells are present and labelled. It costs archive size, which is measured
rather than assumed; `build_archive` reports what the choice cost.

**Nulls are absent keys, not null values.** A vector tile has no null: a property
is present or it is not. So a scored hex carries no `no_score_reason` key at all
and an unscored one carries no `score`. MapLibre reads a missing property as
null, which is what `MapView` already coalesces against, and the alternative —
encoding a sentinel like 0 or -1 — is the zero-for-missing failure section 11
spends a page ruling out, arriving by the back door in the render layer.

**Geometry comes from H3, not from the database.** A cell index determines its
own boundary, so the archive needs no geometry column and no PostGIS at build
time. That also means a tile can be rebuilt from a list of indexes and scores
alone, which is what makes this step repeatable rather than an export someone
did once.

**Low zooms draw parent cells, and the parent shows its worst child.** At zoom 6
one screen pixel covers about two kilometres, so a res-8 cell is under half a
pixel: drawing all of them there is not merely expensive, it is invisible. Doing
it that way puts every cell in the state into each zoom-6 tile; a full-state
build never finished in twenty-five minutes, and the measured trend put roughly
2.4 MB in front of the browser before the first frame, nearly all of it
sub-pixel polygons. So each zoom draws the coarsest H3 resolution that is still
a few pixels across, which is what the grid was chosen for: section 5 picked
hexagons partly because they nest hierarchically for aggregation.

Measured over 294,398 cells, a rectangle larger than Louisiana's land area: a
20.5 MB archive, a 26 kB largest tile, and 35 kB fetched before the first frame,
built in 256 seconds.

The rule for what a parent shows is deliberately **not an aggregate**. No mean,
no median, no invented statistic. A parent cell carries the attributes of one
real child, the one with the highest percentile, and adds `aggregated` and the
number of children it stood in for. Every number on a low-zoom cell is therefore
a number that is true of some actual hexagon, its colour and its opacity
describe the same cell, and clicking it drills into the most burdened hexagon in
that area, which is what a reader at statewide zoom is looking for anyway. A
mean would hide the hotspot the map exists to find, and averaging percentiles
across cells is not a percentile of anything.

This is still a presentation choice the methodology does not yet describe, and
it should be written into `docs/methodology.md` with a changelog entry before
the map is published. It is recorded here and in the backlog rather than left
for a reader to infer from a build script.
"""

import gzip
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3
import mapbox_vector_tile
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

# The source layer `MapView` asks for. Changing it breaks the frontend silently,
# because MapLibre renders nothing for a source-layer it cannot find.
LAYER_NAME = "hexes"

# Web Mercator, the projection every slippy map and every vector tile uses.
EARTH_RADIUS_M = 6378137.0
WORLD_EDGE_M = math.pi * EARTH_RADIUS_M

# MVT integer grid per tile. 4096 is the near-universal choice and is what
# MapLibre assumes when a tile does not say otherwise.
TILE_EXTENT = 4096

# z6 shows Louisiana whole, which is where the map opens. z12 is about 40 m per
# pixel, well past the point where a 0.7 km2 cell is a large object on screen,
# so more zoom levels would add bytes and no information.
DEFAULT_MIN_ZOOM = 6
DEFAULT_MAX_ZOOM = 12

# The coarsest H3 resolution still worth drawing at each zoom, sized so a cell
# is at least a few pixels across. At latitude 31 a pixel spans about
# 134 km / 2^zoom, and a res-r cell is roughly twice its edge length across:
#
#     zoom 6   2100 m/px   res 5 cell ~17 km   ~8 px
#     zoom 7   1050 m/px   res 6 cell ~6.5 km  ~6 px
#     zoom 8    525 m/px   res 6 cell ~6.5 km  ~12 px
#     zoom 9    262 m/px   res 7 cell ~2.4 km  ~9 px
#     zoom 10   131 m/px   res 8 cell ~0.9 km  ~7 px
#
# Past zoom 10 the scored cell itself is comfortably visible, so the pyramid
# stops. A zoom absent from this table draws the source resolution.
ZOOM_RESOLUTION: dict[int, int] = {6: 5, 7: 6, 8: 6, 9: 7}


@dataclass(frozen=True, slots=True)
class ScoredHex:
    """One row of `hex_score`, reduced to what the map draws.

    These six attributes are CS-207's acceptance criteria, and they are also
    everything the map needs to colour a cell, dim it by confidence, explain why
    it has no score, and hand an H3 index to the drill-down endpoint.
    """

    h3: str
    score: float | None = None
    percentile: float | None = None
    confidence: float | None = None
    confidence_band: str | None = None
    no_score_reason: str | None = None

    def properties(self, *, stood_in_for: int = 0) -> dict[str, Any]:
        """The feature's attributes, with absent values left out entirely.

        `stood_in_for` is set on a low-zoom parent cell and is the number of
        source cells this one was drawn in place of. Its presence is what tells
        the frontend the footprint is a parent rather than a scored hexagon;
        every other attribute still describes one real cell.
        """
        fields: dict[str, Any] = {"h3": self.h3}
        if self.score is not None:
            fields["score"] = round(self.score, 4)
        if self.percentile is not None:
            fields["percentile"] = round(self.percentile, 4)
        if self.confidence is not None:
            fields["confidence"] = round(self.confidence, 4)
        if self.confidence_band is not None:
            fields["confidence_band"] = self.confidence_band
        if self.no_score_reason is not None:
            fields["no_score_reason"] = self.no_score_reason
        if stood_in_for:
            fields["aggregated"] = True
            fields["cells"] = stood_in_for
        return fields


@dataclass(frozen=True, slots=True)
class TileBuild:
    """What one build produced, and what it costs to load.

    The sizes are the point of the last acceptance criterion. `archive_bytes` is
    what sits in the bucket; `initial_load_bytes` is what a browser actually
    pulls before the first frame, which is a far smaller and far more useful
    number.
    """

    path: Path
    features: int
    hexes: int
    tiles: int
    archive_bytes: int
    largest_tile_bytes: int
    initial_load_bytes: int
    min_zoom: int
    max_zoom: int

    @property
    def archive_mb(self) -> float:
        return self.archive_bytes / 1_000_000

    @property
    def initial_load_kb(self) -> float:
        return self.initial_load_bytes / 1_000

    def summary(self) -> str:
        return (
            f"{self.path.name}: {self.hexes:,} hexes, {self.features:,} features "
            f"across {self.tiles:,} tiles, z{self.min_zoom}-z{self.max_zoom}\n"
            f"  archive {self.archive_mb:.2f} MB, "
            f"initial load {self.initial_load_kb:.0f} kB, "
            f"largest tile {self.largest_tile_bytes / 1000:.0f} kB"
        )


def build_archive(
    hexes: Iterable[ScoredHex],
    path: Path,
    *,
    min_zoom: int = DEFAULT_MIN_ZOOM,
    max_zoom: int = DEFAULT_MAX_ZOOM,
    attribution: str = "ClearSkies",
) -> TileBuild:
    """Write every hex into one PMTiles archive at `path`.

    Deterministic: the same hexes in any order produce the same bytes, because
    features are sorted within a tile and tiles are written in tile-id order.
    A scoring run that is reproducible under section 13 should not produce a
    different archive each time it is asked to.
    """
    if min_zoom > max_zoom:
        raise ValueError(f"min_zoom {min_zoom} is above max_zoom {max_zoom}")

    rows = sorted(hexes, key=lambda row: row.h3)
    if not rows:
        raise ValueError("no hexes to build tiles from")

    base_resolution = h3.get_resolution(rows[0].h3)
    shapes: dict[str, tuple[tuple[float, float], ...]] = {}

    def ring_of(cell: str) -> tuple[tuple[float, float], ...]:
        # Parent cells repeat across zooms, so the boundaries are cached rather
        # than recomputed for every level of the pyramid.
        if cell not in shapes:
            shapes[cell] = _ring(cell)
        return shapes[cell]

    encoded: dict[int, bytes] = {}
    tile_sizes: dict[int, int] = {}
    initial_load = 0
    features = 0

    for zoom in range(min_zoom, max_zoom + 1):
        drawn = _drawn_at(rows, base_resolution, ZOOM_RESOLUTION.get(zoom, base_resolution))

        buckets: dict[tuple[int, int], list[_Drawn]] = {}
        for item in drawn:
            for x, y in _tiles_covering(ring_of(item.cell), zoom):
                buckets.setdefault((x, y), []).append(item)

        for (x, y), members in buckets.items():
            payload = _encode_tile(members, shapes, zoom, x, y)
            tile_id = zxy_to_tileid(zoom, x, y)
            encoded[tile_id] = payload
            tile_sizes[tile_id] = len(payload)
            features += len(members)
            if zoom == min_zoom:
                initial_load += len(payload)

    bounds = _bounds([ring_of(row.h3) for row in rows])
    _write(path, encoded, bounds, min_zoom, max_zoom, attribution)

    archive_bytes = path.stat().st_size
    # A cold load fetches the header and root directory before any tile. PMTiles
    # clients read the first 16 kB in one request and usually have both. Capped
    # at the archive: a client cannot pull more of a file than the file holds,
    # and for a small archive that first read has already brought the tiles too.
    header_and_root = min(16_384, archive_bytes)
    cold_load = min(archive_bytes, header_and_root + initial_load)

    return TileBuild(
        path=path,
        features=features,
        hexes=len(rows),
        tiles=len(encoded),
        archive_bytes=archive_bytes,
        largest_tile_bytes=max(tile_sizes.values()),
        initial_load_bytes=cold_load,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
    )


@dataclass(frozen=True, slots=True)
class _Drawn:
    """One polygon to put in a tile: whose boundary, and whose numbers."""

    cell: str
    row: ScoredHex
    stood_in_for: int


def _drawn_at(rows: Sequence[ScoredHex], base: int, resolution: int) -> list[_Drawn]:
    """The cells to draw at one H3 resolution.

    At the source resolution every row is drawn as itself. Coarser than that,
    rows are grouped by their parent and each parent is drawn once, carrying the
    attributes of its worst child.
    """
    if resolution >= base:
        return [_Drawn(cell=row.h3, row=row, stood_in_for=0) for row in rows]

    groups: dict[str, list[ScoredHex]] = {}
    for row in rows:
        groups.setdefault(h3.cell_to_parent(row.h3, resolution), []).append(row)

    return [
        _Drawn(cell=parent, row=_worst(children), stood_in_for=len(children))
        for parent, children in sorted(groups.items())
    ]


def _worst(children: Sequence[ScoredHex]) -> ScoredHex:
    """The child a parent cell speaks for: the most burdened one it contains.

    Not a mean and not a median. Every attribute on the parent is then true of
    one real hexagon, which is what lets the colour, the opacity and the
    drill-down all describe the same place. A mean would hide the hotspot the
    map exists to find, and the mean of a set of percentiles is not a percentile
    of anything.

    Where nothing in the group was scored, the first child by index stands in,
    carrying its own reason for having no score, so a low-zoom view over empty
    marsh still explains itself.
    """
    scored = [child for child in children if child.percentile is not None]
    if scored:
        return max(scored, key=lambda child: (child.percentile or 0.0, child.h3))
    return min(children, key=lambda child: child.h3)


def _ring(cell: str) -> tuple[tuple[float, float], ...]:
    """The cell's boundary as (lon, lat), closed, in the winding MVT expects.

    `h3.cell_to_boundary` hands back (lat, lon), which is the opposite order
    from every other geospatial interface in this codebase, so the swap happens
    once here rather than at each use.
    """
    boundary = h3.cell_to_boundary(cell)
    ring = [(lon, lat) for lat, lon in boundary]
    ring.append(ring[0])
    return tuple(ring)


def _mercator(lon: float, lat: float) -> tuple[float, float]:
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def _tile_span(zoom: int) -> float:
    return 2 * WORLD_EDGE_M / float(2**zoom)


def _tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    span = _tile_span(zoom)
    minx = -WORLD_EDGE_M + x * span
    maxy = WORLD_EDGE_M - y * span
    return minx, maxy - span, minx + span, maxy


def _tiles_covering(ring: Sequence[tuple[float, float]], zoom: int) -> Iterator[tuple[int, int]]:
    """Every tile the cell's bounding box touches at this zoom.

    A hex straddling a tile edge belongs to both tiles. Its geometry then runs
    past the tile extent on one side, which is exactly what renderers expect and
    clip; leaving it out of one of them is what produces seams.
    """
    corners = [_mercator(lon, lat) for lon, lat in ring]
    span = _tile_span(zoom)
    limit = 2**zoom - 1

    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]

    x_lo = _clamp(int((min(xs) + WORLD_EDGE_M) // span), limit)
    x_hi = _clamp(int((max(xs) + WORLD_EDGE_M) // span), limit)
    y_lo = _clamp(int((WORLD_EDGE_M - max(ys)) // span), limit)
    y_hi = _clamp(int((WORLD_EDGE_M - min(ys)) // span), limit)

    for x in range(x_lo, x_hi + 1):
        for y in range(y_lo, y_hi + 1):
            yield x, y


def _clamp(value: int, limit: int) -> int:
    return max(0, min(limit, value))


def _encode_tile(
    members: Sequence[_Drawn],
    shapes: dict[str, tuple[tuple[float, float], ...]],
    zoom: int,
    x: int,
    y: int,
) -> bytes:
    layer = {
        "name": LAYER_NAME,
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[_mercator(lon, lat) for lon, lat in shapes[item.cell]]],
                },
                "properties": item.row.properties(stood_in_for=item.stood_in_for),
            }
            # Sorted so two builds of the same run write identical bytes.
            for item in sorted(members, key=lambda item: item.cell)
        ],
    }

    raw = mapbox_vector_tile.encode(
        [layer],
        default_options={
            "quantize_bounds": _tile_bounds(zoom, x, y),
            "extents": TILE_EXTENT,
        },
    )
    # mtime=0 so the gzip header carries no timestamp; otherwise an archive
    # built twice from the same scores would differ byte for byte.
    return gzip.compress(raw, mtime=0)


def _bounds(rings: Iterable[tuple[tuple[float, float], ...]]) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for ring in rings:
        for lon, lat in ring:
            lons.append(lon)
            lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def _write(
    path: Path,
    tiles: dict[int, bytes],
    bounds: tuple[float, float, float, float],
    min_zoom: int,
    max_zoom: int,
    attribution: str,
) -> None:
    west, south, east, north = bounds
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("wb") as handle:
        writer = Writer(handle)  # type: ignore[no-untyped-call]
        # PMTiles stores tiles in Hilbert order, which zxy_to_tileid produces
        # and the writer requires; out of order it builds a directory that
        # clients cannot binary-search.
        for tile_id in sorted(tiles):
            writer.write_tile(tile_id, tiles[tile_id])  # type: ignore[no-untyped-call]

        writer.finalize(  # type: ignore[no-untyped-call]
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "min_lon_e7": int(west * 1e7),
                "min_lat_e7": int(south * 1e7),
                "max_lon_e7": int(east * 1e7),
                "max_lat_e7": int(north * 1e7),
                "center_zoom": min_zoom,
                "center_lon_e7": int((west + east) / 2 * 1e7),
                "center_lat_e7": int((south + north) / 2 * 1e7),
            },
            {
                "name": "ClearSkies burden score",
                "type": "overlay",
                "attribution": attribution,
                # MapLibre reads this to know the layer exists and what it holds
                # before it has fetched a single tile.
                "vector_layers": [
                    {
                        "id": LAYER_NAME,
                        "minzoom": min_zoom,
                        "maxzoom": max_zoom,
                        "fields": {
                            "h3": "String",
                            "score": "Number",
                            "percentile": "Number",
                            "confidence": "Number",
                            "confidence_band": "String",
                            "no_score_reason": "String",
                            "aggregated": "Boolean",
                            "cells": "Number",
                        },
                    }
                ],
            },
        )
