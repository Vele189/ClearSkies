"""CS-207: the archive the map reads, and whether the host will serve it.

The build tests read the archive back with the same library a browser uses, so
what is asserted is what a client would actually find rather than what the
writer believed it wrote.
"""

import gzip
from pathlib import Path
from typing import Any

import h3
import mapbox_vector_tile
import pytest
from pmtiles.reader import MmapSource, Reader

from pipeline.tiles.build import (
    LAYER_NAME,
    ScoredHex,
    _ring,
    _tiles_covering,
    build_archive,
)

# Somewhere in Louisiana, so the numbers in these tests are the ones the real
# grid would produce rather than a special case at the equator.
ANCHOR = h3.latlng_to_cell(30.45, -91.15, 8)


def scored(cell: str, percentile: float) -> ScoredHex:
    return ScoredHex(
        h3=cell,
        score=percentile / 2,
        percentile=percentile,
        confidence=0.82,
        confidence_band="high",
    )


def patch(k: int = 2) -> list[str]:
    return sorted(h3.grid_disk(ANCHOR, k))


def read(path: Path) -> Any:
    """The archive as a PMTiles client sees it.

    Typed as Any because the reader ships no annotations, and one escape here is
    better than one on every call that uses it.
    """
    return Reader(MmapSource(path.open("rb")))  # type: ignore[no-untyped-call]


def features_at(path: Path, zoom: int, cell: str) -> list[dict[str, Any]]:
    """Every feature of the tile that contains `cell` at this zoom."""
    reader = read(path)
    x, y = next(iter(_tiles_covering(_ring(cell), zoom)))
    payload = reader.get(zoom, x, y)
    assert payload is not None, f"no tile at z{zoom} {x}/{y}"
    decoded = mapbox_vector_tile.decode(gzip.decompress(payload))
    return list(decoded[LAYER_NAME]["features"])


# ---- the archive is a real PMTiles file ----------------------------------


def test_the_archive_reads_back_as_pmtiles(tmp_path: Path) -> None:
    out = tmp_path / "t.pmtiles"
    build = build_archive([scored(c, 50.0) for c in patch()], out, min_zoom=10, max_zoom=11)

    header = read(out).header()

    assert build.archive_bytes > 0
    assert header["min_zoom"] == 10
    assert header["max_zoom"] == 11
    assert header["addressed_tiles_count"] == build.tiles


def test_the_layer_is_the_one_the_frontend_asks_for(tmp_path: Path) -> None:
    # MapView sets source-layer to "hexes" and MapLibre renders nothing at all
    # for a source-layer it cannot find, with no error.
    out = tmp_path / "t.pmtiles"
    build_archive([scored(c, 50.0) for c in patch()], out, min_zoom=11, max_zoom=11)

    metadata = read(out).metadata()

    assert metadata["vector_layers"][0]["id"] == LAYER_NAME
    assert features_at(out, 11, ANCHOR)


def test_a_cell_is_drawn_as_a_closed_hexagon(tmp_path: Path) -> None:
    out = tmp_path / "t.pmtiles"
    build_archive([scored(ANCHOR, 50.0)], out, min_zoom=12, max_zoom=12)

    geometry = features_at(out, 12, ANCHOR)[0]["geometry"]

    assert geometry["type"] == "Polygon"
    ring = geometry["coordinates"][0]
    assert len(ring) == 7  # six corners, first repeated to close
    assert ring[0] == ring[-1]


# ---- the six attributes --------------------------------------------------


def test_a_scored_hex_carries_everything_the_map_needs(tmp_path: Path) -> None:
    out = tmp_path / "t.pmtiles"
    build_archive([scored(ANCHOR, 93.5)], out, min_zoom=12, max_zoom=12)

    properties = features_at(out, 12, ANCHOR)[0]["properties"]

    assert properties == {
        "h3": ANCHOR,
        "score": 46.75,
        "percentile": 93.5,
        "confidence": 0.82,
        "confidence_band": "high",
    }


def test_a_scored_hex_carries_no_reason_key_at_all(tmp_path: Path) -> None:
    # A vector tile has no null. Encoding a sentinel instead would be the
    # zero-for-missing failure section 11 rules out, arriving in the render
    # layer by the back door.
    out = tmp_path / "t.pmtiles"
    build_archive([scored(ANCHOR, 50.0)], out, min_zoom=12, max_zoom=12)

    assert "no_score_reason" not in features_at(out, 12, ANCHOR)[0]["properties"]


def test_an_unscored_hex_is_in_the_tiles_and_says_why(tmp_path: Path) -> None:
    # The map has to be able to explain a hole. A grey cell reading "fewer than
    # 25 residents" is a different thing from a cell that failed to draw, and a
    # reader cannot tell them apart unless the unscored ones are present.
    out = tmp_path / "t.pmtiles"
    build_archive(
        [ScoredHex(h3=ANCHOR, no_score_reason="low_population")],
        out,
        min_zoom=12,
        max_zoom=12,
    )

    properties = features_at(out, 12, ANCHOR)[0]["properties"]

    assert properties == {"h3": ANCHOR, "no_score_reason": "low_population"}


# ---- the low-zoom pyramid ------------------------------------------------


def test_low_zooms_draw_far_fewer_cells_than_the_grid_holds(tmp_path: Path) -> None:
    # At zoom 6 a res-8 cell is under half a pixel. Drawing all of them there is
    # not merely expensive, it is invisible.
    cells = patch(k=6)
    out = tmp_path / "t.pmtiles"
    build_archive([scored(c, 50.0) for c in cells], out, min_zoom=6, max_zoom=6)

    drawn = features_at(out, 6, ANCHOR)

    assert len(cells) == 127
    assert len(drawn) < 10


