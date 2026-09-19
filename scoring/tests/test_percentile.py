"""Methodology section 9, the step every indicator passes through.

Every expected number here is computed by hand from `100 · (r − 0.5) / n` and
the arithmetic is written out in the comment above it. Asserting against a
second implementation of the same formula would pass just as happily if the
formula itself were wrong, and section 9 is precisely where being subtly wrong
is invisible: percentiles look plausible whatever convention produced them.
"""

import math

import pytest

from burden.percentile import BREAKPOINT_PERCENTS, quantile, rank, rank_indicators


def hexes(count: int) -> list[str]:
    return [f"h{index:03d}" for index in range(count)]


def percentiles_of(
    values: dict[str, float | None], scored: list[str] | None = None
) -> dict[str, float | None]:
    result = rank(values, scored=scored if scored is not None else list(values))
    return {row.h3: row.percentile for row in result.hexes}


# ---- the Hazen formula ---------------------------------------------------


def test_five_distinct_values_land_on_the_hazen_percentiles() -> None:
    # n = 5, ranks 1 through 5, so 100 * (r - 0.5) / 5 gives 10, 30, 50, 70, 90.
    # The (r-1)/(n-1) convention section 9 rejects would give 0, 25, 50, 75, 100
    # instead, and the 0 would annihilate a hex's whole component in section 10.
    values: dict[str, float | None] = {"h0": 10.0, "h1": 20.0, "h2": 30.0, "h3": 40.0, "h4": 50.0}

    assert percentiles_of(values) == {
        "h0": 10.0,
        "h1": 30.0,
        "h2": 50.0,
        "h3": 70.0,
        "h4": 90.0,
    }


def test_a_lone_scored_hex_sits_at_the_middle() -> None:
    # n = 1, rank 1: 100 * 0.5 / 1 = 50. Not 0 and not 100, which is the whole
    # reason for the half-rank offset.
    assert percentiles_of({"h0": 7.0}) == {"h0": 50.0}


def test_percentiles_stay_strictly_inside_zero_and_one_hundred() -> None:
    # migration 0009 puts CHECK (percentile > 0 AND percentile < 100) on
    # hex_indicator, so a convention that touched either end would fail on
    # insert rather than here.
    for count in (1, 2, 3, 10, 999):
        values: dict[str, float | None] = {
            h3: float(index) for index, h3 in enumerate(hexes(count))
        }
        for percentile in percentiles_of(values).values():
            assert percentile is not None
            assert 0.0 < percentile < 100.0


def test_the_ranking_is_by_order_not_by_magnitude() -> None:
    # One enormous outlier does not drag the others down: percentiles describe
    # position in the state, not distance from the maximum.
    assert percentiles_of({"h0": 1.0, "h1": 2.0, "h2": 3.0}) == percentiles_of(
        {"h0": 1.0, "h1": 2.0, "h2": 10_000_000.0}
    )


# ---- ties ----------------------------------------------------------------


def test_tied_hexes_share_the_mean_of_the_ranks_they_occupy() -> None:
    # n = 5. The three 2.0s occupy ranks 2, 3 and 4, mean rank 3, so
    # 100 * 2.5 / 5 = 50. Taking the lowest rank instead would give 30 and the
    # highest would give 70, and both would be a different distribution.
    values: dict[str, float | None] = {"h0": 1.0, "h1": 2.0, "h2": 2.0, "h3": 2.0, "h4": 5.0}

    assert percentiles_of(values) == {
        "h0": 10.0,
        "h1": 50.0,
        "h2": 50.0,
        "h3": 50.0,
        "h4": 90.0,
    }


def test_ties_do_not_depend_on_the_order_they_arrive_in() -> None:
    forward: dict[str, float | None] = {"h0": 2.0, "h1": 2.0, "h2": 9.0}
    backward: dict[str, float | None] = {"h2": 9.0, "h1": 2.0, "h0": 2.0}

    assert percentiles_of(forward) == percentiles_of(backward)


def test_a_wholly_tied_indicator_puts_every_hex_at_fifty() -> None:
    # Ranks 1 through 4, mean 2.5, so 100 * 2 / 4 = 50 for all of them. An
    # indicator with one value statewide separates nothing, and saying so at the
    # midpoint is the only answer that does not invent an ordering.
    values: dict[str, float | None] = dict.fromkeys(hexes(4), 3.5)

    assert set(percentiles_of(values).values()) == {50.0}


# ---- zero inflation ------------------------------------------------------


