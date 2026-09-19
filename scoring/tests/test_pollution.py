"""Methodology section 10 and section 11, on the pollution half of the score.

The percentiles here are handed in directly rather than ranked from raw values,
so that every expected number is the aggregation arithmetic and nothing else.
CS-201's own behaviour is tested in `test_percentile.py`; what is under test
here is what section 10 does with percentiles once it has them.
"""

from collections.abc import Mapping

import pytest

from burden.percentile import Distribution, RankedHex, Ranking
from burden.pollution import pollution_burden

ALL_EXPOSURES = ("E1", "E2", "E3", "E4")
ALL_ENV_EFFECTS = ("F1", "F2", "F3", "F4")


def ranked(percentiles: Mapping[str, float | None], scored: list[str]) -> Ranking:
    """A CS-201 ranking with the percentiles stated outright."""
    rows = tuple(
        RankedHex(
            h3=h3,
            value=None if percentiles.get(h3) is None else 1.0,
            percentile=percentiles.get(h3),
            observed=percentiles.get(h3) is not None,
        )
        for h3 in sorted(scored)
    )
    observed = sum(1 for row in rows if row.observed)
    return Ranking(
        hexes=rows,
        distribution=Distribution(
            n=observed, n_zero=0, min_value=None, max_value=None, breakpoints=()
        ),
        excluded_unscored=0,
    )


def flat(
    scored: list[str],
    exposures: Mapping[str, float | None],
    env_effects: Mapping[str, float | None],
) -> dict[str, Ranking]:
    """Rankings where every indicator in a group holds that group's percentile."""
    rankings = {i: ranked(exposures, scored) for i in ALL_EXPOSURES}
    rankings.update({i: ranked(env_effects, scored) for i in ALL_ENV_EFFECTS})
    return rankings


# ---- section 10, the weighted combination --------------------------------


def test_the_two_groups_combine_at_one_to_a_half() -> None:
    # hA: Exposures mean 90, Environmental Effects mean 30.
    #     (1.0 * 90 + 0.5 * 30) / 1.5 = 105 / 1.5 = 70.
    # hB: Exposures mean 45, Environmental Effects mean 15.
    #     (1.0 * 45 + 0.5 * 15) / 1.5 = 52.5 / 1.5 = 35.
    # An unweighted mean of the two groups would give 60 and 30 instead, and the
    # 1.0 / 0.5 ratio is a claim about measured exposure against proximity, not
    # a default.
    scored = ["hA", "hB"]
    rankings = flat(scored, {"hA": 90.0, "hB": 45.0}, {"hA": 30.0, "hB": 15.0})

    result = pollution_burden(rankings, scored=scored).by_h3()

    assert result["hA"].raw == pytest.approx(70.0)
    assert result["hB"].raw == pytest.approx(35.0)


def test_the_component_is_rescaled_to_ten_against_the_statewide_maximum() -> None:
    # Section 10 step 3: PB = 10 * PB_raw / max PB_raw. The raws above are 70 and
    # 35, so the top hex takes exactly 10 and the other exactly 5.
    scored = ["hA", "hB"]
    rankings = flat(scored, {"hA": 90.0, "hB": 45.0}, {"hA": 30.0, "hB": 15.0})

    result = pollution_burden(rankings, scored=scored)
    by_h3 = result.by_h3()

    assert result.raw_max == pytest.approx(70.0)
    assert by_h3["hA"].score == pytest.approx(10.0)
    assert by_h3["hB"].score == pytest.approx(5.0)


def test_every_score_lands_in_the_zero_to_ten_band_the_column_allows() -> None:
    # hex_score.pollution_burden is CHECK (pollution_burden BETWEEN 0 AND 10).
    scored = [f"h{i:02d}" for i in range(20)]
    exposures = {h3: float(index + 1) * 4 for index, h3 in enumerate(scored)}
    env = {h3: float(index + 1) for index, h3 in enumerate(scored)}

    for row in pollution_burden(flat(scored, exposures, env), scored=scored).hexes:
        assert row.score is not None
        assert 0.0 <= row.score <= 10.0


