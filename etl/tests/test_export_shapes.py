"""The seam between what `export_run.py` writes and what `pipeline tiles` reads.

Lives here rather than under api/tests because it needs the ingestion package
importable, and skipping is not good enough for this one: the two shapes drifting
apart is invisible until somebody builds a map with no scores in it.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pipeline.tiles.build import ScoredHex, build_archive

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def export() -> ModuleType:
    path = SCRIPTS / "export_run.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("scripts/export_run.py is not in this tree")
    spec = importlib.util.spec_from_file_location("export_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_run"] = module
    spec.loader.exec_module(module)
    return module


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetch(self, _query: str, *_args: object) -> list[dict[str, Any]]:
        return self._rows


SCORED = "88444600ddfffff"
UNSCORED = "88444600d9fffff"


def row(**over: Any) -> dict[str, Any]:
    return {
        "h3": SCORED,
        "score": 81.4,
        "percentile": 94.2,
        "confidence": 0.71,
        "confidence_band": "moderate",
        "no_score_reason": None,
        **over,
    }


def as_scored_hexes(payload: dict[str, Any]) -> list[ScoredHex]:
    """Exactly what `pipeline.__main__._tiles` does with the file."""
    return [
        ScoredHex(
            h3=h3,
            score=cell.get("score"),
            percentile=cell.get("percentile"),
            confidence=cell.get("confidence"),
            confidence_band=cell.get("confidence_band"),
            no_score_reason=cell.get("no_score_reason"),
        )
        for h3, cell in payload["hexes"].items()
    ]


async def test_the_export_builds_an_archive_with_the_scores_in_it(
    export: ModuleType, tmp_path: Path
) -> None:
    payload = await export.tiles_payload(
        FakeConn(
            [
                row(),
                row(
                    h3=UNSCORED,
                    score=None,
                    percentile=None,
                    confidence=None,
                    confidence_band=None,
                    no_score_reason="low_population",
                ),
            ]
        ),
        12,
        "0.2.0",
    )

    rows = as_scored_hexes(payload)
    assert [r.h3 for r in rows] == [SCORED, UNSCORED]
    assert rows[0].score == 81.4
    assert rows[0].confidence == 0.71
    assert rows[0].no_score_reason is None
    # The unscored hex is in the archive, carrying its reason: the map explains
    # the hole rather than leaving one.
    assert rows[1].score is None
    assert rows[1].no_score_reason == "low_population"

    build = build_archive(rows, tmp_path / "hexes.pmtiles", min_zoom=5, max_zoom=8)
    assert build.hexes == 2


async def test_the_validation_export_would_not_have_done(export: ModuleType) -> None:
    """Why --tiles exists at all.

    `make tiles SCORES=...` had no documented producer, and the nearest export
    carries neither the score nor the confidence value and drops every unscored
    hex. Tiles built from it would draw a blank map with unexplained holes.
    """
    conn = FakeConn([row()])

    tiles = await export.tiles_payload(conn, 12, "0.2.0")
    validation = await export.validation_payload(conn, 12, "0.2.0")

    assert set(tiles["hexes"][SCORED]) == {
        "score",
        "percentile",
        "confidence",
        "confidence_band",
    }
    # The validation export over the same row, for contrast. It is right for its
    # own purpose and would lose the two fields the ramp and the hatch are drawn
    # from.
    assert set(validation["hexes"][SCORED]) == {"percentile", "confidence_band"}
