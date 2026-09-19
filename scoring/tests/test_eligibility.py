"""Methodology section 5: the 25-person threshold that sets every denominator.

This is the smallest module in the package and the one with the widest blast
radius. The set it returns is what section 9 ranks against, so an off-by-one at
the threshold does not produce a few wrong hexes, it moves every percentile in
Louisiana.
"""

import math

import pytest

from burden.eligibility import MINIMUM_POPULATION, eligible


def test_the_threshold_is_the_one_the_methodology_states() -> None:
    assert MINIMUM_POPULATION == 25.0


def test_a_hex_with_exactly_twenty_five_people_is_scored() -> None:
    # Section 5 excludes hexes "below 25", so 25 is inside. The boundary is
    # worth pinning because "below" and "at most" differ by exactly this hex.
    assert eligible({"h0": 25.0}).scored == ("h0",)


def test_a_hex_one_person_short_is_not() -> None:
    result = eligible({"h0": 24.0})

    assert result.scored == ()
    assert result.reasons() == {"h0": "low_population"}


def test_an_empty_cell_is_excluded_and_says_why() -> None:
    (row,) = eligible({"marsh": 0.0}).excluded

    assert row.reason == "low_population"
    assert row.population == 0.0


def test_a_hex_with_no_population_estimate_is_treated_as_unpopulated() -> None:
    # CS-106 returns no_population when every contributing overlap held zero
    # people, and interpolate.py already reads that as an unpopulated cell that
    # section 11 leaves unscored. This follows that reading rather than
    # inventing a second one.
    (row,) = eligible({"marsh": None}).excluded

    assert row.reason == "low_population"
    assert row.population is None


def test_the_population_is_carried_so_the_panel_can_explain_the_hole() -> None:
    # "21 estimated residents" is a different message from "not scored", and it
    # is the difference between a reader trusting the map and filing a bug.
    (row,) = eligible({"h0": 21.0}).excluded

    assert row.population == 21.0


def test_the_scored_and_excluded_sets_partition_the_grid() -> None:
    population: dict[str, float | None] = {
        "town": 1200.0,
        "edge": 25.0,
        "hamlet": 24.999,
        "marsh": 0.0,
        "water": None,
    }

    result = eligible(population)

    assert result.scored == ("edge", "town")
    assert sorted(result.reasons()) == ["hamlet", "marsh", "water"]
    assert len(result.scored) + len(result.excluded) == len(population)


def test_the_scored_universe_comes_out_ordered() -> None:
    # It becomes the denominator every indicator is ranked against, and section
    # 13 wants a run reproducible from its inputs.
    result = eligible({"hC": 100.0, "hA": 100.0, "hB": 100.0})

    assert result.scored == ("hA", "hB", "hC")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_population_that_is_not_a_number_is_refused(bad: float) -> None:
    # A NaN compares false against every threshold, so it would pass the filter
    # and land in a denominator. Refused here, where the hex that produced it is
    # still in hand.
    with pytest.raises(ValueError, match="not finite"):
        eligible({"h0": bad})


def test_an_empty_grid_is_not_an_error() -> None:
    result = eligible({})

    assert result.scored == ()
    assert result.excluded == ()
