"""What a run feeds the scorer: zero against missing, and the four other rules.

Every case here is one the scoring run got wrong in production and no test
could see, because the run lives in `scripts/run_scoring.py`, which imports a
database driver and which nothing imported back. The arithmetic these feed is
tested elsewhere in this package; what is tested here is the input to it.
"""

from dataclasses import dataclass
from datetime import date

import pytest

from burden.inputs import (
    HIGH_UNCERTAINTY_CV,
    INDICATOR_IDS,
    INDICATOR_SOURCES,
    NONCOMPLIANT_STATUSES,
    compliance_window,
    high_cv_population_share,
    indicator_rows,
    indicator_vintages,
    loaded_indicators,
    mean_block_area_m2,
    noncompliant_quarters,
    proximity_values,
    quarter_start,
    source_vintages,
)

RUN_DATE = date(2026, 9, 22)


@dataclass(frozen=True)
class Row:
    """One `tract_hex_weight` row, as `Crosswalk.for_hex` hands them over."""

    tract_geoid: str
    population: float
    mean_block_area_m2: float


# ---- section 9: zero where nothing is near -------------------------------


def test_a_hex_with_no_nearby_facility_is_zero_not_missing() -> None:
    # The links relation returns nothing for a hex with no facility within
    # 10 km, which is where 8,247 of the state's 17,263 hexes used to lose the
    # whole Environmental Effects group.
    values = proximity_values({"near": 4.0}, hexes=("near", "far"), loaded=True)

    assert values == {"near": 4.0, "far": 0.0}


def test_a_null_sum_is_a_zero_as_well() -> None:
    # `sum(...) FILTER (WHERE ...)` over a hex whose nearby facilities all fail
    # the filter. The facilities were looked for; none of them qualified.
    assert proximity_values({"h": None}, hexes=("h",), loaded=True) == {"h": 0.0}


def test_nothing_is_zero_when_the_source_did_not_load() -> None:
    # Section 11's distinction in the one direction it matters: an indicator
    # nothing was loaded for is absent for every hex, so the group drops and the
    # coverage term prices it, rather than the state reading as clean.
    values = proximity_values({}, hexes=("a", "b"), loaded=False)

    assert values == {"a": None, "b": None}


# ---- section 8.2: which quarters F2 counts -------------------------------


def test_the_window_is_twelve_quarters_ending_at_the_run_date() -> None:
    window = compliance_window(RUN_DATE)

    assert len(window) == 12
    assert window[-1] == date(2026, 7, 1) == quarter_start(RUN_DATE)
    assert window[0] == date(2023, 10, 1)
    assert window[1] == date(2024, 1, 1)


def test_an_unknown_quarter_is_not_a_violation() -> None:
    # ECHO writes `unknown` for a quarter nobody monitored, and the filter used
    # to be `status <> 'in_compliance'`, so an uninspected facility scored the
    # maximum 12 of 12 and section 8.2's confounder ran backwards.
    rows = [
        ("f1", date(2026, 7, 1), "unknown"),
        ("f1", date(2026, 4, 1), "violation"),
        ("f1", date(2026, 1, 1), "in_compliance"),
        ("f1", date(2025, 10, 1), "high_priority_violation"),
    ]

    assert noncompliant_quarters(rows, as_of=RUN_DATE) == {"f1": 2}
    assert NONCOMPLIANT_STATUSES == {"violation", "high_priority_violation"}


def test_two_programs_in_one_quarter_are_one_bad_quarter() -> None:
    # The table is keyed by facility, quarter and program, and F2 counts
    # facility-quarters. Taking "the last twelve rows" instead counted a
    # two-permit site's history twice and reached only six quarters back.
    rows = [
        ("f1", date(2026, 7, 1), "violation"),
        ("f1", date(2026, 7, 1), "high_priority_violation"),
    ]

    assert noncompliant_quarters(rows, as_of=RUN_DATE) == {"f1": 1}


def test_a_quarter_outside_the_window_is_not_counted() -> None:
    rows = [
        ("f1", date(2023, 7, 1), "violation"),  # one quarter too old
        ("f1", date(2026, 10, 1), "violation"),  # the quarter after the run
    ]

    assert noncompliant_quarters(rows, as_of=RUN_DATE) == {}


def test_a_facility_with_a_clean_history_is_absent_rather_than_zero() -> None:
    # Absent from this mapping, where the query's COALESCE reads it as zero.
    # Carrying explicit zeros would put every facility in the state in the
    # array the query joins against.
    rows = [("f1", date(2026, 7, 1), "in_compliance")]

    assert noncompliant_quarters(rows, as_of=RUN_DATE) == {}


# ---- section 12: which vintage an indicator carries ----------------------


def test_a_source_is_dated_by_the_oldest_snapshot_the_run_read() -> None:
    # Two snapshots of one source, because a nightly pull leaves rows behind
    # from the previous one. The data is as old as the older half.
    read = [("echo", date(2026, 9, 1)), ("echo", date(2026, 6, 1))]

    assert source_vintages(read) == {"echo": date(2026, 6, 1)}


def test_an_indicator_is_no_fresher_than_its_stalest_source() -> None:
    per_source = {"tri": date(2025, 12, 31), "rsei": date(2012, 12, 31)}

    assert indicator_vintages(per_source)["E3"] == date(2012, 12, 31)


