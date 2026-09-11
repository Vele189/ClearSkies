"""Methodology section 7, checked against a case small enough to do by hand.

The fixture below is two tracts, three blocks and two hexagons, chosen so that
every number in these tests can be recomputed on paper. The arithmetic is
written out in the comments beside each assertion rather than left implicit,
because the failure this module exists to prevent is a plausible wrong number,
and a plausible wrong number is only caught by a test whose expected value was
derived independently of the code.

The fixture's shape is the point of the whole ticket. Tract T1's population
weights are 0.4375 and 0.5625 while its area weights are 0.5 and 0.5. A naive
areal interpolation would put half of T1's people in each hexagon. The
dasymetric one puts 43.75 percent in the first and 56.25 percent in the second,
because that is where T1's 2020 block population actually sits.
"""

import math

import pytest

from pipeline.dasymetric import (
    ACS_MOE_Z,
    BlockOverlap,
    Crosswalk,
    HexValue,
    Kind,
    KindMismatch,
    TractEstimate,
    TractHexWeight,
    build_crosswalk,
    coefficient_of_variation,
    combine_in_quadrature,
    crosswalk_from_weights,
    derive_rate,
    interpolate,
    interpolate_extensive,
    interpolate_intensive,
    max_coefficient_variation,
    proportion_moe,
    reconcile_crosswalk,
    reconcile_population,
    require,
)
from pipeline.dasymetric.reconcile import ReconciliationFailed

T1 = "22001000100"
T2 = "22001000200"
H1 = "8844c0b301fffff"
H2 = "8844c0b303fffff"

# Tract T1, two blocks:
#   block A  population 100, area 100, lies entirely in H1
#   block B  population 300, area 200, one quarter in H1 and three quarters in H2
# Tract T2, one block:
#   block C  population 200, area 100, lies entirely in H2
#
# By hand, from the section 7 formula P(t n h) = sum of P(b) * area(b n h)/area(b):
#   P(T1 n H1) = 100 * (100/100) + 300 * (50/200)  = 100 + 75  = 175
#   P(T1 n H2) =                   300 * (150/200) =        225 = 225
#   P(T1)      = 400,  so pop_weight = 175/400 = 0.4375 and 225/400 = 0.5625
#   area(T1)   = 300,  so area_weight = 150/300 = 0.5 and 150/300 = 0.5
BLOCK_A = "220010001001000"
BLOCK_B = "220010001001001"
BLOCK_C = "220010002001000"

FIXTURE = [
    BlockOverlap(BLOCK_A, T1, H1, 100, 100.0, 100.0),
    BlockOverlap(BLOCK_B, T1, H1, 300, 200.0, 50.0),
    BlockOverlap(BLOCK_B, T1, H2, 300, 200.0, 150.0),
    BlockOverlap(BLOCK_C, T2, H2, 200, 100.0, 100.0),
]


@pytest.fixture
def crosswalk() -> Crosswalk:
    return build_crosswalk(FIXTURE)


def weight(crosswalk: Crosswalk, tract: str, h3: str) -> TractHexWeight:
    (row,) = [w for w in crosswalk.for_tract(tract) if w.h3 == h3]
    return row


# --- section 7 steps 1 and 2: the crosswalk ------------------------------


def test_population_weights_follow_the_blocks_not_the_area(crosswalk: Crosswalk) -> None:
    # The whole reason section 7 uses an ancillary layer. T1's area splits
    # evenly between the two hexes; its people do not.
    assert weight(crosswalk, T1, H1).pop_weight == pytest.approx(0.4375)
    assert weight(crosswalk, T1, H2).pop_weight == pytest.approx(0.5625)
    assert weight(crosswalk, T1, H1).area_weight == pytest.approx(0.5)
    assert weight(crosswalk, T1, H2).area_weight == pytest.approx(0.5)


