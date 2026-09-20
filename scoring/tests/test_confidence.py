"""Methodology section 12, and the two exclusions it is not willing to advise.

Every expected number here is worked out from the formulas in section 12 and
the arithmetic is written above it. The geometric mean is the part most likely
to be quietly replaced with an arithmetic one by someone who finds it surprising,
so it is tested against the case that distinguishes them rather than against
itself.
"""

import math
from datetime import date

import pytest

from burden.confidence import (
    DOCUMENTABLE_FLOOR,
    HEX_AREA_KM2,
    INDICATOR_WEIGHT,
    RECENCY_TAU_YEARS,
    TERM_FLOOR,
    TERM_WEIGHTS,
    TOTAL_INDICATOR_WEIGHT,
    HexConfidence,
    HexEvidence,
    InsufficientConfidence,
    assert_documentable,
    band_for,
    confidence,
    confidence_for_run,
    for_validation,
    low_confidence,
)

ALL_FIFTEEN = frozenset(INDICATOR_WEIGHT)
RUN_DATE = date(2026, 9, 11)
FRESH = dict.fromkeys(ALL_FIFTEEN, RUN_DATE)


def perfect(h3: str = "h0", **overrides: object) -> HexEvidence:
    """A hex nothing is wrong with, so a test can spoil exactly one thing."""
    defaults: dict[str, object] = {
        "h3": h3,
        "observed_indicators": ALL_FIFTEEN,
        "high_cv_population_share": 0.0,
        "mean_block_area_km2": 0.1,
        "nearest_monitor_km": 1.0,
    }
    defaults.update(overrides)
    return HexEvidence(**defaults)  # type: ignore[arg-type]


def scored(evidence: HexEvidence, vintages: dict[str, date] | None = None) -> HexConfidence:
    # `is None` rather than a truth test: an empty vintage map is a real case
    # this file tests, not a caller asking for the default.
    return confidence(evidence, vintages=FRESH if vintages is None else vintages, as_of=RUN_DATE)


# ---- the weights section 12 prints ---------------------------------------


def test_the_four_term_weights_are_the_ones_in_the_table() -> None:
    assert TERM_WEIGHTS == {
        "coverage": 0.35,
        "recency": 0.20,
        "spatial": 0.25,
        "monitor": 0.20,
    }
    assert math.isclose(sum(TERM_WEIGHTS.values()), 1.0)


def test_each_term_is_floored_at_five_hundredths() -> None:
    assert TERM_FLOOR == 0.05


def test_a_fully_supported_hex_scores_one() -> None:
    # Every term at its maximum, so the geometric mean is 1.0 and the band is
    # high. Section 12 asks for this to be computed rather than assumed, because
    # a map with confidence on some hexes and not others cannot be read.
    row = scored(perfect())

    assert row.value == pytest.approx(1.0)
    assert row.band == "high"
    assert (row.c_coverage, row.c_recency, row.c_spatial, row.c_monitor) == (1.0, 1.0, 1.0, 1.0)


# ---- c_coverage ----------------------------------------------------------


def test_coverage_weights_each_indicator_as_section_ten_weights_its_group() -> None:
    # Four Exposures at 1.0, four Environmental Effects at 0.5, two Sensitive at
    # 1.0 and five Socioeconomic at 1.0 comes to 13.0.
    assert TOTAL_INDICATOR_WEIGHT == pytest.approx(13.0)
    assert INDICATOR_WEIGHT["E1"] == 1.0
    assert INDICATOR_WEIGHT["F1"] == 0.5


def test_losing_an_exposures_indicator_costs_twice_what_losing_an_effects_one_does() -> None:
    # 12.0 / 13.0 against 12.5 / 13.0. The ratio is section 10's, not a second
    # opinion about which indicators matter.
    without_e1 = scored(perfect(observed_indicators=ALL_FIFTEEN - {"E1"}))
    without_f1 = scored(perfect(observed_indicators=ALL_FIFTEEN - {"F1"}))

    assert without_e1.c_coverage == pytest.approx(12.0 / 13.0)
    assert without_f1.c_coverage == pytest.approx(12.5 / 13.0)


