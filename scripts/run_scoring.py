#!/usr/bin/env python3
"""CS-204: the scoring run. Indicators in, `hex_score` out.

The arithmetic is not here. `scoring/burden` owns every decision section 8
through 12 makes, has no database dependency, and is tested on its own. This
script is the part that could not be tested without data: it reads what the
pipeline loaded, hands it to that package in the shape it expects, and writes
the three tables the API and the tile build read.

The order is section 10's:

    population per hex -> eligibility (section 5)
                       -> indicator values over the scored hexes
                       -> statewide percentiles (section 9)
                       -> two components (section 10 steps 1-3)
                       -> score = PB x PC (step 4)
                       -> confidence (section 12)

**What is missing is missing, and what is zero is zero.** An indicator whose
source this run did not read is left out rather than filled in:
`component.compute` drops it, re-weights the groups that survive, and records
the loss as a confidence penalty. A zero would instead say "measured, and there
is none", which for an unmonitored place is the exact failure this project
exists to avoid. The proximity indicators run the other way. Section 9 says E3
and F1 to F4 *are* zero for a hex with no qualifying facility within 10 km, and
a query over the links relation cannot return a row for a hex that has none, so
the zeros are filled in here over the scored universe rather than lost.

The decisions in that paragraph, and the four others this script used to make
inline, are in `burden.inputs`, which has no database dependency and is tested.
This file is the SQL and the ordering.

Run it under the ingestion environment, which carries asyncpg and the
dasymetric code:

    etl/.venv/bin/python scripts/run_scoring.py
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import subprocess
import sys
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
# `burden` is deliberately not installed anywhere: it declares no dependencies
# so that the arithmetic of a run is reproducible from stdlib floats alone.
# scripts/run_validation.py reaches it the same way.
sys.path.insert(0, str(REPO_ROOT / "scoring"))
sys.path.insert(0, str(REPO_ROOT / "etl"))

import asyncpg  # noqa: E402
from burden.component import compute  # noqa: E402
from burden.confidence import HexEvidence, confidence_for_run  # noqa: E402
from burden.eligibility import eligible  # noqa: E402
from burden.inputs import (  # noqa: E402
    COMPLIANCE_QUARTERS,
    INDICATOR_IDS,
    compliance_window,
    high_cv_population_share,
    indicator_rows,
    indicator_vintages,
    loaded_indicators,
    mean_block_area_m2,
    noncompliant_quarters,
    proximity_values,
    source_vintages,
)
from burden.methodology import METHODOLOGY_VERSION  # noqa: E402
from burden.percentile import rank_indicators  # noqa: E402
from burden.pollution import POLLUTION_BURDEN  # noqa: E402
from burden.population import POPULATION_CHARACTERISTICS  # noqa: E402
from burden.score import burden_score  # noqa: E402
from pipeline.adapters.census_acs import INDICATORS as ACS_RECIPES  # noqa: E402
from pipeline.dasymetric import postgis  # noqa: E402
from pipeline.dasymetric.interpolate import (  # noqa: E402
    interpolate,
    interpolate_rate,
    max_coefficient_variation,
)
from pipeline.dasymetric.quantities import (  # noqa: E402
    coefficient_of_variation,
    proportion_moe,
)

ACS_VINTAGE = "2020-2024"

#: The published estimate suffix. `tract_demographics.variable` stores the id
#: as the Census publishes it, `B01003_001E`, and the margin under the same id
#: ending `M`; the schema's own comment gives `B17002_001E` as its example.
#: `census_acs.INDICATORS` names the *base* ids, because the adapter appends
#: the suffix when it queries and when it writes.
#:
#: Everything below therefore has to convert before it reads the table, and
#: `load_tract_estimates` matches `variable` exactly. Getting this wrong does
#: not raise: the query returns no rows, every rate comes out absent, and the
#: run reports each hex as having insufficient population data — a sentence
#: that describes a state with no census rather than a name that did not match.
ESTIMATE_SUFFIX = "E"


def _stored(variable: str) -> str:
    """A published base id as `tract_demographics` keys it."""
    return f"{variable}{ESTIMATE_SUFFIX}"


TOTAL_POPULATION = _stored("B01003_001")

# Section 8.2: the same inverse-square decay and 10 km cutoff as E3.
INTERACTION_RADIUS_M = 10_000.0

# The trailing enforcement window section 8.2 names. F2's twelve quarters are
# `burden.inputs.COMPLIANCE_QUARTERS`, because which quarters they are is a
# decision rather than a number.
ENFORCEMENT_YEARS = 5

# Indicators this run cannot produce, and why. Named rather than silently
# absent, because "no row" and "no data" look identical downstream and only one
# of them is worth acting on.
UNAVAILABLE: Mapping[str, str] = {}

#: The AirToxScreen release E1 and E2 are computed over, matching the adapter's
#: RELEASE_YEAR. A constant somebody bumps, like the ACS and TRI vintages above.
EXPOSURE_VINTAGE_YEAR = 2019

#: The TRI reporting year E3 is computed over. A constant somebody bumps, for
#: the same reason the ACS release is: which year the score describes is a
#: property of the run and should be legible in it, not inferred from whatever
#: happens to be the newest row.
TRI_REPORTING_YEAR = 2024

# F3 used to sit here, left out on the grounds that section 8.2 did not say
# whether a formal action with no penalty contributed its count or nothing at
# all. Section 8.2 now says: it contributes one, and the penalty is a log-scaled
# increment above that floor. CS-214 made that revision in the paper first, which
# is where CONTRIBUTING puts the choice, and this run implements it below.
UNDEFINED: Mapping[str, str] = {}


# ---- the run ledger ----------------------------------------------------

OPEN_RUN = """
INSERT INTO pipeline_run (git_sha, methodology_version, status, notes)
VALUES ($1, $2, 'running', $3)
RETURNING run_id
"""

CLOSE_RUN = """
UPDATE pipeline_run
   SET status = $2, finished_at = now(), scored_hexes = $3
 WHERE run_id = $1