def test_overlap_populations_are_the_block_apportioned_counts(crosswalk: Crosswalk) -> None:
    assert weight(crosswalk, T1, H1).population == pytest.approx(175.0)
    assert weight(crosswalk, T1, H2).population == pytest.approx(225.0)
    assert weight(crosswalk, T2, H2).population == pytest.approx(200.0)


def test_a_tracts_weights_sum_to_one(crosswalk: Crosswalk) -> None:
    # This is the identity the statewide reconciliation rests on.
    for tract in (T1, T2):
        rows = crosswalk.for_tract(tract)
        assert math.fsum(row.pop_weight for row in rows) == pytest.approx(1.0)
        assert math.fsum(row.area_weight for row in rows) == pytest.approx(1.0)


def test_hex_population_sums_over_every_tract_that_reaches_it(crosswalk: Crosswalk) -> None:
    assert crosswalk.population(H1) == pytest.approx(175.0)  # T1 only
    assert crosswalk.population(H2) == pytest.approx(425.0)  # 225 from T1, 200 from T2


def test_block_counts_and_mean_block_area_are_recorded(crosswalk: Crosswalk) -> None:
    # H1 draws on blocks A and B: (100 + 200) / 2 = 150.
    assert weight(crosswalk, T1, H1).block_count == 2
    assert weight(crosswalk, T1, H1).mean_block_area_m2 == pytest.approx(150.0)
    assert weight(crosswalk, T1, H2).block_count == 1
    assert weight(crosswalk, T1, H2).mean_block_area_m2 == pytest.approx(200.0)


def test_mean_block_area_per_hex_is_population_weighted(crosswalk: Crosswalk) -> None:
    # Section 7's uniformity error matters in proportion to the people it
    # misplaces. H2: (200 * 225 + 100 * 200) / 425 = 65000 / 425.
    assert crosswalk.mean_block_area_m2(H2) == pytest.approx(65000.0 / 425.0)
    assert crosswalk.mean_block_area_m2(H1) == pytest.approx(150.0)


def test_the_crosswalk_reconciles_against_its_own_block_layer(crosswalk: Crosswalk) -> None:
    report = reconcile_crosswalk(crosswalk)
    assert report.ok
    assert report.tract_total == pytest.approx(600.0)  # 100 + 300 + 200
    assert report.hex_total == pytest.approx(600.0)


def test_a_stored_crosswalk_behaves_like_a_freshly_built_one(crosswalk: Crosswalk) -> None:
    restored = crosswalk_from_weights(crosswalk.weights)
    assert restored.population(H2) == pytest.approx(crosswalk.population(H2))
    assert sorted(restored.hexes()) == sorted(crosswalk.hexes())


# --- extensive quantities: apportioned -----------------------------------


def counts(
    variable: str,
    t1_value: float | None,
    t2_value: float | None,
    t1_moe: float | None = None,
    t2_moe: float | None = None,
) -> list[TractEstimate]:
    return [
        TractEstimate(T1, variable, t1_value, t1_moe, Kind.EXTENSIVE),
        TractEstimate(T2, variable, t2_value, t2_moe, Kind.EXTENSIVE),
    ]


def test_counts_are_apportioned_through_the_population_weights(crosswalk: Crosswalk) -> None:
    # ACS says 440 people in T1 and 210 in T2. Note these differ from the 2020
    # block counts on purpose: the block layer is a distribution key, never a
    # source of values.
    #   H1 = 440 * 0.4375                 = 192.5
    #   H2 = 440 * 0.5625 + 210 * 1.0     = 247.5 + 210 = 457.5
    values = interpolate_extensive(crosswalk, counts("B01003_001E", 440.0, 210.0))
    assert values[H1].value == pytest.approx(192.5)
    assert values[H2].value == pytest.approx(457.5)


def test_the_statewide_total_survives_interpolation(crosswalk: Crosswalk) -> None:
    estimates = counts("B01003_001E", 440.0, 210.0)
    values = interpolate_extensive(crosswalk, estimates)
    report = reconcile_population({T1: 440.0, T2: 210.0}, values.values())
    assert report.ok
    assert report.hex_total == pytest.approx(650.0)
    assert report.residual == pytest.approx(0.0)
    assert require(report) is report


