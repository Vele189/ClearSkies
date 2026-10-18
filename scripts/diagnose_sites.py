#!/usr/bin/env python3
"""Break a run's validation result down to the components behind it.

`run_validation.py` says which sites passed. This says why: for every scored
cell of every active pilot-state site it prints the percentile, the two
components, the four subgroup means, the confidence terms, and the mean
indicator percentile across the site's cells. It also prints which indicators
decide rank among the most polluted hexes, which is where the negative
controls fail.

It reads; it never writes. It is a diagnostic, not a gate, and nothing here
may be used to choose a weight -- section 13.7 applies.

    set -a; . ./.env; set +a
    api/.venv/bin/python scripts/diagnose_sites.py              # promoted run
    api/.venv/bin/python scripts/diagnose_sites.py --run-id 81
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SITES = REPO_ROOT / "docs" / "validation" / "sites.yml"

CELLS = """
SELECT s.h3, s.percentile, s.score, s.pollution_burden, s.population_characteristics,
       s.exposures_mean, s.env_effects_mean, s.sensitive_mean, s.socioeconomic_mean,
       s.confidence, s.confidence_band, s.c_coverage, s.c_recency, s.c_spatial,
       s.c_monitor, s.no_score_reason, d.population
  FROM hex_score s LEFT JOIN hex_demographics d ON d.h3 = s.h3
 WHERE s.run_id = $1 AND s.h3 = ANY($2::text[]) AND s.score IS NOT NULL
 ORDER BY s.percentile DESC
"""

INDICATORS = """
SELECT indicator_id, avg(percentile) AS pct, bool_and(observed) AS observed
  FROM hex_indicator
 WHERE run_id = $1 AND h3 = ANY($2::text[])
 GROUP BY 1 ORDER BY 1
"""

# Among the confident hexes whose Pollution Burden is near its ceiling, which
# indicator percentiles track the final percentile. This is where an affluent
# neighbourhood beside industry is told apart from a burdened one, or is not.
RANK_DRIVERS = """
SELECT i.indicator_id, corr(i.percentile, s.percentile) AS r, count(*) AS n
  FROM hex_indicator i JOIN hex_score s ON s.h3 = i.h3 AND s.run_id = i.run_id
 WHERE i.run_id = $1 AND s.confidence_band <> 'insufficient'
   AND s.pollution_burden >= $2
 GROUP BY 1 ORDER BY 2 DESC
"""


def _f(value: object, digits: int = 1) -> str:
    return "-" if value is None else f"{float(value):.{digits}f}"


def pilot_sites() -> list[dict]:
    data = yaml.safe_load(SITES.read_text())
    return [
        site
        for value in data.values()
        if isinstance(value, list)
        for site in value
        if isinstance(site, dict)
        and site.get("h3_cells")
        and site.get("state", "LA") == "LA"
        and site.get("active", True)
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", type=int, help="defaults to the promoted run")
    parser.add_argument("--pb-floor", type=float, default=8.0,
                        help="Pollution Burden at or above which rank drivers are measured")
    args = parser.parse_args()

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        run_id = args.run_id or await conn.fetchval(
            "SELECT run_id FROM pipeline_run WHERE is_current"
        )
        print(f"run {run_id}")

        for site in pilot_sites():
            print(f"\n## {site['id']} {site['name']}")
            print(
                "cell     pct   PB   PC  |  E    F    S    P   "
                "| band          conf  cov  rec  spa  mon | pop"
            )
            for r in await conn.fetch(CELLS, run_id, site["h3_cells"]):
                print(
                    f"{r['h3'][-7:]} {_f(r['percentile']):>5} {_f(r['pollution_burden']):>4}"
                    f" {_f(r['population_characteristics']):>4} | {_f(r['exposures_mean']):>4}"
                    f" {_f(r['env_effects_mean']):>4} {_f(r['sensitive_mean']):>4}"
                    f" {_f(r['socioeconomic_mean']):>4} | {r['confidence_band']:<12}"
                    f" {_f(r['confidence'], 2)} {_f(r['c_coverage'], 2)} {_f(r['c_recency'], 2)}"
                    f" {_f(r['c_spatial'], 2)} {_f(r['c_monitor'], 2)} | {_f(r['population'], 0)}"
                )
            indicators = await conn.fetch(INDICATORS, run_id, site["h3_cells"])
            print("indicator pct (mean over cells, * = not observed): " + "  ".join(
                f"{r['indicator_id']}={_f(r['pct'])}{'' if r['observed'] else '*'}"
                for r in indicators
            ))

        print(f"\n## Rank drivers where Pollution Burden >= {args.pb_floor}")
        for r in await conn.fetch(RANK_DRIVERS, run_id, args.pb_floor):
            print(f"{r['indicator_id']:<3} r={_f(r['r'], 3):>6}  n={r['n']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
