"""Methodology section 7, which is the step the paper says goes wrong most often.

The tests that matter here are the ones that would still pass if the formula were
subtly wrong, so each states the number it expects and where it comes from rather
than asserting that two implementations agree.
"""

from pipeline.interpolate import (
    Overlap,
    StaticCrosswalk,
    apportion,
    population_weighted_mean,
)
from pipeline.records import Measurement


def crosswalk(*overlaps: Overlap, hexes: tuple[str, ...] | None = None) -> StaticCrosswalk:
    cells = hexes if hexes is not None else tuple(dict.fromkeys(o.h3 for o in overlaps))
    return StaticCrosswalk(cells=cells, rows=overlaps)


def overlap(source: str, h3: str, population: float, pop_weight: float = 1.0) -> Overlap:
    return Overlap(source_id=source, h3=h3, population=population, pop_weight=pop_weight)


# ---- intensive: the population-weighted mean ----------------------------


def test_a_single_tract_hands_its_own_value_to_the_hex() -> None:
    values = {"t1": Measurement.of(40.0)}

    (result,), coverage = population_weighted_mean(values, crosswalk(overlap("t1", "h1", 900.0)))

    assert result.value == Measurement.of(40.0)
    assert result.source_count == 1
    assert result.population == 900.0
    assert coverage.observed == 1


def test_two_tracts_are_weighted_by_population_not_by_count() -> None:
    # 20 over 900 people and 60 over 100 gives (20*900 + 60*100) / 1000 = 24.
    # The unweighted mean would be 40, which is what an implementation that
    # forgot the weights would return.
    values = {"t1": Measurement.of(20.0), "t2": Measurement.of(60.0)}
    grid = crosswalk(overlap("t1", "h1", 900.0), overlap("t2", "h1", 100.0))

    (result,), _ = population_weighted_mean(values, grid)

    assert result.value.value == 24.0
    assert result.source_count == 2
    assert result.population == 1000.0


def test_area_is_never_consulted() -> None:
    """Two overlaps of identical area but very different population.

    Area share would give the midpoint, 50. Section 7 rejects that in its first
    paragraph: it would hand an unpopulated third of a rural tract the same
    weight as its town.
    """
    values = {"town": Measurement.of(90.0), "marsh": Measurement.of(10.0)}
    grid = crosswalk(
        # Equal pop_weight, which is the closest thing to an area share this
        # structure carries, and wildly unequal population.
        overlap("town", "h1", 4000.0, pop_weight=0.5),
        overlap("marsh", "h1", 0.0, pop_weight=0.5),
    )

    (result,), _ = population_weighted_mean(values, grid)

    assert result.value.value == 90.0


def test_an_absent_tract_leaves_the_denominator_as_well_as_the_numerator() -> None:
    """The rule that decides whether missing data biases the map.

    t2 reported nothing. Dropping it from the numerator alone would give
    (80*500) / 1500 = 26.7, which is imputing zero by arithmetic instead of by
    assignment and pulls a burdened hex toward the middle. Section 11 forbids it
    in exactly this direction.
    """
    values = {"t1": Measurement.of(80.0), "t2": Measurement.absent()}
    grid = crosswalk(overlap("t1", "h1", 500.0), overlap("t2", "h1", 1000.0))

    (result,), _ = population_weighted_mean(values, grid)

    assert result.value.value == 80.0
    assert result.source_count == 1
    assert result.population == 500.0


def test_a_tract_the_source_never_mentioned_is_treated_like_an_absent_one() -> None:
    values = {"t1": Measurement.of(80.0)}
    grid = crosswalk(overlap("t1", "h1", 500.0), overlap("missing", "h1", 1000.0))

    (result,), _ = population_weighted_mean(values, grid)

    assert result.value.value == 80.0
    assert result.source_count == 1


def test_zero_is_carried_through_as_an_observation() -> None:
    # A modeled risk of zero is a statement about the tract. Only Measurement
    # knows the difference, and this is the assertion that proves the mean does
    # not confuse the two.
    values = {"t1": Measurement.of(0.0), "t2": Measurement.of(100.0)}
    grid = crosswalk(overlap("t1", "h1", 500.0), overlap("t2", "h1", 500.0))

    (result,), coverage = population_weighted_mean(values, grid)

    assert result.value == Measurement.of(50.0)
    assert coverage.absent == 0


# ---- absence, counted ---------------------------------------------------


def test_every_hex_in_the_universe_comes_back_with_an_answer() -> None:
    """CS-103: a value or an explicit, counted absence. Never a shorter list."""
    values = {"t1": Measurement.of(40.0)}
    grid = crosswalk(overlap("t1", "h1", 900.0), hexes=("h1", "h2", "h3"))

    results, coverage = population_weighted_mean(values, grid)

    assert [r.h3 for r in results] == ["h1", "h2", "h3"]
    assert coverage.hexes == 3
    assert coverage.observed == 1
    assert coverage.absent == 2