def test_margins_of_error_combine_in_quadrature(crosswalk: Crosswalk) -> None:
    # A dedicated crosswalk so the weights are exactly one half and the
    # quadrature sum is a 3-4-5 triangle:
    #   MOE = sqrt((0.5 * 6)^2 + (0.5 * 8)^2) = sqrt(9 + 16) = 5
    split = build_crosswalk(
        [
            BlockOverlap("b_a", "22001000300", H1, 100, 100.0, 50.0),
            BlockOverlap("b_a", "22001000300", H2, 100, 100.0, 50.0),
            BlockOverlap("b_b", "22001000400", H1, 100, 100.0, 50.0),
            BlockOverlap("b_b", "22001000400", H2, 100, 100.0, 50.0),
        ]
    )
    values = interpolate_extensive(
        split,
        [
            TractEstimate("22001000300", "V", 100.0, 6.0, Kind.EXTENSIVE),
            TractEstimate("22001000400", "V", 100.0, 8.0, Kind.EXTENSIVE),
        ],
    )
    assert values[H1].value == pytest.approx(100.0)
    assert values[H1].margin_of_error == pytest.approx(5.0)


def test_a_missing_margin_makes_the_hex_margin_unknown_not_smaller(crosswalk: Crosswalk) -> None:
    values = interpolate_extensive(crosswalk, counts("V", 440.0, 210.0, t1_moe=20.0))
    # T2 reported no margin, so quadrature over T1 alone would understate.
    assert values[H2].value == pytest.approx(457.5)
    assert values[H2].margin_of_error is None
    assert values[H2].coefficient_of_variation is None


def test_an_absent_estimate_is_not_a_zero(crosswalk: Crosswalk) -> None:
    # Section 11: a missing value is stored as missing, never imputed.
    values = interpolate_extensive(crosswalk, counts("V", None, 210.0))
    assert values[H1].value is None
    assert values[H1].present is False
    assert values[H1].contributing_tracts == 0
    # H2 still has T2, but only 200 of its 425 people are backed by an estimate.
    assert values[H2].value == pytest.approx(210.0)
    assert values[H2].population_support == pytest.approx(200.0 / 425.0)


def test_full_support_is_reported_when_every_tract_answers(crosswalk: Crosswalk) -> None:
    values = interpolate_extensive(crosswalk, counts("V", 440.0, 210.0))
    assert values[H2].population_support == pytest.approx(1.0)
    assert values[H2].contributing_tracts == 2


# --- intensive quantities: population-weighted mean ----------------------


def rates(
    variable: str,
    t1_value: float | None,
    t2_value: float | None,
    t1_moe: float | None = None,
    t2_moe: float | None = None,
) -> list[TractEstimate]:
    return [
        TractEstimate(T1, variable, t1_value, t1_moe, Kind.INTENSIVE),
        TractEstimate(T2, variable, t2_value, t2_moe, Kind.INTENSIVE),
    ]


def test_rates_are_averaged_over_population_not_summed(crosswalk: Crosswalk) -> None:
    # R(H2) = (20 * 225 + 25 * 200) / 425 = 9500 / 425 = 22.3529...
    values = interpolate_intensive(crosswalk, rates("E1", 20.0, 25.0))
    assert values[H2].value == pytest.approx(9500.0 / 425.0)
    # H1 is reached by T1 alone, so it takes T1's rate unchanged.
    assert values[H1].value == pytest.approx(20.0)


def test_intensive_margins_use_the_normalized_population_weights(crosswalk: Crosswalk) -> None:
    # Weights 225/425 and 200/425, margins 4 and 5:
    #   sqrt((225/425 * 4)^2 + (200/425 * 5)^2)
    values = interpolate_intensive(crosswalk, rates("E1", 20.0, 25.0, 4.0, 5.0))
    expected = math.sqrt((225 / 425 * 4) ** 2 + (200 / 425 * 5) ** 2)
    assert values[H2].margin_of_error == pytest.approx(expected)


