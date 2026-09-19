"""Methodology sections 10, 11 and 14, on the demographic half of the score.

As in `test_pollution.py`, the percentiles are handed in directly so that every
expected number is the aggregation arithmetic and nothing else. The section 14
guard at the bottom is the one test here that is not about arithmetic at all.
"""

from collections.abc import Mapping

import pytest

from burden.eligibility import eligible
from burden.percentile import Distribution, RankedHex, Ranking, rank_indicators
from burden.population import population_characteristics
from tests.registry import api_registry

ALL_SENSITIVE = ("S1", "S2")
ALL_SOCIOECONOMIC = ("P1", "P2", "P3", "P4", "P5")


def ranked(percentiles: Mapping[str, float | None], scored: list[str]) -> Ranking:
    rows = tuple(
        RankedHex(
            h3=h3,
            value=None if percentiles.get(h3) is None else 1.0,
            percentile=percentiles.get(h3),
            observed=percentiles.get(h3) is not None,
        )
        for h3 in sorted(scored)
    )
    return Ranking(
        hexes=rows,
        distribution=Distribution(
            n=sum(1 for row in rows if row.observed),
            n_zero=0,
            min_value=None,
            max_value=None,
            breakpoints=(),
        ),
        excluded_unscored=0,
    )


def flat(
    scored: list[str],
    sensitive: Mapping[str, float | None],
    socioeconomic: Mapping[str, float | None],
) -> dict[str, Ranking]:
    rankings = {i: ranked(sensitive, scored) for i in ALL_SENSITIVE}
    rankings.update({i: ranked(socioeconomic, scored) for i in ALL_SOCIOECONOMIC})
    return rankings


# ---- section 10, the combination -----------------------------------------


def test_the_two_groups_count_equally() -> None:
    # Both groups carry weight 1.0, so (80 + 40) / 2 = 60 and (40 + 20) / 2 = 30.
    # This is the symmetry Pollution Burden does not have.
    scored = ["hA", "hB"]
    rankings = flat(scored, {"hA": 80.0, "hB": 40.0}, {"hA": 40.0, "hB": 20.0})

    result = population_characteristics(rankings, scored=scored).by_h3()

    assert result["hA"].raw == pytest.approx(60.0)
    assert result["hB"].raw == pytest.approx(30.0)


def test_the_component_is_rescaled_to_ten_against_the_statewide_maximum() -> None:
    scored = ["hA", "hB"]
    rankings = flat(scored, {"hA": 80.0, "hB": 40.0}, {"hA": 40.0, "hB": 20.0})

    result = population_characteristics(rankings, scored=scored)
    by_h3 = result.by_h3()

    assert result.raw_max == pytest.approx(60.0)
    assert by_h3["hA"].score == pytest.approx(10.0)
    assert by_h3["hB"].score == pytest.approx(5.0)


def test_five_socioeconomic_indicators_do_not_outvote_two_sensitive_ones() -> None:
    # This is the case section 10 is arguing about. Sensitive Populations at 100
    # and Socioeconomic Factors at 10 gives (100 + 10) / 2 = 55. Pooling all
    # seven percentiles would give (100 + 100 + 10 * 5) / 7 = 35.7, handing the
    # economic indicators five sevenths of the component for no reason beyond
    # there being five of them.
    scored = ["hA"]
    rankings = flat(scored, {"hA": 100.0}, {"hA": 10.0})

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.raw == pytest.approx(55.0)
    assert row.raw != pytest.approx(250 / 7)


# ---- section 11 rule 2, the group minimums -------------------------------


def test_one_of_two_sensitive_indicators_is_enough() -> None:
    scored = ["hA"]
    rankings = {
        "S1": ranked({"hA": 90.0}, scored),
        "S2": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 30.0}, scored) for i in ALL_SOCIOECONOMIC},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("sensitive_populations") == pytest.approx(90.0)
    assert row.raw == pytest.approx(60.0)


def test_four_of_five_socioeconomic_indicators_is_enough() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 50.0}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": 40.0}, scored) for i in ("P1", "P2", "P3", "P4")},
        "P5": ranked({"hA": None}, scored),
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("socioeconomic_factors") == pytest.approx(40.0)


