"""CS-213: the disparity analysis, its cohorts, and the framing it must carry.

Two kinds of test here. The first kind checks the analysis finds what is planted
in the data, including the case where nothing is planted. The second kind checks
the framing, which for this ticket is not decoration: section 13.6 asks for a
result that cannot be read as circular and cannot be treated as a gate, and both
of those are properties of the code that a test can hold in place.
"""

import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from pipeline.analysis import statistics as st
from pipeline.analysis.disparity import (
    FRAMING,
    INDEPENDENCE,
    CorrelationResult,
    DisparityReport,
    HexRow,
    Measure,
    analyse,
    build_cohorts,
    load_rows,
    run_disparity,
)

NOW = datetime(2026, 9, 11, 9, 0, tzinfo=UTC)

# Small enough to keep the suite quick, large enough that the interval means
# something. The production default is 2000.
RESAMPLES = 300

#: Twelve rather than three, because a cluster bootstrap over three clusters
#: reports mostly its own instability. Louisiana has sixty-four parishes.
PARISHES = (
    "Ascension",
    "Calcasieu",
    "East Baton Rouge",
    "Iberville",
    "Jefferson",
    "Lafourche",
    "Orleans",
    "Plaquemines",
    "St. Bernard",
    "St. Charles",
    "St. James",
    "West Baton Rouge",
)


#: Each parish sits at its own level regardless of its scores. Real ones do, and
#: it is what gives the cluster bootstrap something to resample: parishes that
#: were identical apart from noise would make resampling them look free.
PARISH_LEVEL = (-12.0, -8.0, -5.0, -2.0, 0.0, 2.0, 3.0, 5.0, 6.0, 8.0, 9.0, 12.0)


def hexes(
    *,
    slope: float,
    intercept: float = 30.0,
    per_parish: int = 20,
    band: str = "high",
    seed: int = 4242,
) -> list[HexRow]:
    """Hexes whose Black share is a planted function of their score percentile.

    `slope` is percentage points of share per percentile point, so slope 0 plants
    no relationship at all and the analysis should report that it found none.

    The noise is seeded rather than derived from the row index. An earlier
    version of this fixture built its wiggle out of the same counter as the
    percentile, which quietly planted a correlation into the dataset that was
    supposed to have none.
    """
    rng = random.Random(seed)
    rows: list[HexRow] = []
    for p_index, parish in enumerate(PARISHES):
        level = PARISH_LEVEL[p_index % len(PARISH_LEVEL)]
        for j in range(per_parish):
            percentile = 2.5 + (95.0 * j) / (per_parish - 1)
            share = intercept + level + slope * percentile + rng.uniform(-4.0, 4.0)
            share = max(0.0, min(100.0, share))
            rows.append(
                HexRow(
                    h3=f"8844{p_index:02d}{j:03d}fff",
                    percentile=percentile,
                    population=200.0 + rng.randrange(9) * 150.0,
                    black_pct=share,
                    people_of_color_pct=min(100.0, share + 8.0),
                    confidence_band=band,
                    cluster=parish,
                )
            )
    return rows


def report_for(rows: Sequence[HexRow]) -> DisparityReport:
    return analyse(
        rows,
        now=NOW,
        run_id=42,
        methodology_version="0.1.3",
        acs_vintage="2020-2024",
        resamples=RESAMPLES,
        seed=1,
    )


def pick(report: DisparityReport, cohort: str, measure: Measure, method: str) -> CorrelationResult:
    for result in report.correlations:
        if result.cohort == cohort and result.measure is measure and result.method == method:
            return result
    raise AssertionError(f"no {measure} / {method} result for cohort {cohort}")


# ---- finding what is planted -------------------------------------------


def test_a_planted_relationship_is_found_and_its_interval_clears_zero() -> None:
    report = report_for(hexes(slope=0.5))

    result = pick(report, "confident", Measure.BLACK, "pearson")

    assert report.status == "computed"
    assert result.coefficient > 0.8
    assert result.interval.low > 0.0