def test_a_missing_rate_renormalizes_rather_than_dragging_the_mean_down(
    crosswalk: Crosswalk,
) -> None:
    values = interpolate_intensive(crosswalk, rates("E1", None, 25.0))
    # Not (0 * 225 + 25 * 200) / 425. T2's rate stands alone.
    assert values[H2].value == pytest.approx(25.0)
    assert values[H2].population_support == pytest.approx(200.0 / 425.0)


def test_an_unpopulated_hex_falls_back_to_area_weighting() -> None:
    empty = build_crosswalk(
        [
            BlockOverlap("b_x", T1, H1, 0, 100.0, 75.0),
            BlockOverlap("b_x", T1, H2, 0, 100.0, 25.0),
        ]
    )
    values = interpolate_intensive(empty, [TractEstimate(T1, "E1", 12.0, None, Kind.INTENSIVE)])
    assert values[H1].value == pytest.approx(12.0)
    # Zero support is how a caller tells that the weighting was areal.
    assert values[H1].population_support == pytest.approx(0.0)


# --- the rule about rates ------------------------------------------------


def test_a_derived_rate_matches_the_weighted_mean_when_the_denominators_agree(
    crosswalk: Crosswalk,
) -> None:
    # T1: 80 of 400 below 200 percent FPL. T2: 50 of 200. Both rates are the
    # tract's own numerator over its own denominator, and that denominator is
    # the population the intensive path weights by, so the two paths must
    # agree. When they stop agreeing, one of them has a bug.
    numerator = interpolate_extensive(crosswalk, counts("B17026_num", 80.0, 50.0))
    denominator = interpolate_extensive(crosswalk, counts("B17026_den", 400.0, 200.0))
    derived = derive_rate(numerator, denominator, variable="P1", scale=100.0)
    averaged = interpolate_intensive(crosswalk, rates("P1", 20.0, 25.0))

    assert numerator[H2].value == pytest.approx(95.0)  # 80*0.5625 + 50
    assert denominator[H2].value == pytest.approx(425.0)  # 400*0.5625 + 200
    assert derived[H2].value == pytest.approx(100.0 * 95.0 / 425.0)
    assert derived[H2].value == pytest.approx(averaged[H2].value)


def test_deriving_from_published_parts_beats_averaging_when_denominators_differ(
    crosswalk: Crosswalk,
) -> None:
    # Now T2 reports 50 of only 100 people whose poverty status was determined,
    # a 50 percent rate over half its population. The intensive path weights
    # that 50 percent by T2's *total* 200 people and overstates the hex; the
    # derived path uses the published denominator and does not. Section 7
    # prefers the derived path for exactly this reason.
    numerator = interpolate_extensive(crosswalk, counts("num", 80.0, 50.0))
    denominator = interpolate_extensive(crosswalk, counts("den", 400.0, 100.0))
    derived = derive_rate(numerator, denominator, variable="P1", scale=100.0)
    averaged = interpolate_intensive(crosswalk, rates("P1", 20.0, 50.0))

    assert denominator[H2].value == pytest.approx(325.0)  # 400*0.5625 + 100
    assert derived[H2].value == pytest.approx(100.0 * 95.0 / 325.0)  # 29.23 percent
    assert averaged[H2].value == pytest.approx(14500.0 / 425.0)  # 34.12 percent
    assert derived[H2].value != pytest.approx(averaged[H2].value)


def test_a_derived_rate_uses_the_census_proportion_formula(crosswalk: Crosswalk) -> None:
    numerator = interpolate_extensive(crosswalk, counts("num", 80.0, 50.0, 10.0, 8.0))
    denominator = interpolate_extensive(crosswalk, counts("den", 400.0, 200.0, 30.0, 20.0))
    derived = derive_rate(numerator, denominator, variable="P1", scale=100.0)

    top = numerator[H2]
    bottom = denominator[H2]
    assert top.value is not None and top.margin_of_error is not None
    assert bottom.value is not None and bottom.margin_of_error is not None
    expected, conservative = proportion_moe(
        top.value, top.margin_of_error, bottom.value, bottom.margin_of_error
    )
    assert derived[H2].margin_of_error == pytest.approx(100.0 * expected)
    assert derived[H2].moe_is_conservative is conservative