"""

# One current run at a time: the API reads `is_current` to decide which scores
# to serve, and two would make that read ambiguous. `pipeline_run_one_current`
# enforces it.
#
# Two statements rather than one. `SET is_current = (run_id = $1)` expresses the
# same end state, but Postgres checks the index per row as the update walks the
# table: if it reaches the new run before the old one it holds two current runs
# for an instant and the unique index refuses. Which order it walks in depends
# on physical row order, so the single statement works until one day it does
# not. Clearing first is unconditionally safe.
DEMOTE_RUNS = """
UPDATE pipeline_run SET is_current = false WHERE is_current
"""

PROMOTE_RUN = """
UPDATE pipeline_run SET is_current = true WHERE run_id = $1
"""


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        # A run outside a checkout is still a run; it just cannot say which
        # code produced it, and the column is NOT NULL.
        return "unknown"


# ---- population and the ACS-derived indicators -------------------------


async def hex_population(
    conn: asyncpg.Connection, crosswalk: Any, *, acs_vintage: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Total population per hex, and the worst ACS uncertainty behind each.

    Interpolated from the ACS rather than summed from the block counts. The
    blocks are the ancillary surface that distributes the value; the value is
    the survey's, and every other indicator in this run is on the same release.
    """
    estimates = await postgis.load_tract_estimates(
        conn, variable=TOTAL_POPULATION, acs_vintage=acs_vintage
    )
    values = interpolate(crosswalk, estimates)[TOTAL_POPULATION]
    population = {h3: v.value for h3, v in values.items() if v.value is not None}
    worst_cv = {
        h3: cv
        for h3, v in values.items()
        if (cv := max_coefficient_variation([v])) is not None
    }
    return population, worst_cv


async def acs_indicators(
    conn: asyncpg.Connection, crosswalk: Any, *, acs_vintage: str
) -> tuple[dict[str, dict[str, float | None]], dict[str, list[float | None]]]:
    """S1, S2 and P1 to P5, each a rate formed once at the end.

    Section 7's rule, and the reason this goes through `interpolate_rate`
    rather than dividing per tract: both parts are interpolated as extensive
    counts and the division happens after, on the hex. Only the tracts that
    published both parts are interpolated, so a missing numerator cannot act
    as a zero over a denominator that counted everybody.

    Returns the hex values and, per tract, the coefficient of variation of each
    of these seven estimates where it has one. The second is section 12's first
    c_spatial input, which needs the uncertainty of the estimates the score is
    drawn from and not only that of the population count.
    """
    wanted: set[str] = set()
    for recipe in ACS_RECIPES:
        wanted |= set(recipe.numerator) | set(recipe.denominator)

    loaded: list[Any] = []
    for variable in sorted(wanted):
        loaded.extend(
            await postgis.load_tract_estimates(
                conn, variable=_stored(variable), acs_vintage=acs_vintage
            )
        )

    out: dict[str, dict[str, float | None]] = {}
    tract_cvs: dict[str, list[float | None]] = {}
    for recipe in ACS_RECIPES:
        # Both sides are folded the same way. P5's denominator is four
        # published income-by-cost brackets rather than one total, so a rate
        # whose denominator is a single variable is the special case here, not
        # the rule.
        numerator, _ = _summed(loaded, recipe.numerator, f"{recipe.id}_numerator")
        denominator, _ = _summed(loaded, recipe.denominator, f"{recipe.id}_denominator")
        rate = interpolate_rate(
            crosswalk,
            numerator,
            denominator,
            variable=recipe.id,
            scale=100.0,
        )
        out[recipe.id] = {h3: value.value for h3, value in rate.items()}
        for tract, cv in _tract_rate_cvs(numerator, denominator).items():
            tract_cvs.setdefault(tract, []).append(cv)
    return out, tract_cvs


