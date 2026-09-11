"""Methodology section 13.5, and what a robustness check has to be able to promise.

Four promises are under test here beyond the arithmetic.

That the baseline goes through the same code as the score it is measuring. A
robustness check that re-derives the score in order to compare against it is
comparing two implementations, and `test_the_baseline_specification_reproduces_cs_204`
is what makes "the same code path" a fact rather than a claim in a docstring.

That the correlation is Spearman's, with ties taking the mean of their ranks.
E3 and F1 through F4 are exactly zero across a large share of Louisiana, so the
tie block is not an edge case here, and a test shows the uncorrected shortcut
formula giving a different answer on a tied fixture.

That the thresholds are the ones section 13.5 states, applied in the direction it
states them: the two specification variants gate, the additive one does not, and
an indicator is judged on the share of hexes it moved rather than on how far it
moved the worst one.

And that the section 12 exclusion is enforced rather than advised, which means a
run whose confidence was never computed is refused instead of silently included.

The grids below are synthetic and built to have a known shape rather than to
look like Louisiana. Where a number is asserted exactly it was derived on paper
in the comment beside it; where a grid is too large for that, what is asserted is
a property the grid was constructed to have.
"""

import math
from collections.abc import Mapping, Sequence

import pytest

from burden import robustness
from burden.eligibility import Eligibility, eligible
from burden.indicators import GROUP_INDICATORS
from burden.methodology import METHODOLOGY_VERSION
from burden.percentile import Ranking, rank_indicators
from burden.pollution import pollution_burden
from burden.population import population_characteristics
from burden.robustness import (
    BASELINE,
    EXPOSURES_ONLY,
    LEAVE_ONE_OUT_MAX_MOVED_SHARE,
    SPECIFICATION_CORRELATION,
    Interpolation,
    alternative_specifications,
    check,
    interpolation_sensitivity,
    leave_one_out,
    report,
    spearman,
)
from burden.score import burden_score
from tests.registry import api_registry

EXPOSURE_IDS = GROUP_INDICATORS["exposures"]
EFFECT_IDS = GROUP_INDICATORS["environmental_effects"]
SENSITIVE_IDS = GROUP_INDICATORS["sensitive_populations"]
SOCIOECONOMIC_IDS = GROUP_INDICATORS["socioeconomic_factors"]
ALL_IDS = EXPOSURE_IDS + EFFECT_IDS + SENSITIVE_IDS + SOCIOECONOMIC_IDS


def cells(count: int) -> tuple[str, ...]:
    """Hex names that sort in the order they were generated.

    Zero-padded so that sorting by name matches sorting by index. Several
    assertions below read a hex's position out of its name, and an ordering that
    put `h10` before `h2` would make those quietly wrong.
    """
    return tuple(f"h{index:04d}" for index in range(count))


def populated(hexes: Sequence[str], population: float = 900.0) -> Eligibility:
    return eligible({h3: population for h3 in hexes})


def trusted(hexes: Sequence[str], band: str = "high") -> dict[str, str]:
    return {h3: band for h3 in hexes}


def rankings_for(
    values: Mapping[str, Mapping[str, float | None]], scored: Sequence[str]
) -> dict[str, Ranking]:
    return rank_indicators(values, scored=scored)


def aligned(hexes: Sequence[str]) -> dict[str, dict[str, float | None]]:
    """Every indicator ranking the state the same way.

    The degenerate case, and the one a broken comparison is most likely to get
    wrong in the flattering direction. Every group mean is the same percentile,
    so both components are the same number, and every specification in section
    13.5 — including the additive one — orders the hexes identically. Any
    correlation below 1.0 here would be the comparison inventing a difference.
    """
    return {
        indicator: {h3: float(index) for index, h3 in enumerate(hexes)} for indicator in ALL_IDS
    }


def transposed_reverse(count: int) -> list[int]:
    """The reverse ordering with every adjacent pair swapped.

    Reverse alone is too clean for the fixtures below: two groups that rank the
    state in exactly opposite orders cancel to a constant under equal weighting,
    and a constant has no ordering to correlate against, so the check would come
    back undefined rather than low. Transposing adjacent pairs leaves the
    ordering essentially reversed while giving the cancellation something to
    leave behind, which is what makes the resulting correlation a number rather
    than a None.
    """
    order = list(range(count - 1, -1, -1))
    for index in range(0, count - 1, 2):
        order[index], order[index + 1] = order[index + 1], order[index]
    return order