def test_a_hex_with_no_overlapping_tract_says_so() -> None:
    grid = crosswalk(overlap("t1", "h1", 900.0), hexes=("h1", "h2"))

    results, coverage = population_weighted_mean({"t1": Measurement.of(1.0)}, grid)

    assert results[1].absence == "no_overlapping_source"
    assert results[1].value == Measurement.absent()
    assert coverage.absences == {"no_overlapping_source": 1}


def test_a_hex_whose_tracts_all_reported_nothing_says_so_differently() -> None:
    values = {"t1": Measurement.absent()}
    grid = crosswalk(overlap("t1", "h1", 900.0))

    (result,), coverage = population_weighted_mean(values, grid)

    assert result.absence == "no_source_value"
    assert coverage.absences == {"no_source_value": 1}


def test_an_unpopulated_hex_is_absent_rather_than_area_averaged() -> None:
    """The mean is undefined here, and section 7 leaves no fallback that is legal.

    Averaging the two values unweighted, or by area, would be the area-averaging
    CS-103 rules out. Section 11 leaves unpopulated cells unscored anyway.
    """
    values = {"t1": Measurement.of(20.0), "t2": Measurement.of(60.0)}
    grid = crosswalk(overlap("t1", "h1", 0.0), overlap("t2", "h1", 0.0))

    (result,), coverage = population_weighted_mean(values, grid)

    assert result.value == Measurement.absent()
    assert result.absence == "no_population"
    assert coverage.absences == {"no_population": 1}


def test_tracts_that_reach_no_hex_are_counted_not_dropped() -> None:
    """The 2010-against-2020 census vintage mismatch, in miniature."""
    values = {"in_crosswalk": Measurement.of(1.0), "orphan": Measurement.of(99.0)}
    grid = crosswalk(overlap("in_crosswalk", "h1", 100.0))

    _, coverage = population_weighted_mean(values, grid)

    assert coverage.unmatched_sources == ("orphan",)


def test_the_coverage_summary_names_both_halves() -> None:
    values = {"t1": Measurement.of(5.0)}
    grid = crosswalk(overlap("t1", "h1", 10.0), hexes=("h1", "h2"))

    _, coverage = population_weighted_mean(values, grid)

    assert coverage.summary() == (
        "1 of 2 hexes received a value; 1 absent (no_overlapping_source 1)"
    )


# ---- extensive: apportionment -------------------------------------------


def test_apportion_splits_a_count_by_population_share() -> None:
    # 3,000 people in the tract, 30% of them in h1 and 70% in h2.
    values = {"t1": Measurement.of(3000.0)}
    grid = crosswalk(
        overlap("t1", "h1", 900.0, pop_weight=0.3),
        overlap("t1", "h2", 2100.0, pop_weight=0.7),
    )

    results, _ = apportion(values, grid)

    assert [r.value.value for r in results] == [900.0, 2100.0]


def test_apportion_and_the_weighted_mean_disagree_which_is_the_point() -> None:
    """Section 7's warning, as an assertion.

    The same numbers through the wrong branch give a wrong answer rather than an
    obviously broken one, which is why the two functions live in one module.
    """
    values = {"t1": Measurement.of(20.0), "t2": Measurement.of(60.0)}
    grid = crosswalk(
        overlap("t1", "h1", 900.0, pop_weight=0.9),
        overlap("t2", "h1", 100.0, pop_weight=0.1),
    )

    (intensive,), _ = population_weighted_mean(values, grid)
    (extensive,), _ = apportion(values, grid)

    assert intensive.value.value == 24.0
    assert extensive.value.value == 24.0  # 20*0.9 + 60*0.1, coincidentally equal
    # ... but change the shares and they part company immediately.
    grid = crosswalk(
        overlap("t1", "h1", 900.0, pop_weight=0.5),
        overlap("t2", "h1", 100.0, pop_weight=0.5),
    )
    (intensive,), _ = population_weighted_mean(values, grid)
    (extensive,), _ = apportion(values, grid)

    assert intensive.value.value == 24.0
    assert extensive.value.value == 40.0


def test_apportion_treats_an_unpopulated_overlap_as_zero_apportioned() -> None:
    # Unlike the intensive case: no people in the hex means no people apportioned
    # to it, which is an observation rather than an absence.
    values = {"t1": Measurement.of(3000.0)}
    grid = crosswalk(overlap("t1", "h1", 0.0, pop_weight=0.0))

    (result,), coverage = apportion(values, grid)

    assert result.value == Measurement.of(0.0)
    assert coverage.absent == 0


def test_apportion_reports_absence_the_same_way() -> None:
    grid = crosswalk(overlap("t1", "h1", 10.0, pop_weight=1.0), hexes=("h1", "h2"))

    results, coverage = apportion({"t1": Measurement.absent()}, grid)

    assert results[0].absence == "no_source_value"
    assert results[1].absence == "no_overlapping_source"
    assert coverage.observed == 0