def test_a_zero_denominator_is_an_absent_rate_not_a_zero_rate(crosswalk: Crosswalk) -> None:
    numerator = interpolate_extensive(crosswalk, counts("num", 0.0, 0.0))
    denominator = interpolate_extensive(crosswalk, counts("den", 0.0, 0.0))
    derived = derive_rate(numerator, denominator, variable="P1", scale=100.0)
    assert derived[H2].value is None


def test_a_rate_cannot_be_derived_from_intensive_parts(crosswalk: Crosswalk) -> None:
    averaged = interpolate_intensive(crosswalk, rates("P1", 20.0, 25.0))
    with pytest.raises(KindMismatch):
        derive_rate(averaged, averaged, variable="P1")


# --- the two are never confused ------------------------------------------


def test_apportioning_a_rate_raises(crosswalk: Crosswalk) -> None:
    with pytest.raises(KindMismatch):
        interpolate_extensive(crosswalk, rates("E1", 20.0, 25.0))


def test_averaging_a_count_raises(crosswalk: Crosswalk) -> None:
    with pytest.raises(KindMismatch):
        interpolate_intensive(crosswalk, counts("B01003_001E", 440.0, 210.0))


def test_one_variable_cannot_arrive_as_both_kinds(crosswalk: Crosswalk) -> None:
    with pytest.raises(KindMismatch):
        interpolate(
            crosswalk,
            [
                TractEstimate(T1, "V", 1.0, None, Kind.EXTENSIVE),
                TractEstimate(T2, "V", 1.0, None, Kind.INTENSIVE),
            ],
        )


def test_the_dispatcher_sends_each_variable_down_its_own_path(crosswalk: Crosswalk) -> None:
    values = interpolate(
        crosswalk,
        [*counts("B01003_001E", 440.0, 210.0), *rates("E1", 20.0, 25.0)],
    )
    assert values["B01003_001E"][H2].value == pytest.approx(457.5)
    assert values["E1"][H2].value == pytest.approx(9500.0 / 425.0)


def test_a_tract_cannot_appear_twice_for_one_variable(crosswalk: Crosswalk) -> None:
    with pytest.raises(ValueError, match="appears twice"):
        interpolate_extensive(
            crosswalk,
            [
                TractEstimate(T1, "V", 1.0, None, Kind.EXTENSIVE),
                TractEstimate(T1, "V", 2.0, None, Kind.EXTENSIVE),
            ],
        )


def test_two_variables_cannot_share_one_call(crosswalk: Crosswalk) -> None:
    with pytest.raises(ValueError, match="one variable at a time"):
        interpolate_extensive(
            crosswalk,
            [
                TractEstimate(T1, "A", 1.0, None, Kind.EXTENSIVE),
                TractEstimate(T2, "B", 2.0, None, Kind.EXTENSIVE),
            ],
        )


# --- uncertainty ---------------------------------------------------------


def test_quadrature_is_the_root_sum_of_squares() -> None:
    assert combine_in_quadrature([3.0, 4.0]) == pytest.approx(5.0)
    assert combine_in_quadrature([]) == pytest.approx(0.0)


def test_the_coefficient_of_variation_uses_the_ninety_percent_z() -> None:
    # ACS publishes margins at 90 percent, so SE = MOE / 1.645. A margin of
    # 16.45 on an estimate of 100 is a standard error of 10 and a CV of 0.10.
    assert ACS_MOE_Z == 1.645
    assert coefficient_of_variation(100.0, 16.45) == pytest.approx(0.10)