def counterweighted(hexes: Sequence[str]) -> dict[str, dict[str, float | None]]:
    """Environmental Effects ranking the state backwards from Exposures.

    The case the 1.0 / 0.5 weight is about, built so that exactly one choice
    decides the answer. Section 10 weights Exposures at twice Environmental
    Effects, so Pollution Burden still follows Exposures and the baseline
    ordering survives; weight the two equally and they very nearly cancel,
    leaving the ordering to whatever the cancellation did not remove.

    The demographic half is held constant so it cannot contribute an ordering of
    its own, which is what lets the result be attributed to the weight rather
    than shared between the weight and the data.
    """
    backwards = transposed_reverse(len(hexes))
    values: dict[str, dict[str, float | None]] = {}
    for indicator in EXPOSURE_IDS:
        values[indicator] = {h3: float(index) for index, h3 in enumerate(hexes)}
    for indicator in EFFECT_IDS:
        values[indicator] = {h3: float(backwards[index]) for index, h3 in enumerate(hexes)}
    for indicator in SENSITIVE_IDS + SOCIOECONOMIC_IDS:
        values[indicator] = {h3: 1.0 for h3 in hexes}
    return values


def traded_off(hexes: Sequence[str]) -> dict[str, dict[str, float | None]]:
    """The two components running against each other, which is what multiplying is for.

    Both pollution groups agree, so Pollution Burden climbs with the index and
    neither gating variant sees anything change. Population Characteristics runs
    backwards. Multiplying two quantities that trade off like that produces an
    ordering neither of them has; adding them nearly cancels instead, which is
    section 3's objection to the additive model made arithmetic.
    """
    backwards = transposed_reverse(len(hexes))
    values: dict[str, dict[str, float | None]] = {}
    for indicator in EXPOSURE_IDS + EFFECT_IDS:
        values[indicator] = {h3: float(index) for index, h3 in enumerate(hexes)}
    for indicator in SENSITIVE_IDS + SOCIOECONOMIC_IDS:
        values[indicator] = {h3: float(backwards[index]) for index, h3 in enumerate(hexes)}
    return values


def official_scores(grid: Eligibility, rankings: Mapping[str, Ranking]) -> dict[str, float]:
    """The score exactly as CS-204 produces it."""
    run = burden_score(
        eligibility=grid,
        pollution=pollution_burden(rankings, scored=grid.scored),
        population=population_characteristics(rankings, scored=grid.scored),
    )
    return {row.h3: row.score for row in run.scored() if row.score is not None}


# ---- the drift guard on the comparison itself ---------------------------


def test_the_baseline_specification_reproduces_cs_204() -> None:
    """The one test that makes every other result in this module mean anything.

    Exact equality rather than approximate. `_compose` and `burden_score` do the
    same multiplication on the same two component results, so any difference at
    all is a difference in the code path, which is precisely what this is here to
    forbid. A tolerance would let one creep in.
    """
    hexes = cells(40)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)

    assert robustness._compose(BASELINE, rankings, scored=grid.scored) == official_scores(
        grid, rankings
    )


def test_the_baseline_reproduces_cs_204_on_a_grid_with_gaps() -> None:
    # The interesting half: hexes the components decline to score have to drop
    # out of both in the same way, or the comparison universe silently differs
    # from the published one.
    hexes = cells(30)
    grid = populated(hexes)
    values = aligned(hexes)
    # Strip three of the four Exposures indicators from the first ten hexes, so
    # the group misses its 2-of-4 minimum and section 11 rule 3's fallback runs.
    for indicator in EXPOSURE_IDS[:3]:
        for h3 in hexes[:10]:
            values[indicator][h3] = None

    rankings = rankings_for(values, grid.scored)
    composed = robustness._compose(BASELINE, rankings, scored=grid.scored)

    assert composed == official_scores(grid, rankings)
    assert len(composed) == 30


# ---- Spearman, checked against values derived on paper ------------------


