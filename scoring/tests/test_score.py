"""Methodology section 10 step 4, and what a scored run has to be able to promise.

Three promises are under test here beyond the arithmetic. That a hex without a
score says why. That the same inputs under the same methodology version produce
the same output. And that what gets written matches the columns `hex_score`
actually has, which is checked against the migration rather than against a list
retyped here.
"""

import re
from collections.abc import Mapping
from datetime import date

import pytest

from burden.component import ComponentResult, GroupMean, HexComponent
from burden.confidence import HexConfidence, HexEvidence, confidence_for_run, indicator_ids
from burden.eligibility import eligible
from burden.methodology import METHODOLOGY_VERSION
from burden.percentile import rank_indicators
from burden.pollution import pollution_burden
from burden.population import population_characteristics
from burden.score import burden_score
from tests.registry import REPO_ROOT

POLLUTION_GROUPS = ("exposures", "environmental_effects")
POPULATION_GROUPS = ("sensitive_populations", "socioeconomic_factors")
RUN_DATE = date(2026, 9, 11)


def fabricate(
    scores: Mapping[str, float | None], groups: tuple[str, str], reason: str
) -> ComponentResult:
    """A component result with the scores stated outright.

    The component arithmetic has its own tests; what matters here is what
    section 10 step 4 does with two components once it has them.
    """
    rows = tuple(
        HexComponent(
            h3=h3,
            score=scores[h3],
            raw=scores[h3],
            groups=(
                GroupMean(groups[0], None if scores[h3] is None else 60.0, (), ()),
                GroupMean(groups[1], None if scores[h3] is None else 30.0, (), ()),
            ),
            no_score_reason=None if scores[h3] is not None else reason,
            confidence_penalty=1.0 if scores[h3] is not None else 0.0,
        )
        for h3 in sorted(scores)
    )
    present = [value for value in scores.values() if value is not None]
    return ComponentResult(hexes=rows, raw_max=max(present) if present else None)


def pollution(scores: Mapping[str, float | None]) -> ComponentResult:
    return fabricate(scores, POLLUTION_GROUPS, "insufficient_pollution_data")


def population(scores: Mapping[str, float | None]) -> ComponentResult:
    return fabricate(scores, POPULATION_GROUPS, "insufficient_population_data")


def populated(*hexes: str) -> dict[str, float | None]:
    return {h3: 900.0 for h3 in hexes}


# ---- section 10 step 4, the multiplication -------------------------------


def test_the_score_is_the_two_components_multiplied() -> None:
    # 9.5 * 2.0 = 19 and 6.0 * 6.0 = 36, which is section 10's own worked
    # example. The hex that is merely bad at both outscores the one that is
    # dreadful at one and fine at the other, and that is the multiplicative
    # model doing what it was chosen to do.
    grid = eligible(populated("dreadful", "middling"))
    result = burden_score(
        eligibility=grid,
        pollution=pollution({"dreadful": 9.5, "middling": 6.0}),
        population=population({"dreadful": 2.0, "middling": 6.0}),
    ).by_h3()

    assert result["dreadful"].score == pytest.approx(19.0)
    assert result["middling"].score == pytest.approx(36.0)
    assert result["middling"].score > result["dreadful"].score  # type: ignore[operator]


def test_an_additive_model_would_have_ranked_them_the_other_way() -> None:
    # 10 * 1 = 10 against 5 * 5 = 25, so the balanced hex wins. Adding instead
    # gives 11 against 10 and the lopsided one wins. Section 3 rejects that: an
    # additive model lets a high score in one component fully compensate for a
    # low score in the other, which is not what cumulative burden means.
    grid = eligible(populated("lopsided", "balanced"))
    result = burden_score(
        eligibility=grid,
        pollution=pollution({"lopsided": 10.0, "balanced": 5.0}),
        population=population({"lopsided": 1.0, "balanced": 5.0}),
    ).by_h3()

    assert result["lopsided"].score == pytest.approx(10.0)
    assert result["balanced"].score == pytest.approx(25.0)


def test_the_score_stays_in_the_band_the_column_allows() -> None:
    # hex_score.score is CHECK (score > 0 AND score <= 100). Both components are
    # strictly positive because every percentile is, so the product cannot reach
    # zero, and both top out at 10, so it cannot exceed 100.
    grid = eligible(populated("top", "bottom"))
    result = burden_score(
        eligibility=grid,
        pollution=pollution({"top": 10.0, "bottom": 0.5}),
        population=population({"top": 10.0, "bottom": 0.5}),
    ).by_h3()

    assert result["top"].score == pytest.approx(100.0)
    for row in result.values():
        assert row.score is not None
        assert 0.0 < row.score <= 100.0