def test_the_zero_block_takes_one_shared_percentile() -> None:
    # Four zeros at ranks 1 through 4, mean rank 2.5, so 100 * 2 / 10 = 20.
    # The six positives then run 45, 55, 65, 75, 85, 95 at ranks 5 through 10.
    values: dict[str, float | None] = {
        "h0": 0.0,
        "h1": 0.0,
        "h2": 0.0,
        "h3": 0.0,
        "h4": 5.0,
        "h5": 6.0,
        "h6": 7.0,
        "h7": 8.0,
        "h8": 9.0,
        "h9": 10.0,
    }

    assert percentiles_of(values) == {
        "h0": 20.0,
        "h1": 20.0,
        "h2": 20.0,
        "h3": 20.0,
        "h4": 45.0,
        "h5": 55.0,
        "h6": 65.0,
        "h7": 75.0,
        "h8": 85.0,
        "h9": 95.0,
    }


def test_heavy_zero_inflation_is_what_the_facility_indicators_actually_look_like() -> None:
    # 70 hexes with no facility within 10 km and 30 with one, which is the shape
    # section 9 warns about for E3 and F1 through F4. The zeros hold ranks 1
    # through 70, mean rank 35.5, so 100 * 35 / 100 = 35. Nothing in the bottom
    # third of this indicator is distinguishable from anything else in it.
    values: dict[str, float | None] = dict.fromkeys(hexes(70), 0.0)
    for offset in range(30):
        values[f"h{70 + offset:03d}"] = float(offset + 1)

    result = rank(values, scored=list(values))
    by_h3 = result.by_h3()

    assert by_h3["h000"].percentile == 35.0
    assert by_h3["h069"].percentile == 35.0
    # The smallest non-zero value sits at rank 71: 100 * 70.5 / 100 = 70.5.
    assert by_h3["h070"].percentile == 70.5
    # And the largest at rank 100: 100 * 99.5 / 100 = 99.5.
    assert by_h3["h099"].percentile == 99.5
    assert result.distribution.n_zero == 70
    assert result.distribution.zero_block_percentile == 35.0


def test_the_zero_block_percentile_moves_with_how_many_others_are_zero() -> None:
    # Section 9's stated interpretive limit, as a test. The same hex, with the
    # same zero, reads as the 25th percentile in one distribution and the 45th
    # in another. This is why the hex panel publishes the zero block rather than
    # reporting the percentile alone.
    few_zeros: dict[str, float | None] = {"h0": 0.0, "h1": 1.0, "h2": 2.0, "h3": 3.0, "h4": 4.0}
    many_zeros: dict[str, float | None] = {"h0": 0.0, "h1": 0.0, "h2": 0.0, "h3": 0.0, "h4": 4.0}

    assert rank(few_zeros, scored=list(few_zeros)).distribution.zero_block_percentile == 10.0
    assert rank(many_zeros, scored=list(many_zeros)).distribution.zero_block_percentile == 40.0


def test_an_indicator_with_no_zeros_reports_no_zero_block() -> None:
    result = rank({"h0": 1.0, "h1": 2.0}, scored=["h0", "h1"])

    assert result.distribution.n_zero == 0
    assert result.distribution.zero_block_percentile is None


# ---- nulls are excluded, never zeroed ------------------------------------


def test_a_null_is_left_out_of_the_ranking_rather_than_read_as_zero() -> None:
    # Two zeros, two nulls, two positives. Ranked over the four real values the
    # zeros hold ranks 1 and 2, mean 1.5, so 100 * 1 / 4 = 25. Had the nulls
    # been imputed to zero there would be four zeros in a denominator of six and
    # the block would read 33.3 instead, which is the exact failure CONTRIBUTING
    # describes: an unmonitored hex reading as a clean one.
    values: dict[str, float | None] = {
        "h0": 0.0,
        "h1": 0.0,
        "h2": None,
        "h3": None,
        "h4": 5.0,
        "h5": 10.0,
    }

    result = rank(values, scored=list(values))
    by_h3 = result.by_h3()

    assert result.distribution.n == 4
    assert result.distribution.n_zero == 2
    assert by_h3["h0"].percentile == 25.0
    assert by_h3["h1"].percentile == 25.0
    assert by_h3["h4"].percentile == 62.5
    assert by_h3["h5"].percentile == 87.5