def test_a_hex_with_nothing_observed_falls_to_the_floor() -> None:
    row = scored(perfect(observed_indicators=frozenset()))

    assert row.c_coverage == TERM_FLOOR


# ---- c_recency -----------------------------------------------------------


def test_recency_decays_by_exp_minus_age_over_tau() -> None:
    # Every vintage exactly four years old, so Δt / τ is 1 and the term is
    # exp(-1), about 0.368.
    four_years_ago = date(2022, 9, 11)
    row = scored(perfect(), vintages=dict.fromkeys(ALL_FIFTEEN, four_years_ago))

    assert row.c_recency == pytest.approx(math.exp(-1.0), rel=1e-3)


def test_tau_is_four_years() -> None:
    assert RECENCY_TAU_YEARS == 4.0


def test_recency_is_measured_against_the_vintage_not_the_pull() -> None:
    # The same run, pulled today either way. One read a release from 2018 and
    # one read a release from this year, and they must not come out the same.
    # Downloading an old dataset this morning does not make it a new one.
    stale = scored(perfect(), vintages=dict.fromkeys(ALL_FIFTEEN, date(2018, 9, 11)))
    current = scored(perfect(), vintages=FRESH)

    assert stale.c_recency < current.c_recency
    assert current.c_recency == pytest.approx(1.0)


def test_the_age_is_weighted_by_the_same_indicator_weights() -> None:
    # Section 12 calls it the weighted mean age. Only E1 is observed and it is
    # eight years old, so Δt is 8 and the term is exp(-2).
    vintages = {**FRESH, "E1": date(2018, 9, 11)}
    row = scored(perfect(observed_indicators=frozenset({"E1"})), vintages=vintages)

    assert row.c_recency == pytest.approx(math.exp(-2.0), rel=1e-3)


def test_an_indicator_with_no_recorded_vintage_does_not_count_as_fresh() -> None:
    # It drops out of the mean rather than being dated today, on the same terms
    # section 11 drops a missing indicator rather than imputing one.
    row = scored(perfect(observed_indicators=frozenset({"E1", "E2"})), vintages={"E1": RUN_DATE})

    assert row.c_recency == pytest.approx(1.0)


def test_a_hex_whose_contributors_carry_no_vintage_at_all_falls_to_the_floor() -> None:
    # The age of the score is unknown, and unknown is not fresh.
    row = scored(perfect(), vintages={})

    assert row.c_recency == TERM_FLOOR


def test_a_vintage_dated_after_the_run_is_treated_as_current_not_as_a_bonus() -> None:
    # A clock problem upstream should not be able to push a term above 1.
    row = scored(perfect(), vintages=dict.fromkeys(ALL_FIFTEEN, date(2030, 1, 1)))

    assert row.c_recency == pytest.approx(1.0)


# ---- c_spatial -----------------------------------------------------------


def test_spatial_support_falls_with_the_high_cv_share() -> None:
    # Half the hex's population drawn from ACS estimates with a CV over 0.30,
    # and blocks smaller than the hex, so 0.5 * 1 = 0.5.
    row = scored(perfect(high_cv_population_share=0.5))

    assert row.c_spatial == pytest.approx(0.5)


def test_spatial_support_falls_with_the_source_block_size() -> None:
    # Blocks ten times the hex's own area, so the dasymetric step is spreading
    # one number across ten cells' worth of ground: min(1, 0.737 / 7.37) = 0.1.
    row = scored(perfect(mean_block_area_km2=HEX_AREA_KM2 * 10))

    assert row.c_spatial == pytest.approx(0.1)


def test_blocks_no_larger_than_the_hex_support_it_fully() -> None:
    assert scored(perfect(mean_block_area_km2=HEX_AREA_KM2)).c_spatial == pytest.approx(1.0)
    assert scored(perfect(mean_block_area_km2=0.01)).c_spatial == pytest.approx(1.0)