def _tract_rate_cvs(
    numerator: Sequence[Any], denominator: Sequence[Any]
) -> dict[str, float | None]:
    """The coefficient of variation of one ACS rate, tract by tract.

    The same division section 7 performs on the hex, performed on the tract:
    the published margins are combined by the Census Bureau's proportion
    formula and divided by the rate. It is done here rather than read off the
    interpolated hex value because section 12 asks which *estimates* a hex's
    population was drawn from, which is a fact about the tracts underneath it.

    None where the ratio has no coefficient of variation: a tract that reported
    no margin, or a rate of zero, whose CV is undefined rather than infinite.
    """
    bottom = {e.tract_geoid: e for e in denominator}
    cvs: dict[str, float | None] = {}
    for top in numerator:
        below = bottom.get(top.tract_geoid)
        if below is None or below.estimate is None or float(below.estimate) == 0.0:
            continue
        if top.margin_of_error is None or below.margin_of_error is None:
            cvs[top.tract_geoid] = None
            continue
        margin, _ = proportion_moe(
            float(top.estimate),
            float(top.margin_of_error),
            float(below.estimate),
            float(below.margin_of_error),
        )
        cvs[top.tract_geoid] = coefficient_of_variation(
            float(top.estimate) / float(below.estimate), margin
        )
    return cvs


def _summed(
    estimates: Sequence[Any], names: Sequence[str], synthetic: str
) -> tuple[list[Any], str]:
    """Fold several published counts into one synthetic count.

    Summed here, at tract level, rather than after interpolation. The two are
    arithmetically identical because apportioning an extensive quantity is
    linear, and doing it first means never hand-building an interpolated value
    and getting one of its provenance fields wrong.

    A tract missing any part contributes nothing rather than a short sum: a
    partial numerator over a full denominator is a rate that is wrong, which is
    worse than one that is absent. Margins add in quadrature,
    as the Census documents for independently published counts.
    """
    from pipeline.dasymetric.quantities import Kind, TractEstimate

    wanted = {_stored(name) for name in names}
    parts: dict[str, list[Any]] = {}
    for estimate in estimates:
        if estimate.variable in wanted:
            parts.setdefault(estimate.tract_geoid, []).append(estimate)

    name = synthetic
    summed: list[Any] = []
    for tract, rows in parts.items():
        if len(rows) != len(wanted) or any(r.estimate is None for r in rows):
            continue
        margins = [r.margin_of_error for r in rows]
        summed.append(
            TractEstimate(
                tract_geoid=tract,
                variable=name,
                estimate=sum(float(r.estimate) for r in rows),
                margin_of_error=(
                    None
                    if any(m is None for m in margins)
                    else math.sqrt(sum(float(m) ** 2 for m in margins))
                ),
                kind=Kind.EXTENSIVE,
            )
        )
    return summed, name


# ---- the facility-proximity indicators ---------------------------------

