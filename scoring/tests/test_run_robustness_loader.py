"""What `scripts/run_robustness.py` makes of a run export, before any check runs.

The loader decides which hexes the section 13.5 checks are computed over, which
makes it part of the methodology rather than plumbing. AUD-19 is here: section 5
eligibility and "this run produced a score" are different sets, and the loader
was flattening them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    path = SCRIPTS / "run_robustness.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("scripts/run_robustness.py is not in this tree")
    spec = importlib.util.spec_from_file_location("run_robustness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_robustness"] = module
    spec.loader.exec_module(module)
    return module


def hexrow(
    population: float | None,
    *,
    band: str | None = "high",
    scored: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "population": population,
        "confidence_band": band,
        "scored": scored,
        "no_score_reason": reason,
        "outside_pilot_state": False,
    }


def payload(hexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"hexes": hexes, "indicators": {}, "methodology_version": "0.2.0"}


def test_a_scored_hex_is_in_the_universe(runner: ModuleType) -> None:
    grid, bands, _ = runner.load_run(payload({"a": hexrow(100.0)}))

    assert grid.scored == ("a",)
    assert bands == {"a": "high"}


def test_an_eligible_hex_the_run_could_not_score_is_excluded_not_scored(
    runner: ModuleType,
) -> None:
    """AUD-19. It holds enough people for section 5 and produced no score.

    Section 11's minimum-indicator rules are a fact about what was observed, not
    about how many people live there, so `eligible` cannot re-derive them and
    the export has to say. Such a hex carries no confidence either, because
    section 12 measures how well supported a score is and there is none.
    """
    grid, bands, _ = runner.load_run(
        payload(
            {
                "a": hexrow(100.0),
                "b": hexrow(100.0, band=None, scored=False, reason="insufficient_pollution_data"),
            }
        )
    )

    assert grid.scored == ("a",)
    assert [row.h3 for row in grid.excluded] == ["b"]
    assert [row.reason for row in grid.excluded] == ["insufficient_pollution_data"]
    # And it keeps its population, so the report can say who it was about.
    assert [row.population for row in grid.excluded] == [100.0]


def test_a_missing_band_is_absent_rather_than_the_string_none(runner: ModuleType) -> None:
    """The defect itself.

    `str(None)` is "None", which is not a band and is not missing. It passed the
    guard in `_universe`, compared unequal to "insufficient", and so put a hex
    carrying neither a score nor a confidence value into the universe the checks
    correlate over.
    """
    _, bands, _ = runner.load_run(
        payload({"b": hexrow(100.0, band=None, scored=False, reason=None)})
    )

    assert "None" not in bands.values()
    assert "b" not in bands


def test_an_unscored_hex_without_a_recorded_reason_still_leaves_the_universe(
    runner: ModuleType,
) -> None:
    """A null reason is not a licence to treat it as scored."""
    grid, _, _ = runner.load_run(
        payload({"b": hexrow(100.0, band=None, scored=False, reason=None)})
    )

    assert grid.scored == ()
    assert [row.reason for row in grid.excluded] == [runner.UNSCORED_FALLBACK]


def test_an_export_predating_the_scored_flag_falls_back_to_the_band(
    runner: ModuleType,
) -> None:
    """Under section 12 a hex has a band exactly when it has a score.

    An older export carries no `scored` key, and the band is then the only
    evidence there is. Reading it this way keeps an export written before this
    change loadable, and produces the same split it would have produced.
    """
    old_style: dict[str, dict[str, Any]] = {
        "a": {"population": 100.0, "confidence_band": "high", "outside_pilot_state": False},
        "b": {"population": 100.0, "confidence_band": None, "outside_pilot_state": False},
    }

    grid, bands, _ = runner.load_run(payload(old_style))

    assert grid.scored == ("a",)
    assert [row.h3 for row in grid.excluded] == ["b"]
    assert bands == {"a": "high"}


def test_a_low_population_hex_is_still_excluded_by_section_five(runner: ModuleType) -> None:
    """The section 5 rule is unchanged, and still re-derived rather than read."""
    grid, _, _ = runner.load_run(payload({"a": hexrow(100.0), "c": hexrow(3.0)}))

    assert grid.scored == ("a",)
    assert [(row.h3, row.reason) for row in grid.excluded] == [("c", "low_population")]