def test_a_perfectly_aligned_pair_correlates_at_one() -> None:
    left = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
    right = {"a": 2.0, "b": 4.0, "c": 6.0, "d": 8.0}
    assert spearman(left, right) == pytest.approx(1.0)


def test_a_perfectly_reversed_pair_correlates_at_minus_one() -> None:
    left = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
    right = {"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}
    assert spearman(left, right) == pytest.approx(-1.0)


def test_it_matches_the_shortcut_formula_where_there_are_no_ties() -> None:
    # Ranks 1..5 against 2,1,4,3,5. The differences are -1, 1, -1, 1, 0, so
    # sum d^2 = 4 and rho = 1 - 6*4/(5^3 - 5) = 1 - 24/120 = 0.8. The shortcut
    # is exact when nothing is tied, which makes it a usable independent check.
    left = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0}
    right = {"a": 2.0, "b": 1.0, "c": 4.0, "d": 3.0, "e": 5.0}
    assert spearman(left, right) == pytest.approx(0.8)


def test_ties_take_the_mean_of_their_ranks() -> None:
    # Ranks 1,2,3,4 against a variable holding two pairs: mid-ranks 1.5, 1.5,
    # 3.5, 3.5. Pearson on those gives 4 / (sqrt(5) * 2) = 0.8944271...
    #
    # The uncorrected shortcut gives 1 - 6*1/(4^3 - 4) = 0.9 on the same data.
    # E3 and F1 through F4 are exactly zero over a large share of Louisiana, so
    # the gap between the two is not an edge case here: it grows with the size
    # of the zero block, which is the largest tie in the whole dataset.
    left = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
    right = {"a": 1.0, "b": 1.0, "c": 2.0, "d": 2.0}

    assert spearman(left, right) == pytest.approx(4.0 / (math.sqrt(5.0) * 2.0))
    assert spearman(left, right) != pytest.approx(0.9)


def test_it_is_computed_over_the_shared_hexes_only() -> None:
    left = {"a": 1.0, "b": 2.0, "c": 3.0, "zzz": 99.0}
    right = {"a": 1.0, "b": 2.0, "c": 3.0}
    assert spearman(left, right) == pytest.approx(1.0)


def test_fewer_than_two_shared_hexes_has_no_correlation() -> None:
    assert spearman({"a": 1.0}, {"a": 1.0}) is None
    assert spearman({"a": 1.0}, {"b": 1.0}) is None


def test_a_constant_side_has_no_correlation_rather_than_a_zero_one() -> None:
    # Every hex tied on one side leaves its rank variance zero, so the statistic
    # does not exist. Reporting it as 0.0 would say the two orderings are
    # unrelated, which is a claim about data that has no ordering to compare.
    left = {"a": 1.0, "b": 2.0, "c": 3.0}
    right = {"a": 5.0, "b": 5.0, "c": 5.0}
    assert spearman(left, right) is None


def test_the_correlation_never_escapes_its_range() -> None:
    hexes = cells(200)
    values = {h3: float(index) for index, h3 in enumerate(hexes)}
    assert -1.0 <= spearman(values, values) <= 1.0  # type: ignore[operator]


# ---- 13.5 check 1: alternative specifications ---------------------------


def test_every_specification_agrees_when_every_indicator_does() -> None:
    hexes = cells(50)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)

    results = {row.name: row for row in alternative_specifications(rankings, scored=grid.scored)}

    # Including the additive one. Addition and multiplication disagree about how
    # to trade one component against the other, and there is nothing to trade
    # when both components are the same number for every hex.
    for name in ("equal_weights", "exposures_only", "additive"):
        assert results[name].correlation == pytest.approx(1.0)
        assert results[name].met


def test_the_two_specification_variants_gate_and_the_additive_one_does_not() -> None:
    hexes = cells(50)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)
    results = {row.name: row for row in alternative_specifications(rankings, scored=grid.scored)}

    assert results["equal_weights"].gating
    assert results["exposures_only"].gating
    # Section 13.5: reported rather than required, because section 3 rejects the
    # additive model for making a different claim rather than a worse one.
    assert not results["additive"].gating