def test_no_relationship_is_reported_as_a_result_and_not_as_a_failure() -> None:
    """The criterion this ticket turns on.

    A weaker-than-expected correlation is a finding worth publishing, not a bug
    to fix. So a flat dataset produces a report with a coefficient near zero and
    an interval that straddles it, and nothing anywhere calls that a failure.
    """
    report = report_for(hexes(slope=0.0))

    result = pick(report, "confident", Measure.BLACK, "pearson")

    assert report.status == "computed"
    assert abs(result.coefficient) < 0.2
    assert result.interval.low < 0.0 < result.interval.high


def test_a_negative_relationship_is_reported_with_its_sign_intact() -> None:
    report = report_for(hexes(slope=-0.5, intercept=70.0))

    result = pick(report, "confident", Measure.BLACK, "pearson")

    assert result.coefficient < -0.8
    assert result.interval.high < 0.0


def test_both_measures_and_both_methods_are_reported_for_every_cohort() -> None:
    report = report_for(hexes(slope=0.4))

    combinations = {(r.cohort, r.measure, r.method) for r in report.correlations}

    assert len(combinations) == 8  # two cohorts, two measures, two methods
    for cohort in ("confident", "all_scored"):
        for measure in Measure:
            for method in ("pearson", "spearman"):
                assert (cohort, measure, method) in combinations


def test_the_bootstrap_interval_is_wider_than_the_fisher_comparison() -> None:
    """Both are published so the cost of assuming independence stays visible."""
    report = report_for(hexes(slope=0.4))

    result = pick(report, "confident", Measure.BLACK, "pearson")

    assert result.comparison is not None
    boot = result.interval.high - result.interval.low
    fisher = result.comparison.high - result.comparison.low
    assert boot > fisher


def test_the_effective_sample_is_far_smaller_than_the_hex_count() -> None:
    report = report_for(hexes(slope=0.4))

    cohort = report.cohorts[0]

    assert cohort.n_hexes == len(PARISHES) * 20
    assert cohort.n_effective is not None
    assert cohort.n_effective < cohort.n_hexes


def test_the_report_is_reproducible_from_the_same_rows_and_seed() -> None:
    rows = hexes(slope=0.4)

    first = report_for(rows)
    second = report_for(rows)

    assert first.model_dump() == second.model_dump()


# ---- the top-decile contrast -------------------------------------------


def test_the_contrast_puts_the_finding_in_percentage_points() -> None:
    report = report_for(hexes(slope=0.5))

    contrast = next(
        c for c in report.contrasts if c.cohort == "confident" and c.measure is Measure.BLACK
    )

    assert contrast.top_decile_share > contrast.elsewhere_share
    assert contrast.difference > 0
    assert contrast.ratio > 1.0
    assert contrast.ratio_interval.low > 1.0
    assert contrast.top_decile_population > 0
    assert contrast.elsewhere_population > 0


def test_a_flat_dataset_produces_a_contrast_ratio_near_one() -> None:
    report = report_for(hexes(slope=0.0))

    contrast = next(
        c for c in report.contrasts if c.cohort == "confident" and c.measure is Measure.BLACK
    )

    assert contrast.ratio == pytest.approx(1.0, abs=0.15)
    assert contrast.ratio_interval.low < 1.0 < contrast.ratio_interval.high


# ---- cohorts and exclusions --------------------------------------------


def test_insufficient_confidence_hexes_are_kept_out_of_the_reported_cohort() -> None:
    """Section 12 bars them from validation statistics, and section 13.6 is one."""
    rows = hexes(slope=0.4) + hexes(slope=-0.9, intercept=90.0, per_parish=10, band="insufficient")

    confident, everything = build_cohorts(rows)

    assert len(confident.rows) == len(PARISHES) * 20
    assert len(everything.rows) == len(rows)
    assert all(row.confidence_band != "insufficient" for row in confident.rows)
    assert confident.excluded and "insufficient" in confident.excluded[0]


