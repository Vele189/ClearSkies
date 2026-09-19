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

**What is missing is missing, not zero.** Four indicators have no source data
in this database, and every one of them is left out rather than filled in.
`component.compute` drops an absent indicator, re-weights the groups that
survive, and records the loss as a confidence penalty. A zero would instead say
"measured, and there is none", which for an unmonitored place is the exact
failure this project exists to avoid.

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
from collections.abc import Mapping, Sequence
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
from burden.methodology import METHODOLOGY_VERSION  # noqa: E402
from burden.percentile import rank_indicators  # noqa: E402
from burden.pollution import POLLUTION_BURDEN  # noqa: E402
from burden.population import POPULATION_CHARACTERISTICS  # noqa: E402
from burden.score import burden_score  # noqa: E402
from pipeline.adapters.census_acs import INDICATORS as ACS_RECIPES  # noqa: E402
from pipeline.dasymetric import postgis  # noqa: E402
from pipeline.dasymetric.interpolate import (  # noqa: E402
    derive_rate,
    interpolate,
    max_coefficient_variation,
)

ACS_VINTAGE = "2020-2024"
TOTAL_POPULATION = "B01003_001"

# Section 8.2: the same inverse-square decay and 10 km cutoff as E3.
INTERACTION_RADIUS_M = 10_000.0

# The trailing windows section 8.2 names.
COMPLIANCE_QUARTERS = 12
ENFORCEMENT_YEARS = 5

# Indicators this run cannot produce, and why. Named rather than silently
# absent, because "no row" and "no data" look identical downstream and only one
# of them is worth acting on.
UNAVAILABLE: Mapping[str, str] = {
    "E1": "AirToxScreen is not loaded: its 2010 tracts do not all exist in the 2020 set",
    "E2": "AirToxScreen is not loaded: its 2010 tracts do not all exist in the 2020 set",
    "E3": "chemical_toxicity_weight is empty, so RSEI weighting cannot be applied",
    "E4": "OpenAQ exceeded its partial-failure tolerance and loaded nothing",
}

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
# to serve, and two would make that read ambiguous.
PROMOTE_RUN = """
UPDATE pipeline_run SET is_current = (run_id = $1)
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
    conn: asyncpg.Connection, crosswalk: Any
) -> tuple[dict[str, float], dict[str, float]]:
    """Total population per hex, and the worst ACS uncertainty behind each.

    Interpolated from the ACS rather than summed from the block counts. The
    blocks are the ancillary surface that distributes the value; the value is
    the survey's, and every other indicator in this run is on the same release.
    """
    estimates = await postgis.load_tract_estimates(
        conn, variable=TOTAL_POPULATION, acs_vintage=ACS_VINTAGE
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
    conn: asyncpg.Connection, crosswalk: Any
) -> dict[str, dict[str, float | None]]:
    """S1, S2 and P1 to P5, each a rate formed once at the end.

    Section 7's rule, and the reason this goes through `derive_rate` rather
    than dividing per tract: both parts are interpolated as extensive counts
    and the division happens after, on the hex.
    """
    wanted: set[str] = set()
    for recipe in ACS_RECIPES:
        wanted |= set(recipe.numerator) | set(recipe.denominator)

    loaded: list[Any] = []
    for variable in sorted(wanted):
        loaded.extend(
            await postgis.load_tract_estimates(
                conn, variable=variable, acs_vintage=ACS_VINTAGE
            )
        )

    out: dict[str, dict[str, float | None]] = {}
    for recipe in ACS_RECIPES:
        # Both sides are folded the same way. P5's denominator is four
        # published income-by-cost brackets rather than one total, so a rate
        # whose denominator is a single variable is the special case here, not
        # the rule.
        numerator, numerator_name = _summed(loaded, recipe.numerator, f"{recipe.id}_numerator")
        denominator, denominator_name = _summed(
            loaded, recipe.denominator, f"{recipe.id}_denominator"
        )
        interpolated = interpolate(crosswalk, [*numerator, *denominator])
        rate = derive_rate(
            interpolated.get(numerator_name, {}),
            interpolated.get(denominator_name, {}),
            variable=recipe.id,
            scale=100.0,
        )
        out[recipe.id] = {h3: value.value for h3, value in rate.items()}
    return out


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

    wanted = set(names)
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
# years, not about whenever the query happens to execute.
FACILITY_INDICATORS = """
SELECT l.h3::text AS h3,
       sum(l.decay_weight) FILTER (WHERE f.is_major_source OR f.has_title_v) AS f1,
       sum(l.decay_weight * COALESCE(q.bad_quarters, 0))                     AS f2,
       sum(l.decay_weight * COALESCE(e.action_weight, 0))                    AS f3,
       sum(l.decay_weight) FILTER (WHERE f.is_rcra_lqg OR f.is_rcra_tsdf)     AS f4
  FROM hex_facility_links_all($1) l
  JOIN facility f ON f.facility_id = l.facility_id
  LEFT JOIN (
      SELECT facility_id, count(*) AS bad_quarters
        FROM (
            SELECT facility_id, status,
                   row_number() OVER (PARTITION BY facility_id ORDER BY quarter DESC) AS recency
              FROM facility_compliance_quarter
        ) ranked
       WHERE recency <= $2 AND status <> 'in_compliance'
       GROUP BY facility_id
  ) q ON q.facility_id = f.facility_id
  LEFT JOIN (
      SELECT facility_id,
             sum(1.0 + log(10.0, 1.0 + COALESCE(penalty_usd, 0)))::float8 AS action_weight
        FROM enforcement_action
       WHERE is_formal
         AND settled_on IS NOT NULL
         AND settled_on >= ($3::date - make_interval(years => $4))::date
       GROUP BY facility_id
  ) e ON e.facility_id = f.facility_id
 GROUP BY l.h3