def test_three_of_five_socioeconomic_indicators_is_not() -> None:
    # The minimum here is the strictest of the four groups, because five
    # correlated ACS rates with two missing is a different description of a place
    # rather than a slightly noisier one.
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 50.0}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": 40.0}, scored) for i in ("P1", "P2", "P3")},
        **{i: ranked({"hA": None}, scored) for i in ("P4", "P5")},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("socioeconomic_factors") is None


def test_a_missing_indicator_is_dropped_not_imputed() -> None:
    # P5 absent, the other four at 80. The mean is 80, not 64.
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 50.0}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": 80.0}, scored) for i in ("P1", "P2", "P3", "P4")},
        "P5": ranked({"hA": None}, scored),
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]
    socio = next(g for g in row.groups if g.group == "socioeconomic_factors")

    assert socio.mean == pytest.approx(80.0)
    assert socio.present == ("P1", "P2", "P3", "P4")
    assert socio.missing == ("P5",)


# ---- section 11 rule 4, the fallback -------------------------------------


def test_without_socioeconomic_the_component_is_sensitive_alone() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 70.0}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": None}, scored) for i in ALL_SOCIOECONOMIC},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.raw == pytest.approx(70.0)
    assert row.no_score_reason is None


def test_without_sensitive_the_component_is_socioeconomic_alone() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": None}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": 70.0}, scored) for i in ALL_SOCIOECONOMIC},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.raw == pytest.approx(70.0)
    assert row.no_score_reason is None