# One pass over the links relation for all four indicators.
# `hex_facility_links_all` is the same definition of "near" the drill-down uses,
# so a facility that the panel shows contributing to a hex is a facility that
# scored it.
#
# F4 counts a facility once however many of the two flags it carries: section 8.2
# defines it as a count of generators and TSD facilities, not of designations, and
# a site that is both is still one site. The flags are populated by the ECHO
# adapter from RCRA (CS-116); before that they were false for every row, which is
# why this indicator was listed unavailable rather than computed as zero.
#
# F2's twelve quarters are counted in Python, by `burden.inputs`, and handed back
# to this query as two arrays. The count used to be `row_number() OVER (... ORDER
# BY quarter DESC) <= 12` over rows in any status but `in_compliance`, which was
# wrong twice: an `unknown` quarter is an unmonitored one and counted as a
# violation, so a facility nobody inspected scored the maximum 12 of 12; and the
# last twelve *rows* are the last twelve quarters only while one program is
# loaded, because the table is keyed by facility, quarter and program.
#
# F3 weights each formal action by `1 + log10(1 + penalty)`, which is section 8.2
# as revised by CS-214: the count is the floor and the penalty is the increment
# above it, so an action settled without a monetary assessment contributes one
# rather than nothing. `COALESCE(penalty_usd, 0)` is what makes an unreported
# penalty a zero increment rather than a null that would erase the whole action;
# the bulk air feed reports no penalty figure for any Louisiana facility, so today
# that is every row and F3 reduces to the decayed count. The window is the
# trailing five years of section 8.2, taken from the run's own as-of date rather
# than from `current_date`, for the reason `facilities_near_hex` takes it as a
# parameter: a run scoring last night's data should ask about that night's five
# years, not about whenever the query happens to execute. It is bounded at both
# ends for the same reason. An action dated after the run is either a clock
# problem upstream or a scheduled future settlement, and neither belongs in a
# trailing window; unbounded above, a re-run of an old as-of date would quietly
# include everything since.
FACILITY_INDICATORS = """
SELECT l.h3::text AS h3,
       sum(l.decay_weight) FILTER (WHERE f.is_major_source OR f.has_title_v) AS f1,
       sum(l.decay_weight * COALESCE(q.bad_quarters, 0))                     AS f2,
       sum(l.decay_weight * COALESCE(e.action_weight, 0))                    AS f3,
       sum(l.decay_weight) FILTER (WHERE f.is_rcra_lqg OR f.is_rcra_tsdf)     AS f4
  FROM hex_facility_links_all($1) l
  JOIN facility f ON f.facility_id = l.facility_id
  LEFT JOIN unnest($2::text[], $3::int[]) AS q(facility_id, bad_quarters)
         ON q.facility_id = f.facility_id
  LEFT JOIN (
      SELECT facility_id,
             sum(1.0 + log(10.0, 1.0 + COALESCE(penalty_usd, 0)))::float8 AS action_weight
        FROM enforcement_action
       WHERE is_formal
         AND settled_on IS NOT NULL
         AND settled_on >= ($4::date - make_interval(years => $5))::date
         AND settled_on <= $4::date
       GROUP BY facility_id
  ) e ON e.facility_id = f.facility_id
 GROUP BY l.h3
"""

#: The quarters F2 reads, in the window and in every status. Which of them count
#: is `burden.inputs.noncompliant_quarters`, not this query.
COMPLIANCE_ROWS = """
SELECT facility_id, quarter, status
  FROM facility_compliance_quarter
 WHERE quarter BETWEEN $1 AND $2
"""


async def facility_indicators(
    conn: asyncpg.Connection, *, as_of: date, hexes: Collection[str], loaded: bool
) -> dict[str, dict[str, float | None]]:
    """F1 to F4 over the scored hexes, zero where no facility qualifies.

    `loaded` says whether ECHO is in this database at all. Without it there is
    nothing to count and every hex is absent; with it, a hex the links relation
    never mentions has no facility within 10 km and is a zero.
    """
    names = ("F1", "F2", "F3", "F4")
    if not loaded:
        return {name: dict.fromkeys(hexes) for name in names}

    window = compliance_window(as_of, quarters=COMPLIANCE_QUARTERS)
    bad_quarters = noncompliant_quarters(
        (
            (str(row["facility_id"]), row["quarter"], str(row["status"]))
            for row in await conn.fetch(COMPLIANCE_ROWS, window[0], window[-1])
        ),
        as_of=as_of,
    )
    facility_ids = sorted(bad_quarters)

    rows = await conn.fetch(
        FACILITY_INDICATORS,
        INTERACTION_RADIUS_M,
        facility_ids,
        [bad_quarters[facility_id] for facility_id in facility_ids],
        as_of,
        ENFORCEMENT_YEARS,
    )
    sums: dict[str, dict[str, float | None]] = {name: {} for name in names}
    for row in rows:
        for name in names:
            value = row[name.lower()]
            sums[name][row["h3"]] = None if value is None else float(value)
    return {name: proximity_values(sums[name], hexes=hexes, loaded=True) for name in names}


# Section 8.1. The numerator is `facility_release_toxicity.toxicity_weighted_lb`,
# which is sum(w_c * m_{f,c}) over a facility's chemicals for one reporting
# year; the denominator is the same decayed distance F1 to F4 use, so E3 and the
# environmental-effects indicators agree about which facilities reach a hexagon
# and by how much.
#
# One reporting year, not all of them. TRI publishes annually and a sum across
# years would count a facility's steady-state emissions once per year of
# history, which is a different quantity from the annual release the indicator
# names.
RELEASE_PROXIMITY = """
SELECT l.h3::text AS h3,
       sum(l.decay_weight * t.toxicity_weighted_lb)::float8 AS e3
  FROM hex_facility_links_all($1) l
  JOIN facility_release_toxicity t ON t.facility_id = l.facility_id
 WHERE t.reporting_year = $2
 GROUP BY l.h3
"""