"""


async def facility_indicators(
    conn: asyncpg.Connection, *, as_of: date
) -> dict[str, dict[str, float | None]]:
    rows = await conn.fetch(
        FACILITY_INDICATORS,
        INTERACTION_RADIUS_M,
        COMPLIANCE_QUARTERS,
        as_of,
        ENFORCEMENT_YEARS,
    )
    f1: dict[str, float | None] = {}
    f2: dict[str, float | None] = {}
    f3: dict[str, float | None] = {}
    f4: dict[str, float | None] = {}
    for row in rows:
        # A null sum means no facility within the radius matched the filter, which
        # for a proximity count is an observed zero rather than an absence: the
        # facilities were looked for and there are none. An absence here would be a
        # hex the links relation says nothing about, and those get no row at all.
        # F3 reads the same way: nearby facilities with no formal action in the
        # window is a measured absence of enforcement, not an unasked question.
        f1[row["h3"]] = float(row["f1"]) if row["f1"] is not None else 0.0
        f2[row["h3"]] = float(row["f2"]) if row["f2"] is not None else 0.0
        f3[row["h3"]] = float(row["f3"]) if row["f3"] is not None else 0.0
        f4[row["h3"]] = float(row["f4"]) if row["f4"] is not None else 0.0
    return {"F1": f1, "F2": f2, "F3": f3, "F4": f4}


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


async def source_vintages(conn: asyncpg.Connection) -> dict[str, date]:
    """The newest vintage_end per source, for section 12's recency term."""
    rows = await conn.fetch(
        "SELECT source, max(vintage_end) AS vintage_end FROM source_snapshot GROUP BY source"
    )
    return {row["source"]: row["vintage_end"] for row in rows}


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
        return await score_run(conn, promote=args.promote)
    finally:
        await conn.close()