def test_a_missing_contributing_source_makes_the_vintage_unknown() -> None:
    # E3 is TRI scaled by the RSEI weights. Without the weights the toxicity
    # sum is zero for every facility, so dating it by the TRI extract alone
    # would put a fresh date on a quantity the run did not have.
    per_source = {"tri": date(2025, 12, 31)}

    assert "E3" not in indicator_vintages(per_source)
    assert "E3" not in loaded_indicators(per_source)


def test_every_indicator_names_its_sources() -> None:
    assert set(INDICATOR_SOURCES) == set(INDICATOR_IDS)
    assert len(INDICATOR_IDS) == 15


def test_loaded_indicators_are_the_ones_every_source_of_which_was_read() -> None:
    per_source = {"echo": date(2026, 9, 1), "acs": date(2024, 12, 31)}

    assert loaded_indicators(per_source) == frozenset(
        {"F1", "F2", "F3", "F4", "S1", "S2", "P1", "P2", "P3", "P4", "P5"}
    )


# ---- section 12: the two spatial inputs ----------------------------------


def test_the_block_area_mean_is_population_weighted_over_every_tract() -> None:
    # 100 people at 1,000 m2 and 300 at 5,000 m2:
    # (100*1000 + 300*5000) / 400 = 4,000. Keeping whichever tract came last
    # gave this hex either 1,000 or 5,000, depending on row order.
    rows = [Row("t1", 100.0, 1_000.0), Row("t2", 300.0, 5_000.0)]

    assert mean_block_area_m2(rows) == pytest.approx(4_000.0)


def test_a_hex_with_no_block_population_falls_back_to_the_plain_mean() -> None:
    rows = [Row("t1", 0.0, 1_000.0), Row("t2", 0.0, 3_000.0)]

    assert mean_block_area_m2(rows) == pytest.approx(2_000.0)


def test_an_unrecorded_block_area_is_left_out_rather_than_averaged_as_zero() -> None:
    rows = [Row("t1", 100.0, 0.0), Row("t2", 100.0, 2_000.0)]

    assert mean_block_area_m2(rows) == pytest.approx(2_000.0)
    assert mean_block_area_m2([Row("t1", 100.0, 0.0)]) is None
    assert mean_block_area_m2([]) is None


def test_the_cv_share_is_the_population_drawn_from_uncertain_estimates() -> None:
    # Section 12: the share of the hex's population drawn from ACS estimates
    # whose coefficient of variation exceeds 0.30. One estimate per tract, so
    # this is the population share of the tract that exceeds it: 300 of 400.
    rows = [Row("t1", 100.0, 1_000.0), Row("t2", 300.0, 1_000.0)]
    cvs = {"t1": [0.10], "t2": [0.55]}

    assert high_cv_population_share(rows, cvs) == pytest.approx(0.75)


def test_the_share_is_taken_over_estimates_as_well_as_over_population() -> None:
    # Four estimates behind a single tract, one of them noisy: a quarter of the
    # draws on that tract's population are uncertain, not all of them. This is
    # what keeps one noisy small-subgroup count from taking a hex to the floor.
    rows = [Row("t1", 100.0, 1_000.0)]
    cvs = {"t1": [0.4, 0.1, 0.1, 0.1]}

    assert high_cv_population_share(rows, cvs) == pytest.approx(0.25)


def test_the_threshold_is_the_one_sections_7_and_12_name() -> None:
    rows = [Row("t1", 100.0, 1_000.0)]

    assert HIGH_UNCERTAINTY_CV == 0.30
    assert high_cv_population_share(rows, {"t1": [HIGH_UNCERTAINTY_CV]}) == 0.0
    assert high_cv_population_share(rows, {"t1": [0.3001]}) == pytest.approx(1.0)


def test_an_undefined_cv_is_unknown_rather_than_worst_case() -> None:
    # A rate of zero has no coefficient of variation. Counting it as uncertain
    # would penalise every tract that reported none of something.
    rows = [Row("t1", 100.0, 1_000.0), Row("t2", 100.0, 1_000.0)]

    assert high_cv_population_share(rows, {"t1": [None], "t2": [0.5]}) == pytest.approx(1.0)
    assert high_cv_population_share(rows, {}) == 0.0


# ---- section 11 rule 5: the rows a run writes ----------------------------


def test_every_indicator_gets_a_row_for_every_hex() -> None:
    rows = indicator_rows({}, {}, hexes=("h1",))

    assert len(rows) == 15
    assert {row[1] for row in rows} == set(INDICATOR_IDS)
    assert all(row[4] is False for row in rows)


def test_an_unobserved_row_carries_neither_value_nor_percentile() -> None:
    values = {"F1": {"h1": 0.0, "h2": None}}
    percentiles = {"F1": {"h1": 12.5, "h2": None}}

    rows = {
        (h3, indicator): (value, percentile, observed)
        for h3, indicator, value, percentile, observed in indicator_rows(
            values, percentiles, hexes=("h1", "h2")
        )
    }

    # Zero is an observation and carries its percentile; absence carries
    # neither, which is what `hex_indicator_absent_has_no_value` requires.
    assert rows[("h1", "F1")] == (0.0, 12.5, True)
    assert rows[("h2", "F1")] == (None, None, False)
    assert rows[("h1", "E4")] == (None, None, False)