def test_a_zero_estimate_has_no_coefficient_of_variation() -> None:
    # A zero count with a non-zero margin is a real ACS outcome. The honest
    # statement is that the ratio does not exist, not that it is infinite.
    assert coefficient_of_variation(0.0, 12.0) is None
    assert coefficient_of_variation(None, 12.0) is None
    assert coefficient_of_variation(50.0, None) is None


def test_a_high_coefficient_of_variation_is_flagged_and_kept() -> None:
    # Section 7: no threshold silently drops an estimate, because dropping
    # them preferentially removes small and rural populations.
    value = HexValue(
        h3=H1,
        variable="P3",
        kind=Kind.EXTENSIVE,
        value=100.0,
        margin_of_error=82.25,  # SE 50, CV 0.50
        coefficient_of_variation=coefficient_of_variation(100.0, 82.25),
        population_support=1.0,
        contributing_tracts=1,
    )
    assert value.coefficient_of_variation == pytest.approx(0.5)
    assert value.high_uncertainty
    assert value.present


def test_the_proportion_formula_subtracts_when_it_can() -> None:
    # X = 25 +/- 15, Y = 100 +/- 20, P = 0.25:
    #   sqrt(15^2 - 0.25^2 * 20^2) / 100 = sqrt(225 - 25) / 100 = sqrt(200)/100
    moe, conservative = proportion_moe(25.0, 15.0, 100.0, 20.0)
    assert moe == pytest.approx(math.sqrt(200.0) / 100.0)
    assert conservative is False


def test_the_proportion_formula_falls_back_to_the_ratio_formula() -> None:
    # X = 25 +/- 4 gives 16 - 25 = -9 under the root, so the Bureau's ratio
    # formula applies instead: sqrt(16 + 25) / 100.
    moe, conservative = proportion_moe(25.0, 4.0, 100.0, 20.0)
    assert moe == pytest.approx(math.sqrt(41.0) / 100.0)
    assert conservative is True


def test_the_worst_coefficient_of_variation_is_what_the_hex_carries(crosswalk: Crosswalk) -> None:
    values = [
        HexValue(H1, "a", Kind.EXTENSIVE, 100.0, 16.45, 0.10, 1.0, 1),
        HexValue(H1, "b", Kind.EXTENSIVE, 100.0, 82.25, 0.50, 1.0, 1),
        HexValue(H1, "c", Kind.EXTENSIVE, 0.0, 12.0, None, 1.0, 1),
    ]
    assert max_coefficient_variation(values) == pytest.approx(0.50)
    assert max_coefficient_variation([]) is None


# --- edge cases in the crosswalk itself ----------------------------------


def test_clipping_slivers_are_normalized_away() -> None:
    # A block whose hex shares clip to 99.8 percent of its area is suffering
    # from polygon precision. Normalizing keeps its people in the state.
    nearly = build_crosswalk(
        [
            BlockOverlap("b_s", T1, H1, 100, 100.0, 49.9),
            BlockOverlap("b_s", T1, H2, 100, 100.0, 49.9),
        ]
    )
    assert nearly.population(H1) + nearly.population(H2) == pytest.approx(100.0)
    assert nearly.report.uncovered_blocks == ()


def test_a_block_over_a_hole_in_the_grid_is_reported_not_hidden() -> None:
    # Half the block's area found no hexagon. Normalizing still keeps the
    # arithmetic closed, but the block is named so a real grid defect cannot
    # be mistaken for rounding.
    holed = build_crosswalk([BlockOverlap("b_h", T1, H1, 100, 100.0, 50.0)])
    (reported,) = holed.report.uncovered_blocks
    assert reported.block_geoid == "b_h"
    assert reported.coverage == pytest.approx(0.5)


