"""What `scripts/export_run.py` writes, checked against what reads it.

The exports are the seam between a scored run and the three things that
consume one: the section 13.2 gate, the section 13.5 checks, and the tile
builder. Each takes a JSON file rather than a database, which is what makes a
result reproducible from the file -- and what makes a shape mismatch invisible
until somebody runs the whole pipeline.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    path = SCRIPTS / f"{name}.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip(f"scripts/{name}.py is not in this tree")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def export() -> ModuleType:
    return load("export_run")


class FakeConn:
    """Answers the one query the payload under test runs."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetch(self, _query: str, *_args: object) -> list[dict[str, Any]]:
        return self._rows


def row(**over: Any) -> dict[str, Any]:
    return {
        "h3": "88444600ddfffff",
        "score": 81.4,
        "percentile": 94.2,
        "confidence": 0.71,
        "confidence_band": "moderate",
        "no_score_reason": None,
        **over,
    }


async def test_a_scored_hex_carries_everything_a_tile_feature_needs(
    export: ModuleType,
) -> None:
    payload = await export.tiles_payload(FakeConn([row()]), 12, "0.2.0")

    hexes = payload["hexes"]["88444600ddfffff"]
    assert hexes == {
        "score": 81.4,
        "percentile": 94.2,
        "confidence": 0.71,
        "confidence_band": "moderate",
    }


async def test_a_scored_hex_carries_no_reason_key_at_all(export: ModuleType) -> None:
    """build.py reads presence, not truthiness: a reason is there or it is not."""
    payload = await export.tiles_payload(FakeConn([row()]), 12, "0.2.0")

    assert "no_score_reason" not in payload["hexes"]["88444600ddfffff"]


async def test_an_unscored_hex_is_exported_with_its_reason(export: ModuleType) -> None:
    """Every hex with a row is in the tiles, scored or not.

    A grey cell reading "fewer than 25 residents" is a different thing from a
    cell that failed to draw, and filtering to scored hexes -- which the
    validation export does, correctly, for its own purpose -- would turn every
    explained hole into an unexplained one.
    """
    payload = await export.tiles_payload(
        FakeConn(
            [
                row(
                    h3="88444600d9fffff",
                    score=None,
                    percentile=None,
                    confidence=None,
                    confidence_band=None,
                    no_score_reason="low_population",
                )
            ]
        ),
        12,
        "0.2.0",
    )

    assert payload["hexes"]["88444600d9fffff"] == {"no_score_reason": "low_population"}