# ---- the score's own distribution ----------------------------------------


def test_each_scored_hex_gets_its_statewide_percentile() -> None:
    # Five scores through the same section 9 machinery as every indicator:
    # 100 * (r - 0.5) / 5 gives 10, 30, 50, 70, 90.
    names = [f"h{i}" for i in range(5)]
    grid = eligible(populated(*names))
    scores = {h3: float(index + 1) for index, h3 in enumerate(names)}

    result = burden_score(
        eligibility=grid,
        pollution=pollution(dict(scores)),
        population=population(dict.fromkeys(names, 1.0)),
    ).by_h3()

    assert [result[h3].percentile for h3 in names] == [10.0, 30.0, 50.0, 70.0, 90.0]


def test_the_percentile_stays_strictly_inside_zero_and_one_hundred() -> None:
    # hex_score.percentile is CHECK (percentile > 0 AND percentile < 100).
    names = [f"h{i:03d}" for i in range(50)]
    grid = eligible(populated(*names))
    scores = {h3: float(index + 1) for index, h3 in enumerate(names)}

    run = burden_score(
        eligibility=grid,
        pollution=pollution(dict(scores)),
        population=population(dict.fromkeys(names, 1.0)),
    )

    for row in run.scored():
        assert row.percentile is not None
        assert 0.0 < row.percentile < 100.0


def test_the_runs_distribution_is_recorded() -> None:
    # The map colours by percentile because the raw distribution is heavily
    # right-skewed, so the distribution it was ranked against is kept.
    names = ["a", "b", "c"]
    grid = eligible(populated(*names))

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"a": 1.0, "b": 2.0, "c": 8.0}),
        population=population(dict.fromkeys(names, 2.0)),
    )

    assert run.distribution.n == 3
    assert run.distribution.min_value == pytest.approx(2.0)
    assert run.distribution.max_value == pytest.approx(16.0)


def test_a_hex_without_a_score_is_in_no_percentile_denominator() -> None:
    # The same rule section 9 applies to every indicator. Three scored hexes and
    # two the run could not describe means a denominator of three.
    names = ["a", "b", "c", "thin", "empty"]
    grid = eligible({**populated("a", "b", "c", "thin"), "empty": 3.0})

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"a": 1.0, "b": 2.0, "c": 3.0, "thin": None}),
        population=population({"a": 1.0, "b": 1.0, "c": 1.0, "thin": 1.0}),
    )

    assert run.distribution.n == 3
    assert run.scored_hexes() == 3
    assert len(run.hexes) == len(names)


# ---- all four reasons ----------------------------------------------------


def test_a_hex_across_the_state_line_says_so() -> None:
    grid = eligible(populated("inside", "texas"), outside_pilot_state=["texas"])

    result = burden_score(
        eligibility=grid,
        pollution=pollution({"inside": 5.0}),
        population=population({"inside": 5.0}),
    ).by_h3()

    assert result["texas"].no_score_reason == "outside_pilot_state"
    assert result["texas"].score is None


def test_a_hex_with_almost_nobody_in_it_says_so() -> None:
    grid = eligible({"town": 900.0, "marsh": 11.0})

    result = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    ).by_h3()

    assert result["marsh"].no_score_reason == "low_population"


def test_a_populated_hex_the_pollution_half_could_not_describe() -> None:
    grid = eligible(populated("town", "unlit"))

    result = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0, "unlit": None}),
        population=population({"town": 5.0, "unlit": 5.0}),
    ).by_h3()

    assert result["unlit"].no_score_reason == "insufficient_pollution_data"


def test_a_populated_hex_the_population_half_could_not_describe() -> None:
    grid = eligible(populated("town", "uncounted"))

    result = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0, "uncounted": 5.0}),
        population=population({"town": 5.0, "uncounted": None}),
    ).by_h3()

    assert result["uncounted"].no_score_reason == "insufficient_population_data"