def test_dropping_the_nulls_entirely_gives_the_same_answer() -> None:
    with_nulls: dict[str, float | None] = {"h0": 1.0, "h1": None, "h2": 3.0, "h3": None}
    without: dict[str, float | None] = {"h0": 1.0, "h2": 3.0}

    scored = ["h0", "h1", "h2", "h3"]
    observed = {
        row.h3: row.percentile for row in rank(with_nulls, scored=scored).hexes if row.observed
    }

    assert observed == {"h0": 25.0, "h2": 75.0}
    assert observed == {row.h3: row.percentile for row in rank(without, scored=["h0", "h2"]).hexes}


def test_a_scored_hex_with_no_value_keeps_its_row_and_carries_nothing() -> None:
    # It is still a scored hex, so the detail panel still has a row to render
    # "not observed" into. migration 0009 forbids the other combination outright.
    (row,) = [r for r in rank({"h0": None, "h1": 1.0}, scored=["h0", "h1"]).hexes if r.h3 == "h0"]

    assert row.observed is False
    assert row.value is None
    assert row.percentile is None


def test_a_scored_hex_missing_from_the_values_is_unobserved_too() -> None:
    # An adapter that returns nothing for a hex and one that returns None for it
    # mean the same thing, and neither means zero.
    result = rank({"h1": 1.0}, scored=["h0", "h1"])

    assert result.by_h3()["h0"].observed is False
    assert result.distribution.n == 1


def test_a_zero_is_an_observation_and_keeps_its_value() -> None:
    row = rank({"h0": 0.0}, scored=["h0"]).by_h3()["h0"]

    assert row.observed is True
    assert row.value == 0.0
    assert row.percentile == 50.0


# ---- unscored hexes leave every denominator ------------------------------


def test_unscored_hexes_do_not_reach_the_denominator() -> None:
    # Five scored hexes and a thousand unscored marsh cells that all read zero.
    # Section 5 leaves those unscored, and letting them in would push the five
    # real percentiles into the top half of a distribution that is mostly
    # uninhabited water.
    scored = hexes(5)
    values: dict[str, float | None] = {h3: float(index) for index, h3 in enumerate(scored)}
    for index in range(1000):
        values[f"marsh{index:04d}"] = 0.0

    result = rank(values, scored=scored)

    assert result.distribution.n == 5
    assert result.distribution.n_zero == 1
    assert {row.h3: row.percentile for row in result.hexes} == {
        "h000": 10.0,
        "h001": 30.0,
        "h002": 50.0,
        "h003": 70.0,
        "h004": 90.0,
    }


def test_an_unscored_hex_gets_no_row_at_all() -> None:
    result = rank({"h0": 1.0, "marsh": 0.0}, scored=["h0"])

    assert [row.h3 for row in result.hexes] == ["h0"]


def test_the_hexes_dropped_for_being_unscored_are_counted() -> None:
    # Reported rather than dropped in silence. On a statewide run this number is
    # most of the grid, and a zero here means something upstream already
    # filtered and the exclusion can no longer be verified from this end.
    values: dict[str, float | None] = {"h0": 1.0, "m0": 0.0, "m1": 2.0, "m2": None}

    assert rank(values, scored=["h0"]).excluded_unscored == 2


def test_scoring_more_hexes_changes_the_percentiles_of_the_others() -> None:
    # The denominator is not a formality. Two of the same values ranked against
    # three peers and against five give different answers, which is why `scored`
    # is a required argument rather than something inferred from the values.
    values: dict[str, float | None] = {h3: float(index) for index, h3 in enumerate(hexes(5))}

    narrow = rank(values, scored=hexes(3)).by_h3()
    wide = rank(values, scored=hexes(5)).by_h3()

    assert narrow["h000"].percentile == pytest.approx(100 * 0.5 / 3)
    assert wide["h000"].percentile == 10.0


# ---- the stored distribution ---------------------------------------------


def test_the_distribution_records_what_was_ranked() -> None:
    values: dict[str, float | None] = {"h0": 0.0, "h1": 4.0, "h2": 9.0, "h3": None}

    distribution = rank(values, scored=list(values)).distribution

    assert distribution.n == 3
    assert distribution.n_zero == 1
    assert distribution.min_value == 0.0
    assert distribution.max_value == 9.0


def test_an_indicator_nobody_could_measure_produces_an_empty_distribution() -> None:
    # Not an error. E4 over a run where OpenAQ returned nothing is empty, and
    # the component modules drop the indicator rather than the hex.
    result = rank({"h0": None, "h1": None}, scored=["h0", "h1"])

    assert result.distribution.n == 0
    assert result.distribution.min_value is None
    assert result.distribution.max_value is None
    assert result.distribution.breakpoints == ()
    assert result.distribution.zero_block_percentile is None
    assert all(row.observed is False for row in result.hexes)


