"""Methodology section 13, the phase gate.

The thing worth testing here is that the gate cannot be talked into passing. So
the cases are the boundaries: exactly eight of ten, a control cell exactly at
the median, a site whose cells were all excluded, and a high-scoring hex that is
not one of the site's frozen cells.

The real `docs/validation/sites.yml` is not parsed here. This package has no
dependencies and cannot read YAML; the fixture is loaded by
`scripts/run_validation.py`, and CI running that script end to end is what
exercises the parsing.
"""

import pytest

from burden.validation import (
    HIGH_BURDEN,
    NEGATIVE_CONTROL,
    STRESS_EMISSIONS,
    STRESS_POVERTY,
    Criteria,
    ScoredCell,
    Site,
    evaluate,
    report,
)

CRITERIA = Criteria(
    high_burden_percentile=90.0,
    high_burden_required=8,
    high_burden_of=10,
    negative_control_percentile=50.0,
    negative_control_required=4,
    negative_control_of=4,
    poverty_band=(40.0, 75.0),
    emissions_below_percentile=90.0,
)


def site(site_id: str, category: str, *cells: str, active: bool = True) -> Site:
    return Site(
        id=site_id,
        name=f"site {site_id}",
        category=category,
        state="LA",
        active=active,
        cells=cells,
    )


def cell(percentile: float, band: str = "high") -> ScoredCell:
    return ScoredCell(percentile=percentile, band=band)


def run(*sites: Site, cells: dict[str, ScoredCell]):  # type: ignore[no-untyped-def]
    return evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2")


def burden_sites(count: int, passing: int) -> tuple[tuple[Site, ...], dict[str, ScoredCell]]:
    """`count` high-burden sites of which `passing` reach the top decile."""
    sites = tuple(site(f"H{i}", HIGH_BURDEN, f"cell{i}") for i in range(count))
    cells = {f"cell{i}": cell(95.0 if i < passing else 60.0) for i in range(count)}
    return sites, cells


def protocol(passing: int) -> tuple[tuple[Site, ...], dict[str, ScoredCell]]:
    """The whole protocol: ten high-burden sites and four clean controls.

    The gate is every gating category, not the primary one alone, so a test
    about the phase gate has to run the protocol rather than half of it.
    """
    sites, cells = burden_sites(10, passing)
    controls = tuple(site(f"N{i}", NEGATIVE_CONTROL, f"control{i}") for i in range(4))
    cells.update({f"control{i}": cell(20.0) for i in range(4)})
    return sites + controls, cells


# ---- the primary gate ----------------------------------------------------


def test_eight_of_ten_clears_the_phase_gate() -> None:
    sites, cells = protocol(8)

    result = run(*sites, cells=cells)

    assert result.category(HIGH_BURDEN).passed == 8
    assert result.category(HIGH_BURDEN).met is True
    assert result.passed is True


def test_a_run_that_never_evaluated_the_controls_does_not_pass() -> None:
    # Ten high-burden sites and no controls is not the protocol, and a gate that
    # cleared on half of it would be reporting something the fixture does not
    # define. All four controls are required, including the requirement that
    # four exist.
    sites, cells = burden_sites(10, 10)

    result = run(*sites, cells=cells)

    assert result.category(HIGH_BURDEN).met is True
    assert result.category(NEGATIVE_CONTROL).met is False
    assert result.passed is False


def test_seven_of_ten_does_not() -> None:
    # The bar is stated in the fixture and this is the only place it is read.
    sites, cells = burden_sites(10, 7)

    result = run(*sites, cells=cells)

    assert result.category(HIGH_BURDEN).passed == 7
    assert result.passed is False


def test_one_cell_in_the_top_decile_is_enough_for_a_site() -> None:
    # "at least one of the site's pre-registered cells". A site is a place, and
    # the burden does not have to fall evenly across it to be real.
    result = run(
        site("H1", HIGH_BURDEN, "a", "b", "c"),
        cells={"a": cell(10.0), "b": cell(20.0), "c": cell(92.0)},
    )

    assert result.sites[0].outcome == "pass"
    assert result.sites[0].best_percentile == 92.0


def test_the_top_decile_boundary_is_inclusive() -> None:
    # The fixture says "falls in the statewide top decile" at threshold 90, so
    # a cell at exactly the 90th is in it.
    assert run(site("H1", HIGH_BURDEN, "a"), cells={"a": cell(90.0)}).sites[0].outcome == "pass"
    assert run(site("H1", HIGH_BURDEN, "a"), cells={"a": cell(89.9)}).sites[0].outcome == "fail"


def test_a_missed_site_says_how_far_short_it_fell() -> None:
    # Section 13 asks for the likely reason for each miss, and "scored but did
    # not rank" is a different problem from "never scored".
    result = run(site("H1", HIGH_BURDEN, "a"), cells={"a": cell(72.0)})

    assert "72.0" in result.sites[0].detail
    assert "did not rank" in result.sites[0].detail


# ---- the cells are frozen ------------------------------------------------