def test_when_both_halves_fail_the_pollution_reason_is_the_one_stored() -> None:
    # One column, two true answers, so the tie breaks toward pollution. Nothing
    # is hidden by the convention: both components' group means sit on the row,
    # so the panel still shows a reader that both halves failed.
    grid = eligible(populated("town", "dark"))

    row = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0, "dark": None}),
        population=population({"town": 5.0, "dark": None}),
    ).by_h3()["dark"]

    assert row.no_score_reason == "insufficient_pollution_data"
    assert row.exposures_mean is None
    assert row.sensitive_mean is None


def test_being_over_the_line_outranks_being_empty() -> None:
    # A cell in Mississippi is not a Louisiana cell that happens to be empty,
    # and calling it one invites the question of why the pilot scores
    # Mississippi.
    grid = eligible({"town": 900.0, "over_the_line": 0.0}, outside_pilot_state=["over_the_line"])

    assert grid.reasons()["over_the_line"] == "outside_pilot_state"


def test_all_four_reasons_are_reachable_in_one_run() -> None:
    grid = eligible(
        {"town": 900.0, "marsh": 2.0, "unlit": 900.0, "uncounted": 900.0, "texas": 900.0},
        outside_pilot_state=["texas"],
    )

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0, "unlit": None, "uncounted": 5.0}),
        population=population({"town": 5.0, "unlit": 5.0, "uncounted": None}),
    )

    assert run.reasons() == {
        "outside_pilot_state": 1,
        "low_population": 1,
        "insufficient_pollution_data": 1,
        "insufficient_population_data": 1,
    }


def test_every_hex_has_a_score_or_a_reason_and_never_both() -> None:
    # The hex_score_scored_xor_reason constraint in migration 0009. Both would
    # leave the map with a colour it cannot explain; neither would leave a hole
    # a reader has to guess at.
    grid = eligible(
        {"town": 900.0, "marsh": 2.0, "unlit": 900.0, "texas": 900.0},
        outside_pilot_state=["texas"],
    )

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0, "unlit": None}),
        population=population({"town": 5.0, "unlit": 5.0}),
    )

    for row in run.hexes:
        assert (row.score is None) == (row.no_score_reason is not None)


# ---- the sub-scores travel with the total --------------------------------


def test_both_component_scores_and_all_four_group_means_are_kept() -> None:
    # The explain panel renders the waterfall from these and they cannot be
    # recovered from the total once the weights have been applied.
    grid = eligible(populated("town"))

    row = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 8.0}),
        population=population({"town": 4.0}),
    ).by_h3()["town"]

    assert row.pollution_burden == pytest.approx(8.0)
    assert row.population_characteristics == pytest.approx(4.0)
    assert row.exposures_mean == pytest.approx(60.0)
    assert row.env_effects_mean == pytest.approx(30.0)
    assert row.sensitive_mean == pytest.approx(60.0)
    assert row.socioeconomic_mean == pytest.approx(30.0)


# ---- reproducibility, section 13 -----------------------------------------


def test_the_same_inputs_in_a_different_order_produce_an_identical_run() -> None:
    names = [f"h{i:02d}" for i in range(12)]
    scores = {h3: float(index + 1) for index, h3 in enumerate(names)}
    reversed_scores = dict(reversed(list(scores.items())))

    first = burden_score(
        eligibility=eligible(populated(*names)),
        pollution=pollution(dict(scores)),
        population=population(dict.fromkeys(names, 3.0)),
    )
    second = burden_score(
        eligibility=eligible(populated(*reversed(names))),
        pollution=pollution(reversed_scores),
        population=population(dict.fromkeys(reversed(names), 3.0)),
    )

    assert first == second
    assert first.digest() == second.digest()


def test_the_rows_come_out_ordered_by_hex() -> None:
    grid = eligible({"hC": 900.0, "hA": 900.0, "hB": 4.0})

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"hA": 5.0, "hC": 5.0}),
        population=population({"hA": 5.0, "hC": 5.0}),
    )

    assert [row.h3 for row in run.hexes] == ["hA", "hB", "hC"]


def test_a_different_methodology_version_is_a_different_run() -> None:
    # A score is a statement about a place under a particular set of rules, so
    # two runs whose every figure agrees are still different results if the
    # rules differ. A digest that collided on them would assert something
    # section 17 denies.
    grid = eligible(populated("a", "b"))
    args = {
        "eligibility": grid,
        "pollution": pollution({"a": 5.0, "b": 6.0}),
        "population": population({"a": 5.0, "b": 6.0}),
    }

    current = burden_score(**args)  # type: ignore[arg-type]
    future = burden_score(**args, methodology_version="0.2.0")  # type: ignore[arg-type]

    assert [row.score for row in current.hexes] == [row.score for row in future.hexes]
    assert current.digest() != future.digest()