def test_a_weight_change_that_reorders_the_state_fails_its_variant() -> None:
    hexes = cells(60)
    grid = populated(hexes)
    rankings = rankings_for(counterweighted(hexes), grid.scored)

    results = {row.name: row for row in alternative_specifications(rankings, scored=grid.scored)}

    # Moving Environmental Effects from 0.5 to 1.0 lets it cancel Exposures
    # instead of being outweighed by it, and the state comes out in a different
    # order. This is the check doing its job: a score whose ordering turns on one
    # weight has not been validated by finding the right sites, because it would
    # have found different sites under a weight nobody argued against.
    assert results["equal_weights"].correlation is not None
    assert results["equal_weights"].correlation < SPECIFICATION_CORRELATION
    assert not results["equal_weights"].met

    # And the weight is what did it. The Exposures-only variant never reads
    # Environmental Effects at all, so it is nearly unmoved by the same grid,
    # which is how this fixture attributes the failure rather than merely
    # producing one.
    assert results["exposures_only"].correlation == pytest.approx(1.0, abs=0.01)
    assert results["exposures_only"].met


def test_a_reported_variant_passes_however_low_it_goes() -> None:
    hexes = cells(60)
    grid = populated(hexes)
    rankings = rankings_for(traded_off(hexes), grid.scored)

    results = {row.name: row for row in alternative_specifications(rankings, scored=grid.scored)}
    additive = results["additive"]

    # The two components trade off here, so multiplying and adding disagree about
    # the ordering almost entirely. Section 13.5 expects exactly this and treats
    # it as informative: section 3 rejects the additive model for making a
    # different claim, so a low number is the finding rather than the failure.
    assert additive.correlation is not None
    assert additive.correlation < SPECIFICATION_CORRELATION
    assert additive.met
    assert "Reported, not gating" in additive.detail

    # Nothing else moved, so the run as a whole still clears section 13.5.
    assert results["equal_weights"].met
    assert results["exposures_only"].met


def test_a_gating_variant_with_no_computable_correlation_fails() -> None:
    # One hex leaves nothing to correlate. Section 13.5 asks for evidence that
    # the ordering survives the change, and "there was not enough to say" is not
    # that evidence, so it fails rather than passing by default.
    hexes = cells(1)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)

    results = alternative_specifications(rankings, scored=grid.scored)
    for row in results:
        assert row.correlation is None
        assert row.met is (not row.gating)


def test_exposures_only_reports_the_hexes_it_could_not_score() -> None:
    hexes = cells(20)
    grid = populated(hexes)
    values = aligned(hexes)
    # Leave these five hexes with one Exposures indicator. The baseline keeps
    # them through section 11 rule 3's fallback to Environmental Effects; the
    # Exposures-only variant has nothing to fall back to.
    for indicator in EXPOSURE_IDS[1:]:
        for h3 in hexes[:5]:
            values[indicator][h3] = None

    rankings = rankings_for(values, grid.scored)
    result = alternative_specifications(
        rankings, scored=grid.scored, specifications=(EXPOSURES_ONLY,)
    )[0]

    assert result.hexes_baseline_only == 5
    assert result.hexes_variant_only == 0
    assert result.hexes_compared == 15


# ---- 13.5 check 2: leave one indicator out ------------------------------


def test_one_result_per_indicator_in_the_registry_of_record() -> None:
    hexes = cells(30)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)

    results = leave_one_out(rankings, scored=grid.scored)
    registry = api_registry()

    # Against `api/app/indicators.py` rather than against a list retyped here,
    # for the reason `test_indicators.py` gives: the registry is the single
    # declaration and a check that restates it proves nothing.
    assert {row.indicator for row in results} == {row.id for row in registry.INDICATORS}
    assert len(results) == 15


def test_removing_an_indicator_that_says_nothing_new_moves_nothing() -> None:
    hexes = cells(40)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)

    for row in leave_one_out(rankings, scored=grid.scored):
        # Every indicator carries the same ordering here, so dropping any one of
        # them leaves the remaining group mean identical and no hex moves.
        assert row.moved_more_than_one_decile == 0
        assert row.share_moved == pytest.approx(0.0)
        assert row.met