# E4 is already per hexagon: the OpenAQ adapter does the interpolation and the
# sparse-coverage decision at ingest, because how far the nearest monitor is
# belongs with the measurement rather than with the scoring. `observed` is the
# section 11 flag, and a hex without it carries a real distance and no value.
#: The distance behind c_monitor. One row per hexagon whatever E4 came out as:
#: a hex with no reading still has a nearest monitor, and how far it is is the
#: whole point of the term.
NEAREST_MONITOR = """
SELECT h3::text AS h3, min(nearest_monitor_km)::float8 AS km
  FROM hex_air_quality
 GROUP BY h3
"""

MEASURED_PM25 = """
SELECT h3::text AS h3, value::float8 AS e4
  FROM hex_air_quality
 WHERE parameter = 'pm25' AND observed AND value IS NOT NULL
"""


#: E1 and E2 as stored: one row per 2020 tract, already crossed from the 2010
#: geography AirToxScreen publishes on. See pipeline.tract_vintage.
TRACT_EXPOSURE = """
SELECT tract_geoid, cancer_risk_per_million, respiratory_hazard_index
  FROM tract_exposure
 WHERE vintage_year = $1
"""


async def modelled_exposure(
    conn: asyncpg.Connection, crosswalk: Any, *, vintage_year: int
) -> dict[str, dict[str, float | None]]:
    """E1 and E2, interpolated from tracts onto hexagons.

    Intensive: a modelled risk per million is a rate and does not sum across
    space, so section 7 combines it as a population-weighted mean over the
    crosswalk rather than apportioning it. Passing Kind.EXTENSIVE here instead
    would halve a community's exposure wherever a tract happens to span two
    hexagons, which is the error section 7 names as the most common one in this
    step.

    No margin of error: AirToxScreen publishes a modelled surface, not a survey,
    and `None` says that rather than claiming a margin of zero.
    """
    from pipeline.dasymetric.quantities import Kind, TractEstimate

    rows = await conn.fetch(TRACT_EXPOSURE, vintage_year)
    estimates = [
        TractEstimate(
            tract_geoid=str(row["tract_geoid"]),
            variable=name,
            estimate=None if row[column] is None else float(row[column]),
            margin_of_error=None,
            kind=Kind.INTENSIVE,
        )
        for row in rows
        for name, column in (
            ("E1", "cancer_risk_per_million"),
            ("E2", "respiratory_hazard_index"),
        )
    ]
    interpolated = interpolate(crosswalk, estimates)
    return {
        name: {h3: value.value for h3, value in interpolated.get(name, {}).items()}
        for name in ("E1", "E2")
    }


async def exposure_indicators(
    conn: asyncpg.Connection, *, tri_year: int, hexes: Collection[str], e3_loaded: bool
) -> dict[str, dict[str, float | None]]:
    """E3 and E4, the two point-source Exposures indicators.

    E3 is a proximity indicator and reads like F1 to F4: a hexagon with no
    reporting facility within 10 km is a zero, because the facilities were
    looked for. The query inner-joins the toxicity view, so a hexagon with
    nothing near it and a hexagon near a facility that reported no weighted
    release are the same missing row, and both are that zero. Only TRI or the
    RSEI weights being absent from this database makes E3 an absence, and
    `e3_loaded` is that question: without the weights the view's sum is zero for
    every facility, which is an indicator carrying no information rather than a
    state with no toxic releases.

    E4 is the opposite and section 8.1 is emphatic about it: a hexagon with no
    monitor within 25 km has no value and never a zero, so nothing is filled in
    here.
    """
    e3_sums: dict[str, float | None] = {}
    if e3_loaded:
        for row in await conn.fetch(RELEASE_PROXIMITY, INTERACTION_RADIUS_M, tri_year):
            e3_sums[row["h3"]] = None if row["e3"] is None else float(row["e3"])

    e4: dict[str, float | None] = {
        row["h3"]: float(row["e4"]) for row in await conn.fetch(MEASURED_PM25)
    }
    return {
        "E3": proximity_values(e3_sums, hexes=hexes, loaded=e3_loaded),
        "E4": e4,
    }


# ---- writing the three tables ------------------------------------------

# `households` and the three race shares are left unset. The race variables are
# loaded, but into `tract_race_ethnicity`, which section 14 reads and no
# indicator may: filling them here would put them one careless join away from
# the arithmetic. See the ACS adapter's RACE_SEPARATION_GAP.
WRITE_DEMOGRAPHICS = """
INSERT INTO hex_demographics
    (run_id, h3, population, under_5_pct, over_64_pct, poverty_200pct,
     no_hs_diploma_pct, linguistic_isolation_pct, unemployment_pct,
     housing_burden_pct, max_coefficient_variation, mean_block_area_m2,
     acs_vintage)
VALUES ($1, $2::h3_cell, $3::float8::numeric, $4::float8::numeric,
        $5::float8::numeric, $6::float8::numeric, $7::float8::numeric,
        $8::float8::numeric, $9::float8::numeric, $10::float8::numeric,
        $11::float8::numeric, $12::float8::numeric, $13)
"""