def test_a_hex_with_no_block_record_falls_to_the_floor() -> None:
    # The interpolation cannot say what it drew on. That is a reason to trust
    # the number less, not a reason to assume the best.
    assert scored(perfect(mean_block_area_km2=None)).c_spatial == TERM_FLOOR


@pytest.mark.parametrize("bad", [-0.1, 1.5, math.nan])
def test_a_share_that_is_not_a_share_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="not a share"):
        scored(perfect(high_cv_population_share=bad))


@pytest.mark.parametrize("bad", [0.0, -1.0, math.inf])
def test_a_block_area_that_is_not_an_area_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="not an area"):
        scored(perfect(mean_block_area_km2=bad))


# ---- c_monitor -----------------------------------------------------------


def test_monitor_support_is_ten_kilometres_over_the_distance() -> None:
    # min(1, 10 / 40) = 0.25.
    assert scored(perfect(nearest_monitor_km=40.0)).c_monitor == pytest.approx(0.25)


def test_a_monitor_inside_ten_kilometres_is_full_support() -> None:
    assert scored(perfect(nearest_monitor_km=10.0)).c_monitor == pytest.approx(1.0)
    assert scored(perfect(nearest_monitor_km=0.0)).c_monitor == pytest.approx(1.0)


def test_no_monitor_anywhere_falls_to_the_floor_rather_than_dividing_by_nothing() -> None:
    row = scored(perfect(nearest_monitor_km=None))

    assert row.c_monitor == TERM_FLOOR
    assert row.nearest_monitor_km is None


def test_a_negative_distance_is_refused() -> None:
    with pytest.raises(ValueError, match="not a distance"):
        scored(perfect(nearest_monitor_km=-5.0))


# ---- the geometric mean --------------------------------------------------


def test_one_deficient_term_is_not_averaged_away_by_three_healthy_ones() -> None:
    # Section 12's own example: excellent coverage, recency and spatial support
    # but no monitor within 100 km. The arithmetic mean would be
    # 0.35 + 0.20 + 0.25 + 0.20 * 0.1 = 0.82, comfortably in the high band. The
    # geometric mean is 1 * 1 * 1 * 0.1^0.2, about 0.63, which is moderate. That
    # difference is the whole reason section 12 chose the geometric one.
    row = scored(perfect(nearest_monitor_km=100.0))

    assert row.c_monitor == pytest.approx(0.1)
    assert row.value == pytest.approx(0.1**0.2, rel=1e-9)
    assert row.value == pytest.approx(0.631, abs=0.001)
    assert row.band == "moderate"


def test_the_combination_is_the_weighted_product_of_the_four_terms() -> None:
    # Exactly one term spoiled, so the exponent is readable. Spatial at 0.5 and
    # the other three at 1 gives 1^0.35 * 1^0.20 * 0.5^0.25 * 1^0.20 = 0.5^0.25,
    # about 0.841. A term moves the value only by its own weight.
    row = scored(perfect(high_cv_population_share=0.5))

    assert row.c_spatial == pytest.approx(0.5)
    assert row.value == pytest.approx(0.5**0.25)
    assert row.value == pytest.approx(0.841, abs=0.001)


def test_the_floor_stops_one_zero_annihilating_the_product() -> None:
    # Every term at its worst. Without the floor the product would be exactly
    # zero and the other three terms' information would be gone; with it the
    # value is small but still ordered against other bad hexes.
    row = scored(
        perfect(
            observed_indicators=frozenset(),
            mean_block_area_km2=None,
            nearest_monitor_km=None,
        ),
        vintages={},
    )

    assert row.value == pytest.approx(TERM_FLOOR)
    assert row.value > 0.0
    assert row.band == "insufficient"


def test_confidence_never_leaves_the_interval_the_column_allows() -> None:
    # hex_score.confidence is CHECK (confidence > 0 AND confidence <= 1).
    cases = [
        perfect(),
        perfect(nearest_monitor_km=None),
        perfect(observed_indicators=frozenset({"E1"})),
        perfect(high_cv_population_share=1.0),
        perfect(mean_block_area_km2=500.0),
    ]

    for evidence in cases:
        row = scored(evidence)
        assert 0.0 < row.value <= 1.0