def test_an_indicator_carrying_the_map_alone_is_caught() -> None:
    hexes = cells(60)
    grid = populated(hexes)
    values = aligned(hexes)
    # E1 keeps the aligned ordering. Every other Exposures indicator is made
    # constant, so it contributes one tied percentile to every hex and E1 is the
    # only thing distinguishing them within the group. The demographic half is
    # left constant too, so the final ordering is E1's ordering and removing it
    # should reorder the state wholesale.
    for indicator in EXPOSURE_IDS[1:] + EFFECT_IDS + SENSITIVE_IDS + SOCIOECONOMIC_IDS:
        values[indicator] = {h3: 1.0 for h3 in hexes}

    rankings = rankings_for(values, grid.scored)
    result = {row.indicator: row for row in leave_one_out(rankings, scored=grid.scored)}["E1"]

    assert result.share_moved > LEAVE_ONE_OUT_MAX_MOVED_SHARE
    assert not result.met
    assert "doing too much work alone" in result.detail


def test_a_hex_that_loses_its_score_counts_as_moved() -> None:
    hexes = cells(20)
    grid = populated(hexes)
    values = aligned(hexes)
    # These five hexes hold exactly two Exposures indicators and no Environmental
    # Effects, so the pollution half is computable only while both survive.
    for indicator in EXPOSURE_IDS[2:] + EFFECT_IDS:
        for h3 in hexes[:5]:
            values[indicator][h3] = None

    rankings = rankings_for(values, grid.scored)
    result = {row.indicator: row for row in leave_one_out(rankings, scored=grid.scored)}["E1"]

    # Losing a score outright is at least as large a change as any decile move,
    # so it counts as one. Dropping those hexes from the denominator instead
    # would let an indicator that destroys the map look like one that moves
    # nothing.
    assert result.hexes_lost_score == 5
    assert result.moved_more_than_one_decile >= 5
    assert result.hexes_group_lost == 5


def test_tripping_a_group_minimum_is_reported_apart_from_the_movement() -> None:
    hexes = cells(30)
    grid = populated(hexes)
    values = aligned(hexes)
    # Socioeconomic Factors needs 4 of 5. Leave these hexes with exactly four,
    # so removing any of the four takes the group below its minimum while the
    # remaining indicators still say the same thing they said before.
    for h3 in hexes[:6]:
        values[SOCIOECONOMIC_IDS[4]][h3] = None

    rankings = rankings_for(values, grid.scored)
    results = {row.indicator: row for row in leave_one_out(rankings, scored=grid.scored)}

    # The distinction the field exists for: these hexes did not move because P1
    # carried information they needed, they moved because the count rule of
    # section 11 rule 2 stopped being satisfied. A reader deciding whether to
    # re-argue P1 in the paper needs to know which of the two happened.
    assert results[SOCIOECONOMIC_IDS[0]].hexes_group_lost == 6
    # Removing the indicator that was already absent from those hexes costs them
    # nothing, because the group was computing without it already.
    assert results[SOCIOECONOMIC_IDS[4]].hexes_group_lost == 0


def test_the_bar_is_ten_percent_inclusive() -> None:
    hexes = cells(10)
    grid = populated(hexes)
    rankings = rankings_for(aligned(hexes), grid.scored)
    (row,) = leave_one_out(rankings, scored=grid.scored)[:1]

    # Section 13.5 says "must not move more than 10%", so a run sitting exactly
    # on the bar has not moved more than it and passes. Stated as a test because
    # the difference between `>` and `>=` here is one hex in a hundred thousand
    # and a silent change of the published criterion.
    assert row.threshold == pytest.approx(0.10)
    assert robustness.IndicatorResult(
        indicator="E1",
        group="exposures",
        hexes_compared=100,
        moved_more_than_one_decile=10,
        hexes_lost_score=0,
        hexes_group_lost=0,
        largest_decile_move=2,
        share_moved=0.10,
        threshold=LEAVE_ONE_OUT_MAX_MOVED_SHARE,
        detail="",
    ).met


def test_a_one_decile_move_is_within_tolerance() -> None:
    # Section 13.5 allows a move of one decile without limit and counts only what
    # moves further. A check that counted every move would fail on rounding at
    # the decile boundaries and say nothing about whether an indicator dominates.
    assert robustness._decile(9.9) == 1
    assert robustness._decile(10.1) == 2
    assert robustness._decile(0.5) == 1
    assert robustness._decile(99.5) == 10