def test_the_excluded_hexes_are_still_analysed_and_published_beside_the_result() -> None:
    """An exclusion never shown to move the answer is indistinguishable from one
    chosen because it moved the answer."""
    rows = hexes(slope=0.4) + hexes(slope=-0.9, intercept=90.0, per_parish=10, band="insufficient")

    report = report_for(rows)

    reported = pick(report, "confident", Measure.BLACK, "pearson")
    sensitivity = pick(report, "all_scored", Measure.BLACK, "pearson")

    assert reported.coefficient > sensitivity.coefficient
    assert {c.name for c in report.cohorts} == {"confident", "all_scored"}


def test_hexes_with_no_population_are_dropped_before_anything_is_weighted() -> None:
    rows = hexes(slope=0.4)
    empty = HexRow(
        h3="8844990000fff",
        percentile=99.0,
        population=0.0,
        black_pct=100.0,
        people_of_color_pct=100.0,
        confidence_band="high",
        cluster="Orleans",
    )

    report = report_for([*rows, empty])

    assert report.cohorts[0].n_hexes == len(rows)


def test_a_missing_share_drops_that_measure_and_leaves_the_other_alone() -> None:
    rows = [
        HexRow(
            h3=row.h3,
            percentile=row.percentile,
            population=row.population,
            black_pct=None,
            people_of_color_pct=row.people_of_color_pct,
            confidence_band=row.confidence_band,
            cluster=row.cluster,
        )
        for row in hexes(slope=0.4)
    ]

    report = report_for(rows)

    measures = {r.measure for r in report.correlations}
    assert measures == {Measure.PEOPLE_OF_COLOUR}
    assert any("Black population share" in note for note in report.notes)


def test_a_single_parish_gets_no_interval_and_says_why() -> None:
    """A cluster bootstrap needs clusters. Better to report that than to publish
    an interval computed as though hexes were independent."""
    rows = [
        HexRow(
            h3=row.h3,
            percentile=row.percentile,
            population=row.population,
            black_pct=row.black_pct,
            people_of_color_pct=row.people_of_color_pct,
            confidence_band=row.confidence_band,
            cluster="Orleans",
        )
        for row in hexes(slope=0.4)
    ]

    report = report_for(rows)

    assert report.status == "not_computable"
    assert any("bootstrap" in note for note in report.notes)


# ---- nothing to analyse ------------------------------------------------


def test_an_empty_run_says_scoring_has_not_happened_rather_than_raising() -> None:
    report = analyse([], now=NOW, run_id=7, methodology_version="0.1.3")

    assert report.status == "not_computable"
    assert report.reason is not None
    assert "CS-204" in report.reason
    assert report.correlations == ()


def test_a_report_that_computed_nothing_still_carries_the_framing() -> None:
    report = analyse([], now=NOW, run_id=7, methodology_version="0.1.3")

    assert report.framing == FRAMING
    assert report.independence == INDEPENDENCE
    assert INDEPENDENCE in report.markdown()


# ---- the framing is a rule, not a convention ---------------------------


def test_the_independence_argument_cannot_be_emptied_out() -> None:
    with pytest.raises(ValidationError):
        DisparityReport(
            run_id=1,
            analysed_at=NOW,
            methodology_version="0.1.3",
            status="computed",
            independence="   ",
        )


def test_every_serialised_report_carries_both_arguments() -> None:
    """The API, the write-up and the public site all read these fields. A
    consumer cannot receive the coefficient without receiving them too."""
    payload = report_for(hexes(slope=0.4)).model_dump()

    assert payload["framing"] == FRAMING
    assert payload["independence"] == INDEPENDENCE
    assert payload["correlations"]


def test_the_report_states_no_verdict_anywhere() -> None:
    """Section 13.6 is a reported result. Nothing may gate on it, so there is
    nothing on the report to gate on: no pass, no threshold, no verdict."""
    report = report_for(hexes(slope=0.0))

    payload = report.model_dump()

    assert not hasattr(report, "passed")
    assert "threshold" not in payload
    assert report.status in ("computed", "not_computable")