def test_changing_one_number_changes_the_digest() -> None:
    grid = eligible(populated("a", "b"))

    first = burden_score(
        eligibility=grid,
        pollution=pollution({"a": 5.0, "b": 6.0}),
        population=population({"a": 5.0, "b": 6.0}),
    )
    second = burden_score(
        eligibility=grid,
        pollution=pollution({"a": 5.0, "b": 6.5}),
        population=population({"a": 5.0, "b": 6.0}),
    )

    assert first.digest() != second.digest()


# ---- the methodology version, section 17 ---------------------------------


def test_every_row_carries_the_version_including_the_unscored_ones() -> None:
    grid = eligible({"town": 900.0, "marsh": 2.0})

    run = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    )

    assert run.methodology_version == METHODOLOGY_VERSION
    assert {row.methodology_version for row in run.hexes} == {METHODOLOGY_VERSION}


def test_the_version_is_the_one_the_api_reports() -> None:
    # Section 17: a published score carries the version that produced it. A row
    # stamped with a version whose rules it was not produced under cannot be
    # reproduced by anyone reading the paper at that version.
    from tests.registry import api_module

    assert METHODOLOGY_VERSION == api_module("methodology").METHODOLOGY_VERSION


# ---- what gets written ---------------------------------------------------


def hex_score_columns() -> list[str]:
    """The columns `hex_score` actually has, read from migration 0009."""
    path = REPO_ROOT / "api" / "migrations" / "0009_scores.up.sql"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("migration 0009 is not in this tree")

    body = path.read_text().split("CREATE TABLE hex_score (", 1)[1].split("\n);", 1)[0]

    columns = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("--", "CONSTRAINT", "PRIMARY KEY", "CHECK")):
            continue
        name = re.split(r"\s", stripped, maxsplit=1)[0]
        if name.isidentifier():
            columns.append(name)
    return columns


def test_the_emitted_rows_match_the_columns_the_table_has() -> None:
    # Read from the migration rather than retyped here, so a column added in
    # 0017 without a matching field fails this instead of failing an insert.
    grid = eligible(populated("town"))
    run = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    )

    (row,) = run.rows_for_sql(run_id=7)

    assert sorted(row) == sorted(hex_score_columns())


def test_the_confidence_columns_are_named_and_left_for_cs_205() -> None:
    grid = eligible(populated("town"))
    (row,) = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    ).rows_for_sql(run_id=7)

    for column in ("confidence", "confidence_band", "c_coverage", "c_monitor"):
        assert row[column] is None


def test_the_unscored_hexes_are_written_too() -> None:
    # The hex_score table comment says one row per hex per run including the
    # unscored ones, and GET /health counts it to decide whether the pipeline
    # has run at all.
    grid = eligible({"town": 900.0, "marsh": 2.0})

    rows = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    ).rows_for_sql(run_id=7)

    assert [row["h3"] for row in rows] == ["marsh", "town"]
    assert [row["run_id"] for row in rows] == [7, 7]


def test_the_version_is_not_repeated_onto_every_row_in_sql() -> None:
    # It lives on pipeline_run and each row reaches it through run_id. Repeating
    # one string across 150,000 rows is what the foreign key is for.
    grid = eligible(populated("town"))
    (row,) = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    ).rows_for_sql(run_id=7)

    assert "methodology_version" not in row


# ---- the components have to have scored the same hexes -------------------


def test_a_component_over_a_different_universe_is_refused() -> None:
    grid = eligible(populated("a", "b"))

    with pytest.raises(ValueError, match="cannot be composed"):
        burden_score(
            eligibility=grid,
            pollution=pollution({"a": 5.0}),
            population=population({"a": 5.0, "b": 5.0}),
        )


# ---- the whole path ------------------------------------------------------