# ---- 13.5 check 3: interpolation sensitivity ----------------------------


def test_two_identical_interpolations_diverge_not_at_all() -> None:
    hexes = cells(40)
    grid = populated(hexes)
    values = aligned(hexes)
    both = Interpolation(eligibility=grid, values=values)

    result = interpolation_sensitivity(dasymetric=both, areal=both, confidence_bands=trusted(hexes))

    assert result.correlation == pytest.approx(1.0)
    assert result.moved_more_than_one_decile == 0
    assert result.hexes_dasymetric_only == 0
    assert result.hexes_areal_only == 0
    assert result.median_absolute_score_change == pytest.approx(0.0)


def test_a_different_scored_universe_is_reported_rather_than_reconciled() -> None:
    hexes = cells(30)
    values = aligned(hexes)

    # The two methods disagree about which cells clear the 25-person line of
    # section 5, which is the largest single consequence of the choice and the
    # one an average over shared hexes would hide entirely.
    dasymetric = Interpolation(eligibility=eligible({h3: 900.0 for h3 in hexes}), values=values)
    areal = Interpolation(
        eligibility=eligible({h3: (5.0 if index < 4 else 900.0) for index, h3 in enumerate(hexes)}),
        values=values,
    )

    result = interpolation_sensitivity(
        dasymetric=dasymetric, areal=areal, confidence_bands=trusted(hexes)
    )

    assert result.hexes_dasymetric_only == 4
    assert result.hexes_areal_only == 0
    assert result.hexes_compared == 26
    assert "clear the 25-person line" in result.detail


def test_it_reorders_when_the_values_disagree() -> None:
    hexes = cells(40)
    grid = populated(hexes)

    result = interpolation_sensitivity(
        dasymetric=Interpolation(eligibility=grid, values=aligned(hexes)),
        areal=Interpolation(
            eligibility=grid,
            values={
                indicator: {h3: float(len(hexes) - index) for index, h3 in enumerate(hexes)}
                for indicator in ALL_IDS
            },
        ),
        confidence_bands=trusted(hexes),
    )

    # Every indicator reversed, so every hex's standing reverses with it.
    assert result.correlation == pytest.approx(-1.0)
    assert result.largest_decile_move == 9
    assert result.share_moved > 0.5


def test_the_third_check_is_never_gating() -> None:
    hexes = cells(30)
    grid = populated(hexes)

    result = check(
        aligned(hexes),
        eligibility=grid,
        confidence_bands=trusted(hexes),
        areal=Interpolation(
            eligibility=grid,
            values={
                indicator: {h3: float(len(hexes) - index) for index, h3 in enumerate(hexes)}
                for indicator in ALL_IDS
            },
        ),
    )

    # A total reversal of the interpolation, and the run still passes. Section 7
    # argues for dasymetric weighting on grounds that do not depend on this
    # number, so a divergence here is a quantity to publish rather than a gate to
    # fail.
    assert result.interpolation is not None
    assert result.interpolation.correlation == pytest.approx(-1.0)
    assert result.passed


# ---- section 12: the exclusion is enforced, not advised -----------------


def test_insufficient_confidence_hexes_are_out_of_every_statistic() -> None:
    hexes = cells(30)
    grid = populated(hexes)
    bands = trusted(hexes)
    for h3 in hexes[:7]:
        bands[h3] = "insufficient"

    result = check(aligned(hexes), eligibility=grid, confidence_bands=bands)

    assert result.hexes_excluded_low_confidence == 7
    assert result.hexes_in_universe == 23
    assert all(row.hexes_compared == 23 for row in result.indicators)


def test_a_scored_hex_with_no_confidence_band_is_refused() -> None:
    hexes = cells(10)
    grid = populated(hexes)
    bands = trusted(hexes)
    del bands[hexes[3]]

    # A run whose confidence was never computed cannot honour section 12's
    # exclusion. Including those hexes quietly would be the failure the exclusion
    # exists to prevent, so the check declines to run at all.
    with pytest.raises(ValueError, match="no confidence band"):
        check(aligned(hexes), eligibility=grid, confidence_bands=bands)