WRITE_INDICATOR = """
INSERT INTO hex_indicator (run_id, h3, indicator_id, value, percentile, observed)
VALUES ($1, $2::h3_cell, $3, $4::float8::numeric, $5::float8::numeric, $6)
"""

WRITE_SCORE = """
INSERT INTO hex_score
    (run_id, h3, score, percentile, pollution_burden, population_characteristics,
     exposures_mean, env_effects_mean, sensitive_mean, socioeconomic_mean,
     confidence, confidence_band, c_coverage, c_recency, c_spatial, c_monitor,
     nearest_monitor_km, no_score_reason)
VALUES ($1, $2::h3_cell, $3::float8::numeric, $4::float8::numeric,
        $5::float8::numeric, $6::float8::numeric, $7::float8::numeric,
        $8::float8::numeric, $9::float8::numeric, $10::float8::numeric,
        $11::float8::numeric, $12, $13::float8::numeric, $14::float8::numeric,
        $15::float8::numeric, $16::float8::numeric, $17::float8::numeric, $18)
"""


#: The snapshots this run read, one row per source and snapshot.
#:
#: Not `max(vintage_end)` per source, which is what this used to be. The run
#: pins the ACS release, the AirToxScreen year and the TRI reporting year, so
#: the newest snapshot of a source is frequently not the one it scored, and
#: section 12's recency term is then measuring a dataset nobody used. Each
#: branch below names the rows the run actually reads.
#:
#: `s.source = c.source` is not decoration either: TRI creates `facility` rows
#: for reporters ECHO has never seen, so the facility table alone would date the
#: TRI snapshot from whenever those facilities were last written.
SNAPSHOTS_READ = """
WITH consulted(source, snapshot_id) AS (
    SELECT 'acs', snapshot_id FROM tract_demographics WHERE acs_vintage = $1
    UNION
    SELECT 'airtoxscreen', snapshot_id FROM tract_exposure WHERE vintage_year = $2
    UNION
    SELECT 'tri', snapshot_id FROM tri_release WHERE reporting_year = $3
    UNION
    SELECT 'rsei', w.snapshot_id
      FROM chemical_toxicity_weight w
     WHERE w.cas_number IN (SELECT cas_number FROM tri_release WHERE reporting_year = $3)
    UNION
    SELECT 'openaq', snapshot_id FROM hex_air_quality WHERE parameter = 'pm25'
    UNION
    SELECT 'echo', snapshot_id FROM facility
    UNION
    SELECT 'echo', snapshot_id FROM facility_compliance_quarter
    UNION
    SELECT 'echo', snapshot_id FROM enforcement_action
)
SELECT s.source, s.vintage_end
  FROM consulted c
  JOIN source_snapshot s
    ON s.snapshot_id = c.snapshot_id AND s.source = c.source
"""


async def snapshots_read(
    conn: asyncpg.Connection, *, acs_vintage: str, exposure_year: int, tri_year: int
) -> list[tuple[str, date]]:
    rows = await conn.fetch(SNAPSHOTS_READ, acs_vintage, exposure_year, tri_year)
    return [(str(row["source"]), row["vintage_end"]) for row in rows]


