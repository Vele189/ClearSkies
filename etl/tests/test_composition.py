"""Racial composition per hexagon (`pipeline.analysis.composition`).

Two things are worth pinning. The shares must be rates formed after
interpolation, not ratios averaged from tracts, because section 7 says so and
because getting it wrong is invisible in the output. And the module must reach
`tract_race_ethnicity` under the suffixed variable ids it is actually stored
under, which is the trap that silently emptied three other queries in this
pipeline.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.analysis.composition import SHARES, hex_shares, store_shares, stored
from pipeline.dasymetric.weights import Crosswalk, TractHexWeight


def weight(tract: str, h3: str, population: float, share: float) -> TractHexWeight:
    return TractHexWeight(
        tract_geoid=tract,
        h3=h3,
        population=population,
        pop_weight=share,
        area_weight=share,
        block_count=1,
        mean_block_area_m2=1_000.0,
    )


def crosswalk_of(*weights: TractHexWeight) -> Crosswalk:
    from pipeline.dasymetric.weights import crosswalk_from_weights

    return crosswalk_from_weights(weights)


class FakeConnection:
    """Serves `tract_race_ethnicity` rows and records the updates."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.asked: list[Any] = []
        self.updated: list[tuple[Any, ...]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.asked.append(args)
        wanted = set(args[0])
        return [row for row in self.rows if row["variable"] in wanted]

    async def executemany(self, query: str, args: Any) -> None:
        self.updated.extend(args)


def row(tract: str, variable: str, estimate: float | None) -> dict[str, Any]:
    return {
        "tract_geoid": tract,
        "variable": variable,
        "estimate": estimate,
        "margin_of_error": None,
        "is_extensive": True,
    }


def test_the_variables_are_asked_for_with_the_estimate_suffix() -> None:
    """The trap: the table stores B02001_003E and the recipes name B02001_003."""
    assert stored("B02001_003") == "B02001_003E"


async def test_a_share_is_a_percentage_of_the_hexes_own_population() -> None:
    """One tract, one hexagon, no interpolation to confuse the arithmetic."""
    connection = FakeConnection(
        [
            row("22001960100", "B02001_001E", 1_000.0),
            row("22001960100", "B02001_003E", 250.0),
            row("22001960100", "B03002_001E", 1_000.0),
            *(
                row("22001960100", stored(code), 0.0)
                for code in (
                    "B03002_004",
                    "B03002_005",
                    "B03002_006",
                    "B03002_007",
                    "B03002_008",
                    "B03002_009",
                )
            ),
            row("22001960100", "B03002_012E", 100.0),
        ]
    )
    crosswalk = crosswalk_of(weight("22001960100", "88444c16b3fffff", 1_000.0, 1.0))
    shares = await hex_shares(connection, crosswalk, acs_vintage="2020-2024")

    assert shares["black_pct"]["88444c16b3fffff"] == pytest.approx(25.0)
    assert shares["hispanic_pct"]["88444c16b3fffff"] == pytest.approx(10.0)
    # The seven non-white categories, summed: only Hispanic is non-zero here.
    assert shares["people_of_color_pct"]["88444c16b3fffff"] == pytest.approx(10.0)


async def test_the_rate_is_formed_after_interpolation_not_before() -> None:
    """Two tracts of very different size meeting in one hexagon.

    Averaging the tract rates would give (10% + 90%) / 2 = 50%. Interpolating
    both counts and dividing on the hexagon gives 900 of 1,100, which is 81.8%.
    The second is section 7's rule and the one a reader would check by hand.
    """
    connection = FakeConnection(
        [
            row("22001960100", "B02001_001E", 100.0),
            row("22001960100", "B02001_003E", 10.0),
            row("22001960200", "B02001_001E", 1_000.0),
            row("22001960200", "B02001_003E", 890.0),
        ]
    )
    crosswalk = crosswalk_of(
        weight("22001960100", "88444c16b3fffff", 100.0, 1.0),
        weight("22001960200", "88444c16b3fffff", 1_000.0, 1.0),
    )
    shares = await hex_shares(connection, crosswalk, acs_vintage="2020-2024")
    assert shares["black_pct"]["88444c16b3fffff"] == pytest.approx(900 / 1100 * 100)


async def test_a_tract_missing_part_of_a_numerator_contributes_nothing() -> None:
    """A partial numerator over a full denominator is a rate that is wrong."""
    connection = FakeConnection(
        [
            row("22001960100", "B03002_001E", 1_000.0),
            row("22001960100", "B03002_004E", 100.0),
            # the other six categories are absent
        ]
    )
    crosswalk = crosswalk_of(weight("22001960100", "88444c16b3fffff", 1_000.0, 1.0))
    shares = await hex_shares(connection, crosswalk, acs_vintage="2020-2024")
    assert shares["people_of_color_pct"] == {}


async def test_people_of_colour_sums_the_categories_rather_than_subtracting() -> None:
    """Summing is what keeps a future Census category from being absorbed silently."""
    spec = next(s for s in SHARES if s.column == "people_of_color_pct")
    assert "B03002_003" not in spec.numerator, "white alone is never in the numerator"
    assert len(spec.numerator) == 7
    assert spec.denominator == ("B03002_001",)


async def test_store_writes_one_row_per_hex_for_the_run() -> None:
    connection = FakeConnection([])
    written = await store_shares(
        connection,
        {
            "black_pct": {"88444c16b3fffff": 25.0},
            "hispanic_pct": {"88444c16b3fffff": 10.0},
            "people_of_color_pct": {"88444c16b3fffff": 40.0},
        },
        run_id=7,
    )
    assert written == 1
    assert connection.updated == [(7, "88444c16b3fffff", 25.0, 10.0, 40.0)]


async def test_a_hex_with_only_some_shares_still_stores_what_it_has() -> None:
    """The columns are independently nullable; a missing one stays NULL."""
    connection = FakeConnection([])
    await store_shares(connection, {"black_pct": {"88444c16b3fffff": 25.0}}, run_id=7)
    assert connection.updated == [(7, "88444c16b3fffff", 25.0, None, None)]