def test_unscored_hexes_never_reach_the_comparison() -> None:
    hexes = cells(20)
    # Section 5 leaves the first six unscored for holding almost nobody.
    grid = eligible({h3: (3.0 if index < 6 else 900.0) for index, h3 in enumerate(hexes)})
    bands = trusted(grid.scored)

    result = check(aligned(hexes), eligibility=grid, confidence_bands=bands)

    assert result.hexes_in_universe == 14
    assert result.hexes_excluded_low_confidence == 0


# ---- the whole report ---------------------------------------------------


def test_a_passing_run_passes_and_names_no_failures() -> None:
    hexes = cells(40)
    grid = populated(hexes)

    result = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes))

    assert result.passed
    assert result.failures() == ()
    assert result.methodology_version == METHODOLOGY_VERSION


def test_a_failing_variant_fails_the_run_and_is_named() -> None:
    hexes = cells(60)
    grid = populated(hexes)

    result = check(counterweighted(hexes), eligibility=grid, confidence_bands=trusted(hexes))

    assert not result.passed
    assert "equal_weights" in result.failures()

    # And the additive variant is never a reason a run failed, whatever it
    # scored. Checked on the grid where it is at its lowest.
    traded = check(traded_off(hexes), eligibility=grid, confidence_bands=trusted(hexes))
    additive = traded.specification("additive").correlation
    assert additive is not None
    assert additive < SPECIFICATION_CORRELATION
    assert "additive" not in traded.failures()


def test_the_write_up_carries_the_provenance_and_the_protocol() -> None:
    hexes = cells(30)
    grid = populated(hexes)
    result = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes))

    written = report(result, scores_from="a synthetic grid, tests/test_robustness.py")

    assert "a synthetic grid, tests/test_robustness.py" in written
    assert f"Methodology version: {METHODOLOGY_VERSION}" in written
    assert "**PASS**" in written
    # Section 13.7's permitted responses are on the face of the report, because
    # the moment someone reads a failing one is the moment they most want to
    # reach for the thresholds.
    assert "Adjusting" not in written
    assert "Moving the 0.85 or the 10% because a check missed them is not one of them" in written
    # All fifteen indicators are in the table, not just the ones that moved.
    for indicator in ALL_IDS:
        assert f"| {indicator} |" in written


def test_the_write_up_says_when_the_third_check_did_not_run() -> None:
    hexes = cells(20)
    grid = populated(hexes)
    result = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes))

    written = report(result, scores_from="no areal counterpart supplied")

    assert result.interpolation is None
    # Silence would read as "no divergence found". Section 13.5 asked a question
    # and this run did not answer it, which is a different thing.
    assert "Not run" in written


def test_the_same_inputs_produce_the_same_report() -> None:
    hexes = cells(35)
    grid = populated(hexes)
    areal = Interpolation(eligibility=grid, values=aligned(hexes))

    first = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes), areal=areal)
    second = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes), areal=areal)

    # Section 13's reproducibility requirement reaches this module too: a
    # robustness result that varied between runs of the same inputs could not be
    # the evidence section 13.5 asks it to be.
    assert report(first, scores_from="x") == report(second, scores_from="x")


def test_the_thresholds_are_the_ones_the_methodology_states() -> None:
    # Stated here so that changing either constant breaks a test that names
    # section 13.5, rather than passing quietly and publishing a different
    # criterion under the same heading.
    assert SPECIFICATION_CORRELATION == 0.85
    assert LEAVE_ONE_OUT_MAX_MOVED_SHARE == 0.10
    assert robustness.LEAVE_ONE_OUT_DECILE_TOLERANCE == 1


def test_looking_up_a_result_that_is_not_there_says_so() -> None:
    hexes = cells(20)
    grid = populated(hexes)
    result = check(aligned(hexes), eligibility=grid, confidence_bands=trusted(hexes))

    assert result.specification("additive").name == "additive"
    assert result.indicator("E1").indicator == "E1"
    with pytest.raises(KeyError):
        result.specification("geometric_mean")
    with pytest.raises(KeyError):
        result.indicator("E9")