def test_a_high_scoring_hex_outside_the_frozen_cells_does_not_rescue_a_site() -> None:
    # The whole reason the cells were frozen before any score existed. If the
    # gate re-derived them from a radius, widening k by one would hand a missed
    # site eighteen more chances to clear the bar.
    result = run(
        site("H1", HIGH_BURDEN, "registered"),
        cells={"registered": cell(40.0), "next_door": cell(99.0)},
    )

    assert result.sites[0].outcome == "fail"
    assert result.sites[0].best_percentile == 40.0


# ---- negative controls ---------------------------------------------------


def test_a_control_passes_only_if_every_scored_cell_is_below_the_median() -> None:
    passing = run(
        site("N1", NEGATIVE_CONTROL, "a", "b"),
        cells={"a": cell(20.0), "b": cell(49.9)},
    )
    failing = run(
        site("N1", NEGATIVE_CONTROL, "a", "b"),
        cells={"a": cell(20.0), "b": cell(50.0)},
    )

    assert passing.sites[0].outcome == "pass"
    assert failing.sites[0].outcome == "fail"


def test_one_cell_above_the_median_is_reported_as_such() -> None:
    result = run(
        site("N1", NEGATIVE_CONTROL, "a", "b", "c"),
        cells={"a": cell(10.0), "b": cell(80.0), "c": cell(20.0)},
    )

    assert "1 of 3 scored cells" in result.sites[0].detail
    assert "declines to flag any part of it" in result.sites[0].detail


def test_three_of_four_controls_fails_the_category() -> None:
    # All four are required, so this is not a near miss.
    sites = tuple(site(f"N{i}", NEGATIVE_CONTROL, f"c{i}") for i in range(4))
    cells = {f"c{i}": cell(20.0 if i < 3 else 70.0) for i in range(4)}

    result = evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2")

    assert result.category(NEGATIVE_CONTROL).passed == 3
    assert result.category(NEGATIVE_CONTROL).met is False
    assert result.passed is False


# ---- not_applicable ------------------------------------------------------


def test_a_site_with_no_scored_cell_is_not_applicable_and_not_a_pass() -> None:
    # Section 5 leaves cells under 25 people unscored, which the fixture expects
    # to affect the low-population stress cases.
    result = run(site("H1", HIGH_BURDEN, "a", "b"), cells={})

    assert result.sites[0].outcome == "not_applicable"
    assert result.sites[0].cells_unscored == 2
    assert "Never counted as a pass" in result.sites[0].detail


def test_a_not_applicable_site_still_counts_against_the_eight_of_ten() -> None:
    # The gate is eight of the ten registered sites, not eight of however many
    # happened to produce numbers. Dropping unscored sites from the denominator
    # would let a run that scored almost nothing clear the bar.
    sites, cells = burden_sites(10, 8)
    del cells["cell0"]
    del cells["cell1"]

    result = evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2")

    assert result.category(HIGH_BURDEN).passed == 6
    assert result.category(HIGH_BURDEN).of == 10
    assert result.passed is False


# ---- section 12's exclusion ----------------------------------------------


def test_an_insufficient_confidence_cell_is_excluded_before_anything_is_counted() -> None:
    # Section 12 bars it from validation statistics. A site cleared by a cell
    # the system says it does not trust would be the exclusion's whole point
    # defeated.
    result = run(
        site("H1", HIGH_BURDEN, "trusted", "untrusted"),
        cells={"trusted": cell(40.0), "untrusted": cell(99.0, band="insufficient")},
    )

    assert result.sites[0].outcome == "fail"
    assert result.sites[0].cells_scored == 1
    assert result.sites[0].cells_excluded_low_confidence == 1


def test_a_site_whose_cells_are_all_untrusted_is_not_applicable() -> None:
    result = run(
        site("H1", HIGH_BURDEN, "a"),
        cells={"a": cell(99.0, band="insufficient")},
    )

    assert result.sites[0].outcome == "not_applicable"
    assert "insufficient confidence" in result.sites[0].detail


def test_a_low_but_not_insufficient_cell_still_counts() -> None:
    # Section 12 bars only the bottom band. Over-excluding would be its own
    # failure, and would quietly shrink the evidence the gate rests on.
    result = run(site("H1", HIGH_BURDEN, "a"), cells={"a": cell(95.0, band="low")})

    assert result.sites[0].outcome == "pass"


# ---- the inactive set ----------------------------------------------------


def test_an_inactive_out_of_state_site_is_not_evaluated() -> None:
    # Registered now precisely so it cannot be chosen later once a score exists.
    # Flipping `active` is a pre-declared transition, not a change to the set.
    result = run(
        site("H1", HIGH_BURDEN, "a"),
        site("X1", HIGH_BURDEN, "b", active=False),
        cells={"a": cell(95.0), "b": cell(95.0)},
    )

    assert [row.site_id for row in result.sites] == ["H1"]


# ---- the stress cases, reported but not gating ---------------------------


