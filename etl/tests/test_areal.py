"""Methodology section 13.5: the interpolation section 7 rejected, checked by hand.

The fixture is `tests/test_dasymetric.py`'s, reused deliberately. That fixture
was built so the two weightings visibly disagree — tract T1's people split
0.4375 / 0.5625 between the hexes while its area splits 0.5 / 0.5 — which makes
it the case where an areal counterpart that quietly reproduced the dasymetric
answer would be caught rather than flattered.

Every expected number below is derived on paper in the comment beside it, for the
reason section 7's own tests give: the failure this code could have is a
plausible wrong number, and only an independently derived expectation catches
one.
"""

import pytest

from pipeline.dasymetric import (
    BlockOverlap,
    Crosswalk,
    Kind,
    TractEstimate,
    TractHexWeight,
    areal_counterpart,
    build_crosswalk,
    crosswalk_from_weights,
    divergence,
    interpolate_extensive,
    interpolate_intensive,
    reconcile_population,
    tract_populations,
)
from pipeline.dasymetric.areal import PartialCrosswalk
from tests.test_dasymetric import BLOCK_A, BLOCK_B, FIXTURE, H1, H2, T1, T2, weight


@pytest.fixture
def dasymetric() -> Crosswalk:
    return build_crosswalk(FIXTURE)


@pytest.fixture
def areal(dasymetric: Crosswalk) -> Crosswalk:
    return areal_counterpart(dasymetric)


# ---- the counterfactual weights ----------------------------------------


def test_the_extensive_weight_becomes_the_area_share(
    dasymetric: Crosswalk, areal: Crosswalk
) -> None:
    # This is the whole substitution. T1's area splits evenly between the two
    # hexes, so simple areal weighting apportions its counts evenly, where the
    # block layer sends 43.75 percent one way and 56.25 percent the other.
    assert weight(dasymetric, T1, H1).pop_weight == pytest.approx(0.4375)
    assert weight(areal, T1, H1).pop_weight == pytest.approx(0.5)
    assert weight(areal, T1, H2).pop_weight == pytest.approx(0.5)


def test_the_population_column_still_holds_people(areal: Crosswalk) -> None:
    # P(t) * area share, not an area. T1 holds 400 people and its area splits
    # evenly, so 200 land in each hex. Section 5 reads this column against a
    # 25-person threshold, and a square metre in it would be a silent unit bug
    # in the one place the two methods most visibly disagree.
    assert weight(areal, T1, H1).population == pytest.approx(200.0)
    assert weight(areal, T1, H2).population == pytest.approx(200.0)
    # T2's single block lies wholly in H2, so both methods agree about it.
    assert weight(areal, T2, H2).population == pytest.approx(200.0)


def test_the_hex_population_differs_from_the_dasymetric_one(
    dasymetric: Crosswalk, areal: Crosswalk
) -> None:
    # Dasymetric: H1 holds 175 of T1's people, H2 holds 225 plus T2's 200.
    assert dasymetric.population(H1) == pytest.approx(175.0)
    assert dasymetric.population(H2) == pytest.approx(425.0)
    # Areal: H1 holds 200, H2 holds 200 plus T2's 200.
    assert areal.population(H1) == pytest.approx(200.0)
    assert areal.population(H2) == pytest.approx(400.0)


def test_every_row_is_marked_as_an_area_share(areal: Crosswalk) -> None:
    # The flag already means "this weight is an area share rather than a
    # population share", so a consumer that distinguishes the two needs nothing
    # new to check.
    assert all(row.pop_weight_from_area for row in areal.weights)


def test_the_tract_total_is_conserved(dasymetric: Crosswalk, areal: Crosswalk) -> None:
    # The comparison is only fair if both methods place the same people. They
    # differ in where the people go, never in how many there are, which is what
    # makes a divergence attributable to the ancillary layer rather than to one
    # method losing residents.
    assert tract_populations(areal) == pytest.approx(dict(tract_populations(dasymetric)))


def test_the_statewide_reconciliation_closes_for_both(
    dasymetric: Crosswalk, areal: Crosswalk
) -> None:
    # Section 7's reconciliation is an identity under either weighting, so a
    # failure here would be a defect in this module rather than a property of
    # areal interpolation.
    tracts = {T1: 400.0, T2: 200.0}
    estimates = [
        TractEstimate(T1, "TOTAL_POP", 400.0, None, Kind.EXTENSIVE),
        TractEstimate(T2, "TOTAL_POP", 200.0, None, Kind.EXTENSIVE),
    ]
    for crosswalk in (dasymetric, areal):
        interpolated = interpolate_extensive(crosswalk, estimates).values()
        assert reconcile_population(tracts, interpolated, crosswalk=crosswalk).ok