def test_no_scored_hexes_at_all_is_an_empty_ranking() -> None:
    result = rank({"marsh": 1.0}, scored=[])

    assert result.hexes == ()
    assert result.distribution.n == 0
    assert result.excluded_unscored == 1


# ---- breakpoints ---------------------------------------------------------


def test_there_is_one_breakpoint_per_whole_percent() -> None:
    result = rank({h3: float(i) for i, h3 in enumerate(hexes(20))}, scored=hexes(20))

    assert len(BREAKPOINT_PERCENTS) == 101
    assert len(result.distribution.breakpoints) == 101


def test_the_breakpoints_reproduce_the_percentiles_they_were_built_from() -> None:
    # This is what indicator_distribution is for: re-deriving a stored score
    # without the source data. Reading the breakpoint at a hex's own percentile
    # has to give that hex's value back, which only holds because `quantile`
    # inverts the same Hazen formula the ranking uses.
    values: dict[str, float | None] = {"h0": 10.0, "h1": 20.0, "h2": 30.0, "h3": 40.0, "h4": 50.0}
    result = rank(values, scored=list(values))

    for row in result.hexes:
        assert row.percentile is not None
        index = int(round(row.percentile))
        assert result.distribution.breakpoints[index] == pytest.approx(row.value)


def test_the_breakpoints_span_the_observed_range_and_never_step_backwards() -> None:
    values: dict[str, float | None] = {"h0": 10.0, "h1": 20.0, "h2": 30.0, "h3": 40.0, "h4": 50.0}
    breakpoints = rank(values, scored=list(values)).distribution.breakpoints

    assert breakpoints[0] == 10.0
    assert breakpoints[100] == 50.0
    assert list(breakpoints) == sorted(breakpoints)


def test_a_breakpoint_between_two_order_statistics_interpolates() -> None:
    # n = 5 at the 20th percentile: r = 20 * 5 / 100 + 0.5 = 1.5, halfway
    # between the values at ranks 1 and 2, so 10 + 0.5 * (20 - 10) = 15.
    assert quantile([10.0, 20.0, 30.0, 40.0, 50.0], 20) == pytest.approx(15.0)


def test_a_quantile_of_nothing_is_an_error_not_a_zero() -> None:
    with pytest.raises(ValueError, match="no values"):
        quantile([], 50)


# ---- reproducibility and bad input ---------------------------------------


def test_the_same_inputs_in_a_different_order_produce_an_identical_ranking() -> None:
    # Section 13 wants a scoring run reproducible from its inputs, and the rows
    # are persisted in the order they come out, so the order is part of the
    # output rather than an accident of dict insertion.
    forward: dict[str, float | None] = {h3: float(i) for i, h3 in enumerate(hexes(50))}
    backward: dict[str, float | None] = dict(reversed(list(forward.items())))

    assert rank(forward, scored=hexes(50)) == rank(backward, scored=list(reversed(hexes(50))))


def test_the_rows_come_out_ordered_by_hex() -> None:
    result = rank({"h2": 1.0, "h0": 2.0, "h1": 3.0}, scored=["h2", "h0", "h1"])

    assert [row.h3 for row in result.hexes] == ["h0", "h1", "h2"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_value_that_is_not_finite_is_refused(bad: float) -> None:
    # A NaN is not equal to itself, so it would sort unpredictably and corrupt
    # every other percentile in the run, not only its own.
    with pytest.raises(ValueError, match="not finite"):
        rank({"h0": bad, "h1": 1.0}, scored=["h0", "h1"])


# ---- ranking several indicators at once ----------------------------------


def test_every_indicator_is_ranked_against_the_same_scored_universe() -> None:
    # The components average percentiles across indicators, which only means
    # anything if the denominators match. E4 is missing for one hex here and
    # that hex still counts toward E1's denominator.
    scored = ["h0", "h1", "h2"]
    values: dict[str, dict[str, float | None]] = {
        "E1": {"h0": 1.0, "h1": 2.0, "h2": 3.0},
        "E4": {"h0": 1.0, "h1": None, "h2": 3.0},
    }

    rankings = rank_indicators(values, scored=scored)

    assert rankings["E1"].distribution.n == 3
    assert rankings["E4"].distribution.n == 2
    assert [row.h3 for row in rankings["E4"].hexes] == scored
    assert rankings["E4"].by_h3()["h1"].observed is False