def test_either_loss_costs_the_same_here_unlike_pollution_burden() -> None:
    # Both groups weigh 1.0, so half the component's weight survives whichever
    # one goes. Pollution Burden's penalties are 1/3 and 2/3 because section 10
    # weights its groups unequally; this component's symmetry is not an
    # oversight in one of the two.
    scored = ["hA"]
    no_socio = {
        **{i: ranked({"hA": 70.0}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": None}, scored) for i in ALL_SOCIOECONOMIC},
    }
    no_sensitive = {
        **{i: ranked({"hA": None}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": 70.0}, scored) for i in ALL_SOCIOECONOMIC},
    }

    first = population_characteristics(no_socio, scored=scored).by_h3()["hA"]
    second = population_characteristics(no_sensitive, scored=scored).by_h3()["hA"]

    assert first.confidence_penalty == pytest.approx(0.5)
    assert second.confidence_penalty == pytest.approx(0.5)


def test_neither_group_computable_is_no_score_with_its_own_reason() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": None}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"hA": None}, scored) for i in ALL_SOCIOECONOMIC},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.score is None
    assert row.no_score_reason == "insufficient_population_data"


# ---- section 5, and why it is a different reason -------------------------


def test_a_hex_under_twenty_five_people_never_reaches_this_component() -> None:
    # The whole path: section 5 sets the universe, section 9 ranks against it,
    # section 10 scores it. The eleven-person cell is excluded before anything
    # is ranked, so it is in no denominator and gets no component row.
    population: dict[str, float | None] = {"town": 900.0, "suburb": 400.0, "marsh": 11.0}
    universe = eligible(population)

    values: dict[str, Mapping[str, float | None]] = {
        "S1": {"town": 9.0, "suburb": 4.0, "marsh": 40.0},
        **{
            indicator: {"town": 9.0, "suburb": 4.0, "marsh": 40.0}
            for indicator in ("P1", "P2", "P3", "P4")
        },
    }
    rankings = rank_indicators(values, scored=universe.scored)
    result = population_characteristics(rankings, scored=universe.scored)

    assert universe.reasons() == {"marsh": "low_population"}
    assert rankings["S1"].distribution.n == 2
    assert rankings["S1"].excluded_unscored == 1
    assert [row.h3 for row in result.hexes] == ["suburb", "town"]


def test_low_population_is_not_the_same_as_insufficient_population_data() -> None:
    # One says the methodology declines to score a place with almost nobody in
    # it. The other says a populated place had too little data to describe.
    # Collapsing them would tell a reader in a rural hex that the census failed
    # them when the cell holds eleven people.
    scored = ["populated"]
    rankings = {
        **{i: ranked({"populated": None}, scored) for i in ALL_SENSITIVE},
        **{i: ranked({"populated": None}, scored) for i in ALL_SOCIOECONOMIC},
    }

    row = population_characteristics(rankings, scored=scored).by_h3()["populated"]

    assert row.no_score_reason == "insufficient_population_data"
    assert eligible({"empty": 11.0}).reasons() == {"empty": "low_population"}


# ---- what gets persisted -------------------------------------------------


def test_both_subscores_come_back_not_only_the_total() -> None:
    # sensitive_mean and socioeconomic_mean are their own columns on hex_score.
    scored = ["hA"]
    rankings = flat(scored, {"hA": 80.0}, {"hA": 40.0})

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("sensitive_populations") == pytest.approx(80.0)
    assert row.group_mean("socioeconomic_factors") == pytest.approx(40.0)


def test_the_pollution_indicators_are_ignored_here() -> None:
    scored = ["hA"]
    rankings = flat(scored, {"hA": 80.0}, {"hA": 40.0})
    rankings["E1"] = ranked({"hA": 1.0}, scored)
    rankings["F1"] = ranked({"hA": 1.0}, scored)

    row = population_characteristics(rankings, scored=scored).by_h3()["hA"]

    assert [g.group for g in row.groups] == ["sensitive_populations", "socioeconomic_factors"]
    assert row.raw == pytest.approx(60.0)


# ---- section 14: race and ethnicity are not inputs -----------------------

# Terms that would betray a racial or ethnic composition measure having been
# added to the registry. The list is blunt on purpose: this guard is meant to
# fire on a well-intentioned pull request, not to classify social science.
RACE_TERMS = (
    "race",
    "racial",
    "ethnic",
    "black",
    "hispanic",
    "latino",
    "latina",
    "minority",
    "people of color",
    "people of colour",
    "nonwhite",
    "non-white",
    "white",
)


def test_no_indicator_in_the_registry_measures_race_or_ethnicity() -> None:
    """Section 14, as a test that fails before the score can become circular.

    The project's central claim is that burden in Louisiana falls
    disproportionately on Black communities. An indicator of racial composition
    anywhere in the fifteen would make the score high where the population is
    Black partly because the formula put it there, turn the correlation in
    section 13.6 into a fact about the arithmetic, and leave a Title VI
    disparate-impact argument resting on it far weaker than one resting on a
    metric that never reached for race.
    """
    offenders = []
    for indicator in api_registry().INDICATORS:
        text = f"{indicator.id} {indicator.name} {indicator.description}".lower()
        hits = [term for term in RACE_TERMS if term in text]
        if hits:
            offenders.append((indicator.id, hits))

    assert offenders == []


def test_the_two_groups_hold_exactly_the_seven_indicators_they_should() -> None:
    # An eighth would have to arrive through the registry, and this says which
    # seven the component is built from without going through it.
    scored = ["hA"]
    row = population_characteristics(
        flat(scored, {"hA": 50.0}, {"hA": 50.0}), scored=scored
    ).by_h3()["hA"]

    present = tuple(indicator for group in row.groups for indicator in group.present)

    assert present == ("S1", "S2", "P1", "P2", "P3", "P4", "P5")


def test_a_ranking_of_racial_composition_handed_in_anyway_changes_nothing() -> None:
    # The component reads the group's indicator ids and nothing else, so a
    # demographic ranking that reaches this function is ignored rather than
    # quietly averaged in. Race is carried on the API response for display and
    # for CS-213; this is the arithmetic declining to look at it.
    scored = ["hA"]
    without = flat(scored, {"hA": 80.0}, {"hA": 40.0})
    with_race = dict(without)
    with_race["black_pct"] = ranked({"hA": 99.0}, scored)
    with_race["hispanic_pct"] = ranked({"hA": 99.0}, scored)

    assert population_characteristics(with_race, scored=scored) == population_characteristics(
        without, scored=scored
    )