def test_the_geometry_columns_are_untouched(dasymetric: Crosswalk, areal: Crosswalk) -> None:
    # Which blocks a hex was built from is a fact about the grid, not about
    # which weighting reads it, so the c_spatial term of section 12 describes
    # the same cell under both methods.
    for left, right in zip(dasymetric.weights, areal.weights, strict=True):
        assert (left.tract_geoid, left.h3) == (right.tract_geoid, right.h3)
        assert left.block_count == right.block_count
        assert left.mean_block_area_m2 == right.mean_block_area_m2
        assert left.area_weight == right.area_weight


# ---- what it does to an interpolated value -----------------------------


def test_an_extensive_count_is_apportioned_by_area(dasymetric: Crosswalk, areal: Crosswalk) -> None:
    estimates = [TractEstimate(T1, "P2", 800.0, None, Kind.EXTENSIVE)]

    # 800 * 0.4375 = 350 against 800 * 0.5 = 400. Fifty people in poverty move
    # hexagon purely because the ancillary layer was taken away.
    assert interpolate_extensive(dasymetric, estimates)[H1].value == pytest.approx(350.0)
    assert interpolate_extensive(areal, estimates)[H1].value == pytest.approx(400.0)


def test_an_intensive_rate_is_weighted_by_the_areal_population(
    dasymetric: Crosswalk, areal: Crosswalk
) -> None:
    estimates = [
        TractEstimate(T1, "E1", 10.0, None, Kind.INTENSIVE),
        TractEstimate(T2, "E1", 20.0, None, Kind.INTENSIVE),
    ]

    # H2 is where the two tracts meet, so it is where the weighting shows.
    #   dasymetric: (10 * 225 + 20 * 200) / 425 = 6250 / 425 = 14.7058823...
    #   areal:      (10 * 200 + 20 * 200) / 400 = 6000 / 400 = 15.0
    assert interpolate_intensive(dasymetric, estimates)[H2].value == pytest.approx(6250.0 / 425.0)
    assert interpolate_intensive(areal, estimates)[H2].value == pytest.approx(15.0)


def test_a_hex_covered_by_one_tract_is_unaffected(dasymetric: Crosswalk, areal: Crosswalk) -> None:
    # A rate over a hex with a single contributing tract is that tract's rate
    # under any weighting, because the weights normalize to 1 either way. Worth
    # stating: it means a divergence reported by section 13.5 comes from hexes
    # that straddle a tract boundary, which is where the uniformity assumption
    # of section 7 is what is actually being tested.
    estimates = [TractEstimate(T1, "E1", 10.0, None, Kind.INTENSIVE)]
    assert interpolate_intensive(dasymetric, estimates)[H1].value == pytest.approx(10.0)
    assert interpolate_intensive(areal, estimates)[H1].value == pytest.approx(10.0)


# ---- the divergence report ---------------------------------------------


def test_divergence_is_signed_and_sums_to_nothing(dasymetric: Crosswalk, areal: Crosswalk) -> None:
    gaps = divergence(dasymetric, areal)

    # Areal weighting puts 25 more people in H1 and 25 fewer in H2. The sign is
    # the direction section 7 opens by describing, and the two must cancel
    # because neither method invents a resident.
    assert gaps[H1] == pytest.approx(25.0)
    assert gaps[H2] == pytest.approx(-25.0)
    assert sum(gaps.values()) == pytest.approx(0.0)


# ---- what it refuses ----------------------------------------------------


def test_a_partial_crosswalk_is_refused_rather_than_renormalized() -> None:
    # Half of tract T1 loaded. Renormalizing would spread all 400 of T1's people
    # across the one hex that happened to be present and report it as a property
    # of areal interpolation, when it is a loading bug.
    partial = crosswalk_from_weights(
        [
            TractHexWeight(
                tract_geoid=T1,
                h3=H1,
                population=175.0,
                pop_weight=0.4375,
                area_weight=0.5,
                block_count=2,
                mean_block_area_m2=150.0,
            )
        ]
    )

    with pytest.raises(PartialCrosswalk, match="not the whole tract"):
        areal_counterpart(partial)


def test_a_crosswalk_read_back_from_storage_behaves_the_same(dasymetric: Crosswalk) -> None:
    # The production path reads `tract_hex_weight` rather than rebuilding, so
    # the counterpart has to be derivable from stored rows alone.
    restored = crosswalk_from_weights(dasymetric.weights)
    assert areal_counterpart(restored).weights == areal_counterpart(dasymetric).weights


def test_a_tract_with_no_block_population_apportions_nothing(dasymetric: Crosswalk) -> None:
    # `build_crosswalk` already falls back to area share for such a tract, per
    # its own comment, so both weightings agree and the counterpart adds no
    # divergence of its own. Zero people spread by area is still zero people.
    empty = build_crosswalk(
        [
            BlockOverlap(BLOCK_A, T1, H1, 0, 100.0, 100.0),
            BlockOverlap(BLOCK_B, T1, H2, 0, 200.0, 200.0),
        ]
    )
    counterpart = areal_counterpart(empty)

    assert all(row.population == pytest.approx(0.0) for row in counterpart.weights)
    assert divergence(empty, counterpart) == pytest.approx({H1: 0.0, H2: 0.0})