def test_a_run_from_populations_and_indicators_through_to_rows() -> None:
    # Section 5 sets the universe, section 9 ranks against it, section 10 builds
    # the components and multiplies them. The eleven-person cell and the one
    # over the state line never enter a denominator and come back explained.
    grid = eligible(
        {"industrial": 4000.0, "suburb": 2500.0, "rural": 300.0, "marsh": 11.0, "texas": 5000.0},
        outside_pilot_state=["texas"],
    )

    values: dict[str, Mapping[str, float | None]] = {
        "E1": {"industrial": 90.0, "suburb": 20.0, "rural": 10.0},
        "E2": {"industrial": 85.0, "suburb": 25.0, "rural": 12.0},
        "F1": {"industrial": 40.0, "suburb": 5.0, "rural": 1.0},
        "F2": {"industrial": 30.0, "suburb": 4.0, "rural": 2.0},
        "S1": {"industrial": 9.0, "suburb": 6.0, "rural": 7.0},
        "P1": {"industrial": 40.0, "suburb": 12.0, "rural": 30.0},
        "P2": {"industrial": 25.0, "suburb": 8.0, "rural": 20.0},
        "P3": {"industrial": 10.0, "suburb": 2.0, "rural": 4.0},
        "P4": {"industrial": 12.0, "suburb": 4.0, "rural": 9.0},
    }
    rankings = rank_indicators(values, scored=grid.scored)

    run = burden_score(
        eligibility=grid,
        pollution=pollution_burden(rankings, scored=grid.scored),
        population=population_characteristics(rankings, scored=grid.scored),
    )
    by_h3 = run.by_h3()

    assert run.scored_hexes() == 3
    assert run.distribution.n == 3
    assert by_h3["marsh"].no_score_reason == "low_population"
    assert by_h3["texas"].no_score_reason == "outside_pilot_state"
    # The industrial cell is worst on both halves, so it takes the top score and
    # the top percentile of the three.
    assert by_h3["industrial"].score == pytest.approx(100.0)
    assert by_h3["industrial"].percentile == pytest.approx(100 * 2.5 / 3)
    assert len(run.rows_for_sql(run_id=1)) == 5


# ---- section 12 travels with the row -------------------------------------


def confidences(*hexes: str) -> dict[str, HexConfidence]:
    """Fully supported confidence for each hex, so a test can vary one thing."""
    return confidence_for_run(
        [
            HexEvidence(
                h3=h3,
                observed_indicators=frozenset(indicator_ids()),
                mean_block_area_km2=0.1,
                nearest_monitor_km=1.0,
            )
            for h3 in hexes
        ],
        vintages=dict.fromkeys(indicator_ids(), RUN_DATE),
        as_of=RUN_DATE,
    )


def test_the_confidence_columns_are_filled_when_a_run_has_confidence() -> None:
    grid = eligible(populated("town"))

    (row,) = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
        confidence=confidences("town"),
    ).rows_for_sql(run_id=7)

    assert row["confidence"] == pytest.approx(1.0)
    assert row["confidence_band"] == "high"
    assert row["c_coverage"] == pytest.approx(1.0)
    assert row["nearest_monitor_km"] == pytest.approx(1.0)


def test_a_hex_with_no_score_carries_no_confidence() -> None:
    # Confidence measures how well supported a score is. An unscored hex has
    # none to support, and a number sitting there invites being read as one.
    grid = eligible({"town": 900.0, "marsh": 2.0})

    rows = {
        row["h3"]: row
        for row in burden_score(
            eligibility=grid,
            pollution=pollution({"town": 5.0}),
            population=population({"town": 5.0}),
            confidence=confidences("town", "marsh"),
        ).rows_for_sql(run_id=7)
    }

    assert rows["marsh"]["confidence"] is None
    assert rows["marsh"]["confidence_band"] is None
    assert rows["town"]["confidence"] is not None


def test_a_run_given_no_confidence_still_emits_the_columns_empty() -> None:
    # CS-204 ran before CS-205 existed and the insert shape did not change.
    grid = eligible(populated("town"))

    (row,) = burden_score(
        eligibility=grid,
        pollution=pollution({"town": 5.0}),
        population=population({"town": 5.0}),
    ).rows_for_sql(run_id=7)

    assert row["confidence"] is None
    assert "confidence_band" in row


def test_two_runs_differing_only_in_confidence_are_different_runs() -> None:
    # Confidence is part of what a run published, so the reproducibility digest
    # covers it. Identical scores with different support are not one result.
    grid = eligible(populated("town"))
    args = {
        "eligibility": grid,
        "pollution": pollution({"town": 5.0}),
        "population": population({"town": 5.0}),
    }

    bare = burden_score(**args)  # type: ignore[arg-type]
    measured = burden_score(**args, confidence=confidences("town"))  # type: ignore[arg-type]

    assert [row.score for row in bare.hexes] == [row.score for row in measured.hexes]
    assert bare.digest() != measured.digest()