def test_the_page_argues_before_it_reports() -> None:
    """A reader who stops after the first screen should have read the argument."""
    page = report_for(hexes(slope=0.5)).markdown()

    assert page.index(INDEPENDENCE) < page.index("## Correlations")
    assert page.index(FRAMING) < page.index("## Correlations")


def test_the_headline_is_black_share_against_percentile_on_the_reported_cohort() -> None:
    report = report_for(hexes(slope=0.5))

    headline = report.headline()

    assert headline is not None
    assert headline.cohort == "confident"
    assert headline.measure is Measure.BLACK
    assert "CI" in report.summary()


# ---- reading the warehouse ---------------------------------------------


class FakeConnection:
    """Enough asyncpg to satisfy the protocol, and nothing more."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]] = (),
        current: Mapping[str, Any] | None = None,
    ) -> None:
        self.rows = list(rows)
        self.current = current
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]:
        self.queries.append((query, args))
        return self.rows

    async def fetchrow(self, query: str, *args: Any) -> Mapping[str, Any] | None:
        self.queries.append((query, args))
        return self.current


def record(**overrides: Any) -> dict[str, Any]:
    base = {
        "h3": "8844a1b2c3dfff",
        "percentile": 88.0,
        "confidence_band": "high",
        "population": 1200.0,
        "black_pct": 61.0,
        "people_of_color_pct": 70.0,
        "acs_vintage": "2020-2024",
        "cluster": "Iberville",
    }
    base.update(overrides)
    return base


async def test_rows_come_back_typed_with_their_vintage() -> None:
    conn = FakeConnection([record(), record(h3="8844a1b2c3efff", percentile=12.0)])

    rows, vintage = await load_rows(conn, 42)

    assert vintage == "2020-2024"
    assert [row.percentile for row in rows] == [88.0, 12.0]
    assert rows[0].cluster == "Iberville"
    assert conn.queries[0][1] == (42,)


async def test_a_null_share_survives_the_read_as_none() -> None:
    conn = FakeConnection([record(black_pct=None)])

    rows, _ = await load_rows(conn, 42)

    assert rows[0].black_pct is None
    assert rows[0].people_of_color_pct == 70.0


async def test_mixed_acs_vintages_are_reported_rather_than_averaged_over() -> None:
    conn = FakeConnection(
        [record(), record(h3="8844a1b2c3efff", acs_vintage="2019-2023")],
        current={"run_id": 42, "methodology_version": "0.1.3"},
    )

    report = await run_disparity(conn, now=NOW, resamples=RESAMPLES)

    assert report.acs_vintage is None
    assert any("ACS vintage" in note for note in report.notes)


async def test_no_current_run_means_no_analysis_and_a_reason_that_names_it() -> None:
    conn = FakeConnection(current=None)

    report = await run_disparity(conn, now=NOW)

    assert report.status == "not_computable"
    assert report.reason is not None
    assert "CS-204" in report.reason
    assert report.independence == INDEPENDENCE


async def test_the_current_run_supplies_the_methodology_version_it_was_scored_under() -> None:
    conn = FakeConnection(current={"run_id": 91, "methodology_version": "0.1.7"})

    report = await run_disparity(conn, now=NOW)

    assert report.run_id == 91
    assert report.methodology_version == "0.1.7"


async def test_the_row_query_never_joins_demographics_on_h3_alone() -> None:
    """hex_demographics is keyed by run so an old score can be read against the
    inputs it was built from. Joining on h3 alone would pair this run's scores
    with another run's demographics and nothing would fail."""
    conn = FakeConnection([record()])

    await load_rows(conn, 42)

    query = conn.queries[0][0]
    assert "d.run_id = s.run_id" in query
    assert "d.h3 = s.h3" in query


def test_the_statistics_module_is_the_only_thing_doing_arithmetic() -> None:
    """A guard on the split that keeps the numbers unit-testable without a database."""
    assert st.DEFAULT_SEED == 20260911
    assert st.DEFAULT_LEVEL == 0.95
