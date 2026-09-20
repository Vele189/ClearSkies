#!/usr/bin/env python3
"""Rebuild `tile_scores.json`, the fixture CI builds tiles from.

    etl/.venv/bin/python tests/fixtures/make_tile_scores.py

Real Louisiana cells, invented numbers. It exists so `python -m pipeline tiles`
can run end to end in CI without a database, on the same terms as
`python -m pipeline run fake` proves the adapter contract without an upstream.
"""

import json
import pathlib

import h3

OUT = pathlib.Path(__file__).resolve().parent / "tile_scores.json"
ANCHOR = h3.latlng_to_cell(30.45, -91.15, 8)


def main() -> None:
    cells = sorted(h3.grid_disk(ANCHOR, 3))
    hexes: dict[str, dict[str, object]] = {}

    for index, cell in enumerate(cells):
        # Every seventh cell unscored, so the fixture exercises the branch that
        # puts a reason in the tile instead of a score.
        if index % 7 == 0:
            hexes[cell] = {"no_score_reason": "low_population"}
            continue
        percentile = round(1.0 + (index * 97) % 99, 1)
        hexes[cell] = {
            "score": round(percentile / 2, 2),
            "percentile": percentile,
            "confidence": round(0.4 + (index % 60) / 100, 2),
            "confidence_band": "high" if percentile > 60 else "moderate",
        }

    OUT.write_text(
        json.dumps(
            {
                "source": "SYNTHETIC FIXTURE - invented scores, not a scored run",
                "methodology_version": "0.1.2",
                "hexes": hexes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {OUT} with {len(hexes)} cells")


if __name__ == "__main__":
    main()