# ---- the bands -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "high"),
        (0.80, "high"),
        (0.799, "moderate"),
        (0.60, "moderate"),
        (0.599, "low"),
        (0.40, "low"),
        (0.399, "insufficient"),
        (0.05, "insufficient"),
    ],
)
def test_the_bands_are_section_twelves(value: float, expected: str) -> None:
    assert band_for(value) == expected


def test_the_printed_ranges_are_half_open_intervals() -> None:
    # Section 12 prints moderate as "0.60 - 0.79", which is a two-decimal
    # rendering. A hex at 0.795 is moderate, not stranded between two bands.
    assert band_for(0.795) == "moderate"
    assert band_for(0.595) == "low"


# ---- section 12's two exclusions, enforced rather than advised -----------


def test_the_documentable_floor_is_the_insufficient_boundary() -> None:
    assert DOCUMENTABLE_FLOOR == 0.40


def test_an_insufficient_hex_is_not_in_the_validation_sample() -> None:
    # Returned as a sample the hex is already out of, rather than a predicate a
    # caller has to remember. A validation result resting on a score the same
    # document says is unreliable would prove nothing.
    rows = (
        HexConfidence("good", 0.9, "high", 1.0, 1.0, 1.0, 1.0, 2.0),
        HexConfidence("thin", 0.2, "insufficient", 0.2, 1.0, 1.0, 1.0, 90.0),
        HexConfidence("weak", 0.45, "low", 0.5, 1.0, 1.0, 1.0, 30.0),
    )

    assert [row.h3 for row in for_validation(rows)] == ["good", "weak"]


def test_an_insufficient_hex_cannot_produce_a_document() -> None:
    # It raises rather than returning false. Section 12: producing a cited
    # complaint from a score the system does not itself trust would be the most
    # damaging thing this tool could do.
    thin = HexConfidence("thin", 0.2, "insufficient", 0.2, 1.0, 1.0, 1.0, 90.0)

    with pytest.raises(InsufficientConfidence, match="insufficient confidence band"):
        assert_documentable(thin)


def test_a_low_but_not_insufficient_hex_may_still_produce_a_document() -> None:
    # Low leads its panel with the caveat; it is not barred. Over-barring would
    # be its own failure, since section 12 gives the two bands different
    # treatments on purpose.
    weak = HexConfidence("weak", 0.45, "low", 0.5, 1.0, 1.0, 1.0, 30.0)

    assert_documentable(weak)
    assert weak.documentable is True


def test_the_low_confidence_sweep_returns_both_bottom_bands_worst_first() -> None:
    rows = (
        HexConfidence("good", 0.9, "high", 1.0, 1.0, 1.0, 1.0, 2.0),
        HexConfidence("weak", 0.45, "low", 0.5, 1.0, 1.0, 1.0, 30.0),
        HexConfidence("thin", 0.2, "insufficient", 0.2, 1.0, 1.0, 1.0, 90.0),
        HexConfidence("fine", 0.7, "moderate", 0.8, 1.0, 1.0, 1.0, 12.0),
    )

    assert [row.h3 for row in low_confidence(rows)] == ["thin", "weak"]


# ---- over a whole run ----------------------------------------------------


def test_every_hex_gets_one_including_the_fully_covered_ones() -> None:
    rows = confidence_for_run(
        [perfect("hB"), perfect("hA", nearest_monitor_km=None)],
        vintages=FRESH,
        as_of=RUN_DATE,
    )

    assert list(rows) == ["hA", "hB"]
    assert rows["hB"].value == pytest.approx(1.0)
    assert rows["hA"].band != "high"


def test_the_terms_are_kept_not_only_the_combined_value() -> None:
    # "This hex is at 0.42" is not actionable. "This hex is at 0.42 because the
    # nearest monitor is 90 km away" is, and the panel renders the second.
    row = scored(perfect(nearest_monitor_km=90.0))

    assert row.nearest_monitor_km == 90.0
    assert row.c_monitor < row.c_coverage