def test_a_block_touching_no_hexagon_leaves_its_population_unassigned() -> None:
    stranded = build_crosswalk(
        [
            BlockOverlap(BLOCK_A, T1, H1, 100, 100.0, 100.0),
            BlockOverlap(BLOCK_B, T1, H2, 300, 200.0, 0.0),
        ]
    )
    assert stranded.report.unassigned_population == 300
    # The block layer is genuinely short by those 300, and says so by name.
    blocks = reconcile_crosswalk(stranded)
    assert blocks.raw_difference == pytest.approx(-300.0)
    assert blocks.explained == pytest.approx(300.0)
    assert blocks.ok
    assert blocks.detail == (BLOCK_B,)

    # The ACS pass is not short, though. T1's surviving weights still sum to 1,
    # so its estimate lands in full over the covered part of the tract. What
    # was lost is spatial detail, not population.
    values = interpolate_extensive(stranded, [TractEstimate(T1, "V", 100.0, None, Kind.EXTENSIVE)])
    assert values[H1].value == pytest.approx(100.0)
    assert require(reconcile_population({T1: 100.0}, values.values(), crosswalk=stranded)).ok


def test_a_tract_the_crosswalk_never_reached_is_named_not_silently_lost(
    crosswalk: Crosswalk,
) -> None:
    # Every block of T3 fell outside the grid, so it produced no weights and
    # its estimate lands nowhere. Without the crosswalk that reads as a
    # failure; with it, the gap is attributed.
    values = interpolate_extensive(crosswalk, counts("V", 440.0, 210.0))
    claimed = {T1: 440.0, T2: 210.0, "22001000300": 75.0}

    blind = reconcile_population(claimed, values.values())
    assert not blind.ok

    attributed = reconcile_population(claimed, values.values(), crosswalk=crosswalk)
    assert attributed.ok
    assert attributed.explained == pytest.approx(75.0)
    assert attributed.detail == ("22001000300",)
    assert "never reached" in attributed.describe()


def test_a_tract_with_no_block_population_falls_back_to_area_share() -> None:
    # 2020 blocks and a 2019-2023 ACS vintage do not always agree. A tract the
    # ACS thinks holds people must still land somewhere, or the statewide total
    # will not close.
    empty = build_crosswalk(
        [
            BlockOverlap("b_e", T1, H1, 0, 100.0, 75.0),
            BlockOverlap("b_e", T1, H2, 0, 100.0, 25.0),
        ]
    )
    assert weight(empty, T1, H1).pop_weight == pytest.approx(0.75)
    assert weight(empty, T1, H1).pop_weight_from_area is True
    assert empty.report.area_fallback_tracts == (T1,)

    values = interpolate_extensive(empty, [TractEstimate(T1, "V", 40.0, None, Kind.EXTENSIVE)])
    assert values[H1].value == pytest.approx(30.0)
    assert require(reconcile_population({T1: 40.0}, values.values())).ok


def test_a_block_with_no_area_cannot_apportion_anything() -> None:
    with pytest.raises(ValueError, match="non-positive area"):
        build_crosswalk([BlockOverlap("b_z", T1, H1, 10, 0.0, 0.0)])


def test_a_negative_block_population_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative population"):
        build_crosswalk([BlockOverlap("b_n", T1, H1, -1, 100.0, 100.0)])


# --- reconciliation ------------------------------------------------------


def test_reconciliation_fails_loudly_when_the_totals_move(crosswalk: Crosswalk) -> None:
    values = interpolate_extensive(crosswalk, counts("V", 440.0, 210.0))
    # Claim a tract total the interpolation never saw.
    report = reconcile_population({T1: 440.0, T2: 999.0}, values.values())
    assert not report.ok
    with pytest.raises(ReconciliationFailed):
        require(report)
    assert "OUT OF TOLERANCE" in report.describe()


def test_the_tolerance_is_relative_and_documented(crosswalk: Crosswalk) -> None:
    values = interpolate_extensive(crosswalk, counts("V", 440.0, 210.0))
    # One person in ten million against a total of 650 is inside 1e-6 relative.
    report = reconcile_population({T1: 440.0, T2: 210.0 + 6.5e-5}, values.values())
    assert report.ok
    # A hundred times that is not.
    worse = reconcile_population({T1: 440.0, T2: 210.0 + 6.5e-3}, values.values())
    assert not worse.ok