def test_a_parent_cell_says_it_stood_in_for_others(tmp_path: Path) -> None:
    out = tmp_path / "t.pmtiles"
    build_archive([scored(c, 50.0) for c in patch(k=6)], out, min_zoom=6, max_zoom=6)

    properties = features_at(out, 6, ANCHOR)[0]["properties"]

    assert properties["aggregated"] is True
    assert properties["cells"] > 1


def test_a_parent_shows_its_worst_child_and_not_an_average(tmp_path: Path) -> None:
    # Every number on a low-zoom cell is true of one real hexagon. The mean of a
    # set of percentiles is not a percentile of anything, and it would hide the
    # hotspot the map exists to find.
    cells = patch(k=2)
    worst = cells[3]
    rows = [scored(c, 10.0) for c in cells if c != worst] + [scored(worst, 97.0)]

    out = tmp_path / "t.pmtiles"
    build_archive(rows, out, min_zoom=6, max_zoom=6)

    properties = features_at(out, 6, ANCHOR)[0]["properties"]

    assert properties["percentile"] == 97.0
    assert properties["h3"] == worst
    # The colour and the opacity describe the same real cell, not two summaries.
    assert properties["confidence"] == 0.82


def test_a_parent_with_nothing_scored_beneath_it_still_explains_itself(tmp_path: Path) -> None:
    out = tmp_path / "t.pmtiles"
    build_archive(
        [ScoredHex(h3=c, no_score_reason="low_population") for c in patch(k=2)],
        out,
        min_zoom=6,
        max_zoom=6,
    )

    properties = features_at(out, 6, ANCHOR)[0]["properties"]

    assert properties["no_score_reason"] == "low_population"
    assert "percentile" not in properties


def test_the_top_zooms_draw_the_scored_cells_themselves(tmp_path: Path) -> None:
    cells = patch(k=2)
    out = tmp_path / "t.pmtiles"
    build_archive([scored(c, 50.0) for c in cells], out, min_zoom=12, max_zoom=12)

    drawn = features_at(out, 12, ANCHOR)

    assert all("aggregated" not in f["properties"] for f in drawn)
    assert {f["properties"]["h3"] for f in drawn} <= set(cells)


# ---- reproducibility -----------------------------------------------------


def test_the_same_run_in_a_different_order_writes_identical_bytes(tmp_path: Path) -> None:
    # Section 13 wants a run reproducible from its inputs, and the archive is
    # part of what a run produced.
    rows = [scored(c, 50.0 + index) for index, c in enumerate(patch())]

    first = tmp_path / "a.pmtiles"
    second = tmp_path / "b.pmtiles"
    build_archive(rows, first, min_zoom=10, max_zoom=11)
    build_archive(list(reversed(rows)), second, min_zoom=10, max_zoom=11)

    assert first.read_bytes() == second.read_bytes()


# ---- tiling ---------------------------------------------------------------


def test_a_hex_on_a_tile_boundary_is_written_into_both_tiles(tmp_path: Path) -> None:
    # Leaving it out of one of them is what produces seams. Geometry running
    # past a tile's extent is normal and renderers clip it.
    spanning = [cell for cell in patch(k=8) if len(list(_tiles_covering(_ring(cell), 12))) > 1]

    assert spanning, "expected at least one cell to straddle a z12 tile edge"
    out = tmp_path / "t.pmtiles"
    build = build_archive([scored(c, 50.0) for c in patch(k=8)], out, min_zoom=12, max_zoom=12)

    assert build.features > build.hexes


def test_the_build_reports_what_it_costs_to_load(tmp_path: Path) -> None:
    # The last acceptance criterion. The archive size is what sits in the
    # bucket; the initial load is what a browser pulls before the first frame,
    # which is the number that decides whether the map feels broken. The
    # pyramid is what keeps the second far below the first: at the opening zoom
    # the browser fetches parent cells, not the whole grid.
    out = tmp_path / "t.pmtiles"
    build = build_archive([scored(c, 50.0) for c in patch(k=24)], out, min_zoom=6, max_zoom=12)

    assert build.archive_bytes == out.stat().st_size
    assert build.largest_tile_bytes > 0
    assert "initial load" in build.summary()
    assert build.initial_load_bytes < build.archive_bytes / 4


def test_a_small_archive_is_entirely_fetched_by_the_first_read(tmp_path: Path) -> None:
    # A client cannot pull more of a file than the file holds. PMTiles clients
    # open with a 16 kB read, so for anything smaller than that the initial load
    # is the whole archive and reporting more would be arithmetic, not traffic.
    out = tmp_path / "t.pmtiles"
    build = build_archive([scored(ANCHOR, 50.0)], out, min_zoom=6, max_zoom=7)

    assert build.archive_bytes < 16_384
    assert build.initial_load_bytes == build.archive_bytes


# ---- refusals -------------------------------------------------------------


def test_building_from_nothing_is_an_error_not_an_empty_archive(tmp_path: Path) -> None:
    # An empty archive would leave the map blank with no error anywhere.
    with pytest.raises(ValueError, match="no hexes"):
        build_archive([], tmp_path / "t.pmtiles")


def test_an_inverted_zoom_range_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="above max_zoom"):
        build_archive([scored(ANCHOR, 50.0)], tmp_path / "t.pmtiles", min_zoom=10, max_zoom=8)