def test_a_poverty_stress_site_inside_the_band_passes() -> None:
    result = run(site("SA1", STRESS_POVERTY, "a"), cells={"a": cell(55.0)})

    assert result.sites[0].outcome == "pass"
    assert result.sites[0].gating is False


def test_a_poverty_stress_site_above_the_band_is_flagged_but_does_not_fail_the_run() -> None:
    # "A result outside it triggers a documented investigation, not an automatic
    # failure." The distinction matters: a gating stress case would be a lever
    # for tuning the score toward the band.
    sites, cells = protocol(10)
    cells["sa"] = cell(88.0)

    result = run(*sites, site("SA1", STRESS_POVERTY, "sa"), cells=cells)
    stress = result.category(STRESS_POVERTY)

    assert stress.results[0].outcome == "fail"
    assert stress.gating is False
    assert stress.met is True
    assert "documented investigation" in stress.results[0].detail


def test_a_poverty_stress_site_below_the_band_is_flagged_too() -> None:
    # The band is two-sided. A Delta parish at the 5th percentile would say
    # something is wrong with the socioeconomic half.
    result = run(site("SA1", STRESS_POVERTY, "a"), cells={"a": cell(12.0)})

    assert result.sites[0].outcome == "fail"
    assert "below the expected" in result.sites[0].detail


def test_an_emissions_stress_site_below_the_top_decile_passes() -> None:
    result = run(site("SB1", STRESS_EMISSIONS, "a"), cells={"a": cell(80.0)})

    assert result.sites[0].outcome == "pass"


def test_an_emissions_stress_site_in_the_top_decile_is_flagged_but_not_gating() -> None:
    # A high-emission low-population site in the top decile means the score is
    # tracking emissions rather than burden on people.
    sites, cells = protocol(10)
    cells["sb"] = cell(97.0)

    result = run(*sites, site("SB1", STRESS_EMISSIONS, "sb"), cells=cells)

    assert result.category(STRESS_EMISSIONS).results[0].outcome == "fail"
    assert result.passed is True


def test_the_stress_cases_are_judged_on_the_sites_highest_cell() -> None:
    # The fixture gives a band without saying which cell it applies to. The
    # highest is used, matching the statistic the primary gate uses and
    # answering the question both stress cases actually ask, which is whether
    # the score over-flagged the place.
    result = run(
        site("SB1", STRESS_EMISSIONS, "a", "b"),
        cells={"a": cell(10.0), "b": cell(95.0)},
    )

    assert result.sites[0].outcome == "fail"
    assert result.sites[0].best_percentile == 95.0
    assert result.sites[0].median_percentile == 52.5


# ---- the criteria come from the fixture ----------------------------------


def test_the_thresholds_are_the_ones_handed_in() -> None:
    # Section 13.7 forbids loosening a criterion in response to a result, so the
    # numbers arrive from the frozen fixture rather than defaulting in code.
    loosened = Criteria(
        high_burden_percentile=50.0,
        high_burden_required=8,
        high_burden_of=10,
        negative_control_percentile=50.0,
        negative_control_required=4,
        negative_control_of=4,
        poverty_band=(40.0, 75.0),
        emissions_below_percentile=90.0,
    )
    sites = (site("H1", HIGH_BURDEN, "a"),)
    cells = {"a": cell(60.0)}

    assert (
        evaluate(sites, cells, criteria=CRITERIA, methodology_version="x").sites[0].outcome
        == "fail"
    )
    assert (
        evaluate(sites, cells, criteria=loosened, methodology_version="x").sites[0].outcome
        == "pass"
    )


def test_a_site_in_a_category_the_protocol_does_not_define_is_refused() -> None:
    with pytest.raises(ValueError, match="category the protocol does not define"):
        run(site("Z1", "invented_category", "a"), cells={"a": cell(95.0)})


# ---- the write-up --------------------------------------------------------


def test_the_report_leads_with_the_outcome_and_where_the_scores_came_from() -> None:
    # A report whose provenance is not on its face invites being read as a
    # result of whichever run the reader happens to have in mind.
    sites, cells = protocol(8)
    written = report(
        evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2"),
        scores_from="run 41",
    )

    assert "**PASS**" in written
    assert "Scores from: run 41" in written
    assert "Methodology version: 0.1.2" in written


def test_the_report_names_every_site_that_did_not_pass() -> None:
    sites, cells = burden_sites(10, 7)
    result = evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2")
    written = report(result, scores_from="run 41")

    assert "**FAIL**" in written
    assert "## Sites that did not pass" in written
    assert len(result.misses()) == 3
    for missed in result.misses():
        assert missed.name in written


def test_the_report_states_the_failure_protocol() -> None:
    # So that a reader looking at a red gate finds the three permitted responses
    # in front of them rather than reaching for the weights.
    sites, cells = burden_sites(10, 7)
    written = report(
        evaluate(sites, cells, criteria=CRITERIA, methodology_version="0.1.2"),
        scores_from="run 41",
    )

    assert "13.7" in written
    assert "never edited" in written