async def score_run(conn: asyncpg.Connection, *, promote: bool) -> int:
    # One as-of date for the whole run. Section 12's recency term and section
    # 8.2's trailing enforcement window are both measured from it, and a run that
    # asked the clock twice could straddle midnight and date them differently.
    as_of = datetime.now(UTC).date()

    missing = sorted({**UNAVAILABLE, **UNDEFINED})
    print(f"methodology {METHODOLOGY_VERSION}; {len(missing)} indicators unavailable: {', '.join(missing)}")
    for indicator, reason in sorted({**UNAVAILABLE, **UNDEFINED}.items()):
        print(f"  {indicator}: {reason}")

    crosswalk = await postgis.load_crosswalk(conn)
    population, worst_cv = await hex_population(conn, crosswalk)
    print(f"population interpolated onto {len(population)} hexes")

    # The whole grid, not just the hexes with people: a cell the run knows
    # about and did not score has to say why, and the map draws it differently
    # rather than leaving a hole.
    grid = [row["h3"] for row in await conn.fetch("SELECT h3::text AS h3 FROM hex ORDER BY h3")]
    cover = {h3: population.get(h3) for h3 in grid}

    eligibility = eligible(cover)
    scored = eligibility.scored
    print(f"section 5: {len(scored)} hexes scored, {len(eligibility.excluded)} excluded")
    if not scored:
        print("nothing to score", file=sys.stderr)
        return 1

    values: dict[str, dict[str, float | None]] = {}
    values.update(await acs_indicators(conn, crosswalk))
    values.update(await facility_indicators(conn, as_of=as_of))
    present = sorted(values)
    print(f"{len(present)} indicators computed: {', '.join(present)}")

    rankings = rank_indicators(values, scored=scored)
    pollution = compute(POLLUTION_BURDEN, rankings, scored=scored)
    characteristics = compute(POPULATION_CHARACTERISTICS, rankings, scored=scored)

    vintages = await source_vintages(conn)
    observed_by_hex = {
        h3: frozenset(i for i in present if values[i].get(h3) is not None) for h3 in scored
    }
    mean_block_area = {
        h3: area
        for h3, area in (
            (w.h3, w.mean_block_area_m2) for w in crosswalk.weights
        )
    }
    evidence = [
        HexEvidence(
            h3=h3,
            observed_indicators=observed_by_hex[h3],
            high_cv_population_share=min(worst_cv.get(h3, 0.0), 1.0),
            mean_block_area_km2=(
                mean_block_area[h3] / 1e6 if mean_block_area.get(h3) else None
            ),
            nearest_monitor_km=None,
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
        f"{len(present)} of 15 indicators; missing {', '.join(missing)}",
    )

    try:
        async with conn.transaction():
            await _write(conn, run_id, run, rankings, values, population, worst_cv, mean_block_area)
        await conn.execute(CLOSE_RUN, run_id, "succeeded", len(scored))
        if promote:
            await conn.execute(PROMOTE_RUN, run_id)
    except BaseException:
        await conn.execute(CLOSE_RUN, run_id, "failed", None)
        raise

    print(f"run {run_id}: wrote {len(run.hexes)} hex_score rows, {len(scored)} of them scored")
    if promote:
        print(f"run {run_id} is now the current run")
    return 0


async def _write(
    conn: asyncpg.Connection,
    run_id: int,
    run: Any,
    rankings: Mapping[str, Any],
    values: Mapping[str, Mapping[str, float | None]],
    population: Mapping[str, float],
    worst_cv: Mapping[str, float],
    mean_block_area: Mapping[str, float],
) -> None:
    scored = {row.h3 for row in run.hexes if row.score is not None}

    rates = {name: values.get(name, {}) for name in ("S1", "S2", "P1", "P2", "P3", "P4", "P5")}
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
                ACS_VINTAGE,
            )
            for h3 in sorted(scored)
        ],
    )

    percentiles = {
        indicator: {row.h3: row.percentile for row in ranking.hexes}
        for indicator, ranking in rankings.items()
    }
    await conn.executemany(
        WRITE_INDICATOR,
        [
            (run_id, h3, indicator, value, percentiles[indicator].get(h3), value is not None)
            for indicator in sorted(values)
            for h3 in sorted(scored)
            if (value := values[indicator].get(h3)) is not None
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