WRITE_DISTRIBUTION = """
INSERT INTO indicator_distribution
    (run_id, indicator_id, n_hexes, n_zero, min_value, max_value, breakpoints, vintage_end)
VALUES ($1, $2, $3, $4, $5::float8::numeric, $6::float8::numeric,
        $7::float8[]::numeric[], $8)
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promote",
        action="store_true",
        help="make this the run the API serves once it succeeds",
    )
    parser.add_argument(
        "--acs-vintage", default=ACS_VINTAGE, help="the release to score against"
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(url, command_timeout=1800)
    try:
        return await score_run(conn, promote=args.promote, acs_vintage=args.acs_vintage)
    finally:
        await conn.close()


async def score_run(
    conn: asyncpg.Connection, *, promote: bool, acs_vintage: str = ACS_VINTAGE
) -> int:
    # One as-of date for the whole run. Section 12's recency term and section
    # 8.2's trailing enforcement window are both measured from it, and a run that
    # asked the clock twice could straddle midnight and date them differently.
    as_of = datetime.now(UTC).date()

    # Which sources this database holds, read before anything is computed: it
    # decides both what an indicator's vintage is and whether an indicator with
    # no nearby facility is a zero or an absence.
    per_source = source_vintages(
        await snapshots_read(
            conn,
            acs_vintage=acs_vintage,
            exposure_year=EXPOSURE_VINTAGE_YEAR,
            tri_year=TRI_REPORTING_YEAR,
        )
    )
    vintages = indicator_vintages(per_source)
    loaded = loaded_indicators(per_source)
    missing = sorted(set(INDICATOR_IDS) - loaded)
    print(
        f"methodology {METHODOLOGY_VERSION}; ACS {acs_vintage}; "
        f"{len(missing)} indicators have no source loaded: {', '.join(missing) or 'none'}"
    )
    for indicator, reason in sorted({**UNAVAILABLE, **UNDEFINED}.items()):
        print(f"  {indicator}: {reason}")

    crosswalk = await postgis.load_crosswalk(conn)
    population, worst_cv = await hex_population(conn, crosswalk, acs_vintage=acs_vintage)
    print(f"population interpolated onto {len(population)} hexes")

    # The whole grid, not just the hexes with people: a cell the run knows
    # about and did not score has to say why, and the map draws it differently
    # rather than leaving a hole.
    grid = [
        row["h3"]
        for row in await conn.fetch("SELECT h3::text AS h3 FROM hex ORDER BY h3")
    ]
    cover = {h3: population.get(h3) for h3 in grid}

    eligibility = eligible(cover)
    scored = eligibility.scored
    print(
        f"section 5: {len(scored)} hexes scored, {len(eligibility.excluded)} excluded"
    )
    if not scored:
        print("nothing to score", file=sys.stderr)
        return 1

    values: dict[str, dict[str, float | None]] = {}
    acs_values, tract_cvs = await acs_indicators(conn, crosswalk, acs_vintage=acs_vintage)
    values.update(acs_values)
    values.update(
        await facility_indicators(
            conn, as_of=as_of, hexes=scored, loaded="F1" in loaded
        )
    )
    values.update(
        await exposure_indicators(
            conn, tri_year=TRI_REPORTING_YEAR, hexes=scored, e3_loaded="E3" in loaded
        )
    )
    values.update(
        await modelled_exposure(conn, crosswalk, vintage_year=EXPOSURE_VINTAGE_YEAR)
    )
    present = sorted(
        indicator
        for indicator, row in values.items()
        if any(row.get(h3) is not None for h3 in scored)
    )
    print(f"{len(present)} indicators computed: {', '.join(present)}")

    rankings = rank_indicators(values, scored=scored)
    pollution = compute(POLLUTION_BURDEN, rankings, scored=scored)
    characteristics = compute(POPULATION_CHARACTERISTICS, rankings, scored=scored)

    observed_by_hex = {
        h3: frozenset(i for i in present if values[i].get(h3) is not None)
        for h3 in scored
    }
    # Section 12's two spatial inputs, both over the tracts that actually meet
    # this hex. `mean_block_area` used to be a dict comprehension over every
    # crosswalk row, which kept whichever tract came last for each hex and so
    # scored a hex split between a town and a marsh on one of the two at random.
    mean_block_area = {h3: mean_block_area_m2(crosswalk.for_hex(h3)) for h3 in scored}
    high_cv_share = {
        h3: high_cv_population_share(crosswalk.for_hex(h3), tract_cvs) for h3 in scored
    }
    # Section 12's c_monitor term. The OpenAQ adapter already computed the
    # distance to the nearest monitor for every hexagon, including the ones it
    # found no value for, because how far away the nearest sensor is belongs
    # with the measurement. Passing None here instead pins the term at its 0.05
    # floor, and under a geometric mean that alone caps every hex's confidence
    # near 0.55 before the other three terms are applied.
    nearest_monitor = {
        row["h3"]: float(row["km"]) for row in await conn.fetch(NEAREST_MONITOR)
    }
    evidence = [
        HexEvidence(
            h3=h3,
            observed_indicators=observed_by_hex[h3],
            high_cv_population_share=high_cv_share[h3],
            mean_block_area_km2=(
                area / 1e6 if (area := mean_block_area.get(h3)) else None
            ),
            nearest_monitor_km=nearest_monitor.get(h3),
        )
        for h3 in scored
    ]
    confidence = confidence_for_run(evidence, vintages=vintages, as_of=as_of)

    run = burden_score(
        eligibility=eligibility,
        pollution=pollution,
        population=characteristics,
        confidence=confidence,
    )

    run_id: int = await conn.fetchval(
        OPEN_RUN,
        git_sha(),
        METHODOLOGY_VERSION,
        f"{len(present)} of 15 indicators; no source loaded for {', '.join(missing) or 'none'}",
    )

    try:
        async with conn.transaction():
            await _write(
                conn,
                run_id,
                run,
                rankings,
                values,
                population,
                worst_cv,
                mean_block_area,
                acs_vintage,
            )
            await _write_distributions(conn, run_id, rankings, vintages)
        await conn.execute(CLOSE_RUN, run_id, "succeeded", len(scored))
        if promote:
            async with conn.transaction():
                await conn.execute(DEMOTE_RUNS)
                await conn.execute(PROMOTE_RUN, run_id)
    except BaseException:
        await conn.execute(CLOSE_RUN, run_id, "failed", None)
        raise

    print(
        f"run {run_id}: wrote {len(run.hexes)} hex_score rows, {len(scored)} of them scored"
    )
    if promote:
        print(f"run {run_id} is now the current run")
    return 0


async def _write_distributions(
    conn: asyncpg.Connection,
    run_id: int,
    rankings: Mapping[str, Any],
    vintages: Mapping[str, date],
) -> None:
    """The distribution each indicator's percentiles were ranked against.

    A percentile means nothing beside the distribution that produced it, which
    is why migration 0009 stores one row per indicator per run. The ranking
    already carries it and this run was discarding it: the table has been empty
    on every run so far, so a stored score could not be re-derived and the
    section 9 denominators were unrecoverable after the fact.

    An indicator with no vintage is skipped rather than given today's date.
    `vintage_end` is NOT NULL and drives the recency term; inventing one would
    make a source of unknown age read as fresh, which is the single thing
    section 12 says a recency term must never do.
    """
    rows = [
        (
            run_id,
            indicator,
            ranking.distribution.n,
            ranking.distribution.n_zero,
            ranking.distribution.min_value,
            ranking.distribution.max_value,
            list(ranking.distribution.breakpoints),
            vintages[indicator],
        )
        for indicator, ranking in sorted(rankings.items())
        if indicator in vintages
    ]
    if rows:
        await conn.executemany(WRITE_DISTRIBUTION, rows)

    unknown = sorted(set(rankings) - set(vintages))
    if unknown:
        print(f"  no vintage for {', '.join(unknown)}; distribution rows omitted")


async def _write(
    conn: asyncpg.Connection,
    run_id: int,
    run: Any,
    rankings: Mapping[str, Any],
    values: Mapping[str, Mapping[str, float | None]],
    population: Mapping[str, float],
    worst_cv: Mapping[str, float],
    mean_block_area: Mapping[str, float | None],
    acs_vintage: str,
) -> None:
    scored = {row.h3 for row in run.hexes if row.score is not None}

    rates = {
        name: values.get(name, {})
        for name in ("S1", "S2", "P1", "P2", "P3", "P4", "P5")
    }
    await conn.executemany(
        WRITE_DEMOGRAPHICS,
        [
            (
                run_id,
                h3,
                population[h3],
                rates["S1"].get(h3),
                rates["S2"].get(h3),
                rates["P1"].get(h3),
                rates["P2"].get(h3),
                rates["P3"].get(h3),
                rates["P4"].get(h3),
                rates["P5"].get(h3),
                worst_cv.get(h3),
                mean_block_area.get(h3),
                acs_vintage,
            )
            for h3 in sorted(scored)
        ],
    )

    # All fifteen for every scored hex, observed or not. Section 11 rule 5 asks
    # for every dropped indicator to be recorded per hex, and the panel already
    # renders an absent one; writing only the observed rows left `observed =
    # false` a state no run could produce.
    percentiles: Mapping[str, Mapping[str, float | None]] = {
        indicator: {row.h3: row.percentile for row in ranking.hexes}
        for indicator, ranking in rankings.items()
    }
    await conn.executemany(
        WRITE_INDICATOR,
        [
            (run_id, h3, indicator, value, percentile, observed)
            for h3, indicator, value, percentile, observed in indicator_rows(
                values, percentiles, hexes=scored
            )
        ],
    )

    await conn.executemany(
        WRITE_SCORE,
        [
            (
                run_id,
                row.h3,
                row.score,
                row.percentile,
                row.pollution_burden,
                row.population_characteristics,
                row.exposures_mean,
                row.env_effects_mean,
                row.sensitive_mean,
                row.socioeconomic_mean,
                row.confidence.value if row.confidence else None,
                row.confidence.band if row.confidence else None,
                row.confidence.c_coverage if row.confidence else None,
                row.confidence.c_recency if row.confidence else None,
                row.confidence.c_spatial if row.confidence else None,
                row.confidence.c_monitor if row.confidence else None,
                row.confidence.nearest_monitor_km if row.confidence else None,
                row.no_score_reason,
            )
            for row in run.hexes
        ],
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