def test_the_subgroup_means_are_averaged_not_pooled() -> None:
    # Exposures has two indicators present and Environmental Effects four. The
    # group means are 100 and 10, so the component is
    # (1.0 * 100 + 0.5 * 10) / 1.5 = 70. Pooling all six percentiles instead
    # would give (100 + 100 + 10 + 10 + 10 + 10) / 6 = 40, handing Environmental
    # Effects the larger share purely for having more indicators present.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 100.0}, scored),
        "E2": ranked({"hA": 100.0}, scored),
        "E3": ranked({"hA": None}, scored),
        "E4": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 10.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("exposures") == pytest.approx(100.0)
    assert row.group_mean("environmental_effects") == pytest.approx(10.0)
    assert row.raw == pytest.approx(70.0)


# ---- section 11 rule 1, missing indicators -------------------------------


def test_a_missing_indicator_is_dropped_rather_than_imputed_to_zero() -> None:
    # Two of the four Exposures indicators are present at 100. The mean is the
    # mean of those two, 100. Imputing the absent pair to the bottom of the
    # scale would give roughly 50 and report the hex as half as exposed as it is.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 100.0}, scored),
        "E2": ranked({"hA": 100.0}, scored),
        "E3": ranked({"hA": None}, scored),
        "E4": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 50.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    assert pollution_burden(rankings, scored=scored).by_h3()["hA"].group_mean(
        "exposures"
    ) == pytest.approx(100.0)


def test_a_missing_indicator_is_not_imputed_to_the_median_either() -> None:
    # The median of a percentile distribution is 50, and imputing to it would
    # pull a hex at 100 down to 75. Section 11's "direction matters" paragraph is
    # about exactly this: it moves unmonitored high-burden areas toward the
    # middle, which is the failure the project exists to avoid.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 100.0}, scored),
        "E2": ranked({"hA": 100.0}, scored),
        "E3": ranked({"hA": None}, scored),
        "E4": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 50.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    mean = pollution_burden(rankings, scored=scored).by_h3()["hA"].group_mean("exposures")

    assert mean == pytest.approx(100.0)
    assert mean != pytest.approx(75.0)


def test_the_used_and_dropped_indicators_are_recorded_per_hex() -> None:
    # Section 11 rule 5: a user always sees which of the fifteen produced the
    # score, so the detail panel needs the lists rather than an absence.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 80.0}, scored),
        "E2": ranked({"hA": 60.0}, scored),
        "E3": ranked({"hA": None}, scored),
        "E4": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 20.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]
    exposures = next(g for g in row.groups if g.group == "exposures")

    assert exposures.present == ("E1", "E2")
    assert exposures.missing == ("E3", "E4")


def test_an_indicator_that_was_never_ingested_is_missing_everywhere() -> None:
    # A source that failed all night is not a source that measured zero.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 80.0}, scored),
        "E2": ranked({"hA": 60.0}, scored),
        "E3": ranked({"hA": 40.0}, scored),
        **{i: ranked({"hA": 20.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]
    exposures = next(g for g in row.groups if g.group == "exposures")

    assert exposures.missing == ("E4",)
    assert exposures.mean == pytest.approx(60.0)


# ---- section 11 rule 2, the group minimums -------------------------------


def test_exactly_two_of_four_exposures_is_enough() -> None:
    # The minimum is 2 of 4, so this is computable and the mean is over the two.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 60.0}, scored),
        "E2": ranked({"hA": 20.0}, scored),
        "E3": ranked({"hA": None}, scored),
        "E4": ranked({"hA": None}, scored),
        **{i: ranked({"hA": 20.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    assert pollution_burden(rankings, scored=scored).by_h3()["hA"].group_mean(
        "exposures"
    ) == pytest.approx(40.0)


def test_one_of_four_exposures_is_not_a_weaker_estimate_but_no_estimate() -> None:
    # Below the minimum the group drops out entirely rather than reporting the
    # single indicator it has. A mean of one Exposures indicator is a different
    # quantity wearing the same name.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("E2", "E3", "E4")},
        **{i: ranked({"hA": 40.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("exposures") is None


def test_one_of_four_environmental_effects_is_not_enough_either() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 40.0}, scored) for i in ALL_EXPOSURES},
        "F1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("F2", "F3", "F4")},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("environmental_effects") is None


# ---- section 11 rule 3, the fallback -------------------------------------


def test_without_exposures_the_component_is_environmental_effects_alone() -> None:
    # Not 0.5 * 40 and not 40 / 1.5. The weights re-normalize over the group
    # that survived, so the component is that group's mean outright.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("E2", "E3", "E4")},
        **{i: ranked({"hA": 40.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.raw == pytest.approx(40.0)
    assert row.score is not None
    assert row.no_score_reason is None


def test_losing_exposures_costs_two_thirds_of_the_components_weight() -> None:
    # Exposures is 1.0 of the 1.5, so a third of the weight survives. Section 11
    # rule 3 asks for a heavy penalty and this is where it comes from: the share
    # of the component's own weight still standing, not a number chosen to look
    # severe.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("E2", "E3", "E4")},
        **{i: ranked({"hA": 40.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    assert pollution_burden(rankings, scored=scored).by_h3()[
        "hA"
    ].confidence_penalty == pytest.approx(1 / 3)


def test_losing_environmental_effects_costs_less_than_losing_exposures() -> None:
    # The asymmetry rule 3 asks for, stated as a comparison rather than as two
    # constants that happen to differ.
    scored = ["hA"]
    without_env = {
        **{i: ranked({"hA": 60.0}, scored) for i in ALL_EXPOSURES},
        **{i: ranked({"hA": None}, scored) for i in ALL_ENV_EFFECTS},
    }
    without_exposures = {
        **{i: ranked({"hA": None}, scored) for i in ALL_EXPOSURES},
        **{i: ranked({"hA": 60.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    env_gone = pollution_burden(without_env, scored=scored).by_h3()["hA"]
    exposures_gone = pollution_burden(without_exposures, scored=scored).by_h3()["hA"]

    assert env_gone.confidence_penalty == pytest.approx(2 / 3)
    assert exposures_gone.confidence_penalty == pytest.approx(1 / 3)
    assert exposures_gone.confidence_penalty < env_gone.confidence_penalty


def test_exposures_alone_is_also_the_group_mean_outright() -> None:
    scored = ["hA"]
    rankings = {
        **{i: ranked({"hA": 60.0}, scored) for i in ALL_EXPOSURES},
        **{i: ranked({"hA": None}, scored) for i in ALL_ENV_EFFECTS},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.raw == pytest.approx(60.0)
    assert row.group_mean("environmental_effects") is None


def test_neither_group_computable_is_no_score_with_a_reason() -> None:
    # Section 11 rule 3's other half, and the hex_score_scored_xor_reason
    # constraint: a hex without a score reports why rather than a bare null.
    scored = ["hA"]
    rankings = {
        "E1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("E2", "E3", "E4")},
        "F1": ranked({"hA": 90.0}, scored),
        **{i: ranked({"hA": None}, scored) for i in ("F2", "F3", "F4")},
    }

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.score is None
    assert row.raw is None
    assert row.no_score_reason == "insufficient_pollution_data"


def test_an_unscorable_hex_does_not_drag_the_statewide_maximum() -> None:
    # The rescaling divides by the maximum over hexes that got a raw value, so a
    # no_score hex changes nobody else's score.
    scored = ["hA", "hB"]
    rankings = {
        "E1": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E2": ranked({"hA": 90.0, "hB": None}, scored),
        "E3": ranked({"hA": 90.0, "hB": None}, scored),
        "E4": ranked({"hA": 90.0, "hB": None}, scored),
        **{i: ranked({"hA": 30.0, "hB": None}, scored) for i in ALL_ENV_EFFECTS},
    }

    result = pollution_burden(rankings, scored=scored)
    by_h3 = result.by_h3()

    assert by_h3["hB"].no_score_reason == "insufficient_pollution_data"
    assert by_h3["hA"].score == pytest.approx(10.0)
    assert result.raw_max == pytest.approx(70.0)


# ---- OpenAQ absence must not read as cleanliness -------------------------


def test_a_hex_with_no_monitor_is_not_reported_as_cleaner_than_one_with_one() -> None:
    # hA and hB agree on E1, E2 and E3. hA has a PM2.5 monitor reading at the
    # same level; hB is beyond 25 km of any monitor, so E4 is absent. They must
    # score the same. Were the absence read as zero it would take the bottom
    # percentile, drag hB's Exposures mean from 90 to about 68, and paint a
    # place nobody has ever measured as cleaner than one that was measured.
    scored = ["hA", "hB"]
    rankings = {
        "E1": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E2": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E3": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E4": ranked({"hA": 90.0, "hB": None}, scored),
        **{i: ranked({"hA": 30.0, "hB": 30.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    by_h3 = pollution_burden(rankings, scored=scored).by_h3()

    assert by_h3["hB"].group_mean("exposures") == pytest.approx(90.0)
    assert by_h3["hA"].score == pytest.approx(by_h3["hB"].score)
    assert next(g for g in by_h3["hB"].groups if g.group == "exposures").missing == ("E4",)


def test_openaq_still_moves_the_mean_when_it_is_there() -> None:
    # The other half of the requirement: E4 contributes when present. A measured
    # low reading pulls the Exposures mean down, which is the difference between
    # measured-and-clean and never-measured.
    scored = ["hA", "hB"]
    rankings = {
        "E1": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E2": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E3": ranked({"hA": 90.0, "hB": 90.0}, scored),
        "E4": ranked({"hA": 10.0, "hB": None}, scored),
        **{i: ranked({"hA": 30.0, "hB": 30.0}, scored) for i in ALL_ENV_EFFECTS},
    }

    by_h3 = pollution_burden(rankings, scored=scored).by_h3()

    # (90 + 90 + 90 + 10) / 4 = 70 against (90 + 90 + 90) / 3 = 90.
    assert by_h3["hA"].group_mean("exposures") == pytest.approx(70.0)
    assert by_h3["hB"].group_mean("exposures") == pytest.approx(90.0)


# ---- what gets persisted -------------------------------------------------


def test_the_subscores_come_back_not_only_the_total() -> None:
    # exposures_mean and env_effects_mean are their own columns on hex_score.
    # The explain panel renders the waterfall from them, and recomputing them
    # from the total is not possible once the weights have been applied.
    scored = ["hA"]
    rankings = flat(scored, {"hA": 80.0}, {"hA": 20.0})

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert row.group_mean("exposures") == pytest.approx(80.0)
    assert row.group_mean("environmental_effects") == pytest.approx(20.0)
    assert row.raw == pytest.approx((80.0 + 10.0) / 1.5)


def test_asking_for_a_group_that_is_not_in_this_component_is_an_error() -> None:
    scored = ["hA"]
    row = pollution_burden(flat(scored, {"hA": 80.0}, {"hA": 20.0}), scored=scored).by_h3()["hA"]

    with pytest.raises(KeyError):
        row.group_mean("socioeconomic_factors")


def test_the_population_indicators_are_ignored_here() -> None:
    # The whole run's rankings can be handed to both components.
    scored = ["hA"]
    rankings = flat(scored, {"hA": 80.0}, {"hA": 20.0})
    rankings["S1"] = ranked({"hA": 1.0}, scored)
    rankings["P1"] = ranked({"hA": 1.0}, scored)

    row = pollution_burden(rankings, scored=scored).by_h3()["hA"]

    assert [g.group for g in row.groups] == ["exposures", "environmental_effects"]
    assert row.raw == pytest.approx((80.0 + 10.0) / 1.5)


def test_the_rows_come_out_ordered_by_hex() -> None:
    scored = ["hC", "hA", "hB"]
    rankings = flat(scored, dict.fromkeys(scored, 50.0), dict.fromkeys(scored, 50.0))

    result = pollution_burden(rankings, scored=scored)

    assert [row.h3 for row in result.hexes] == ["hA", "hB", "hC"]


def test_scoring_no_hexes_at_all_produces_nothing_rather_than_failing() -> None:
    result = pollution_burden({}, scored=[])

    assert result.hexes == ()
    assert result.raw_max is None


# ---- percentiles from two different denominators are not comparable ------


def test_a_ranking_over_a_different_universe_is_refused() -> None:
    # Averaging a percentile ranked against 150,000 hexes with one ranked
    # against 900 produces a number that looks like a component score and is
    # not one. The failure is silent everywhere downstream of here.
    scored = ["hA", "hB"]
    rankings = flat(scored, {"hA": 90.0, "hB": 45.0}, {"hA": 30.0, "hB": 15.0})
    rankings["E1"] = ranked({"hA": 90.0}, ["hA"])

    with pytest.raises(ValueError, match="not comparable"):
        pollution_burden(rankings, scored=scored)
