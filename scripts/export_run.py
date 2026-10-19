#!/usr/bin/env python3
"""Export a scored run in the shapes the gates and the tile builder read.

`run_validation.py` and `run_robustness.py` each take a JSON file rather than a
database, so that a result is reproducible by anyone holding the file and so
that the criteria can be unit tested without Postgres. That is the right split,
and it left nothing that produces the files. This does.

    etl/.venv/bin/python scripts/export_run.py --validation out.json
    etl/.venv/bin/python scripts/export_run.py --robustness values.json
    etl/.venv/bin/python scripts/export_run.py --tiles tile_scores.json

`--tiles` is the same idea for `pipeline tiles`, which also took a JSON file
nothing produced. The map was therefore only as current as a file somebody made
by hand, which `_tiles` says in as many words is the thing it exists not to be.
Its shape is not the validation export's: tiles carry the score and the
confidence value as well as the percentile, and they carry every hex the run has
a row for rather than only the ones that scored, because `no_score_reason` is an
attribute so the map can explain a hole rather than draw nothing.

Defaults to the promoted run, the one the API and the tiles serve, so a gate
describes the data a reader is looking at rather than whichever run finished
last.

**The `areal` block, with `--areal`.** Section 13.5's third check wants the
same run interpolated a second time by area share. It does not need a second
scored run: `run_robustness.py` scores both interpolations itself through the
production `compute`. It needs the inputs, and only the crosswalk-derived ones
differ -- the total population behind section 5, S1, S2 and P1 to P5 from the
ACS, and E1 and E2 from AirToxScreen. Those are recomputed here by the
scorer's own loaders over `dasymetric.areal_counterpart`, so the only thing that
changes between the two blocks is the population estimator. E3, E4 and F1 to
F4 are point-based and are copied unchanged.

The counterpart needs the whole of each tract, which `tract_hex_weight` holds
once the crosswalk is rebuilt under migration 0025; it raises
`PartialCrosswalk` rather than guess when it does not. As a control, the same
loaders are first run over the dasymetric crosswalk and must reproduce the
run's stored values; `--areal` refuses to write a block if they do not, since
the comparison would then measure drift since the run rather than section 7.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "etl"))

import asyncpg  # noqa: E402

CURRENT_RUN = "SELECT run_id, methodology_version FROM pipeline_run WHERE is_current"

# Only scored hexes. Both gates rank and contrast within the scored universe,
# and an unscored hex has no percentile to place.
VALIDATION_ROWS = """
SELECT h3::text AS h3, percentile, confidence_band
  FROM hex_score
 WHERE run_id = $1 AND score IS NOT NULL AND percentile IS NOT NULL
"""

# The whole grid, because section 5's exclusions are an input to the robustness
# checks rather than something already applied: `eligible` has to be able to
# re-derive them.
# `scored` and `no_score_reason` are here because section 5 eligibility and
# "this run produced a score" are not the same set, and flattening them was
# AUD-19. A hex can hold enough people to be eligible and still carry no score,
# because section 11's minimum-indicator rules could not be met for it. Such a
# hex also carries no confidence: section 12 measures how well supported a score
# is, and there is none to support. Exporting only the band left the reader
# unable to tell "this run never computed confidence", which must fail the run,
# from "this hex has no score to be confident about", which is ordinary.
ROBUSTNESS_HEXES = """
SELECT s.h3::text        AS h3,
       d.population      AS population,
       s.confidence_band AS confidence_band,
       s.score IS NOT NULL  AS scored,
       s.no_score_reason AS no_score_reason,
       -- The column is centroid_in_state since 0031; the JSON key keeps its
       -- name, because tiles/robustness-values.json carries it and
       -- scripts/run_robustness.py reads it by that name.
       NOT h.centroid_in_state AS outside_pilot_state
  FROM hex_score s
  JOIN hex h ON h.h3 = s.h3
  LEFT JOIN hex_demographics d ON d.run_id = s.run_id AND d.h3 = s.h3
 WHERE s.run_id = $1
"""

# Everything the tile builder puts in a feature, for every hex the run has a
# row for -- scored or not. `no_score_reason` is an attribute precisely so the
# map can explain a hole: a grey cell reading "fewer than 25 residents" is a
# different thing from a cell that failed to draw. Filtering to scored hexes
# here, as the validation export does, would turn every explained hole into an
# unexplained one.
TILE_HEXES = """
SELECT h3::text        AS h3,
       score           AS score,
       percentile      AS percentile,
       confidence      AS confidence,
       confidence_band AS confidence_band,
       no_score_reason AS no_score_reason
  FROM hex_score
 WHERE run_id = $1
"""

ROBUSTNESS_INDICATORS = """
SELECT indicator_id, h3::text AS h3, value
  FROM hex_indicator
 WHERE run_id = $1
"""


async def resolve(conn: asyncpg.Connection, run_id: int | None) -> tuple[int, str]:
    if run_id is not None:
        version = await conn.fetchval(
            "SELECT methodology_version FROM pipeline_run WHERE run_id = $1", run_id
        )
        if version is None:
            raise SystemExit(f"no run {run_id}")
        return run_id, str(version)

    record = await conn.fetchrow(CURRENT_RUN)
    if record is None:
        raise SystemExit("no promoted run; score with --promote first")
    return int(record["run_id"]), str(record["methodology_version"])


async def validation_payload(conn: asyncpg.Connection, run_id: int, version: str) -> dict[str, Any]:
    rows = await conn.fetch(VALIDATION_ROWS, run_id)
    return {
        "source": f"run {run_id}",
        "methodology_version": version,
        "hexes": {
            row["h3"]: {
                "percentile": float(row["percentile"]),
                "confidence_band": row["confidence_band"],
            }
            for row in rows
        },
    }


async def tiles_payload(conn: asyncpg.Connection, run_id: int, version: str) -> dict[str, Any]:
    """The run in the shape `pipeline tiles` reads.

    Without this, `make tiles SCORES=...` had no documented way to produce its
    input from a run: the validation export carries only percentile and band,
    and only for hexes that scored, so tiles built from it would lose the score,
    the confidence value and every unscored cell.

    A scored hex carries no `no_score_reason` key at all rather than a null one,
    which is the distinction `build.py` relies on: a reason is present or it is
    not.
    """
    rows = await conn.fetch(TILE_HEXES, run_id)

    hexes: dict[str, dict[str, Any]] = {}
    for row in rows:
        hex_row: dict[str, Any] = {}
        if row["no_score_reason"] is not None:
            hex_row["no_score_reason"] = str(row["no_score_reason"])
        for field in ("score", "percentile", "confidence"):
            if row[field] is not None:
                hex_row[field] = float(row[field])
        if row["confidence_band"] is not None:
            hex_row["confidence_band"] = str(row["confidence_band"])
        hexes[row["h3"]] = hex_row

    return {
        "source": f"run {run_id}",
        "methodology_version": version,
        "hexes": hexes,
    }


async def robustness_payload(conn: asyncpg.Connection, run_id: int, version: str) -> dict[str, Any]:
    hexes = await conn.fetch(ROBUSTNESS_HEXES, run_id)
    indicators = await conn.fetch(ROBUSTNESS_INDICATORS, run_id)

    grouped: dict[str, dict[str, float | None]] = {}
    for row in indicators:
        # A null value is an absence and stays one. Section 11 does not let it
        # become a zero anywhere else in this pipeline and does not here.
        grouped.setdefault(str(row["indicator_id"]), {})[row["h3"]] = (
            None if row["value"] is None else float(row["value"])
        )

    return {
        "source": f"run {run_id}",
        "methodology_version": version,
        "hexes": {
            row["h3"]: {
                "population": None if row["population"] is None else float(row["population"]),
                # Null stays null. A hex with no score has no band, and writing
                # the absence as a string is what let one into the comparison
                # universe carrying neither.
                "confidence_band": row["confidence_band"],
                "scored": bool(row["scored"]),
                "no_score_reason": row["no_score_reason"],
                "outside_pilot_state": bool(row["outside_pilot_state"]),
            }
            for row in hexes
        },
        "indicators": grouped,
    }


#: Recomputed under area share. Everything else is a point indicator and does
#: not pass through the crosswalk.
CROSSWALK_INDICATORS = ("S1", "S2", "P1", "P2", "P3", "P4", "P5", "E1", "E2")

#: How far a recomputed dasymetric value may sit from the stored one. The
#: stored column is numeric and the recomputation is float8, so this is
#: rounding, not tolerance for a different answer.
REPRODUCTION_TOLERANCE = 1e-6


async def _crosswalk_inputs(
    conn: asyncpg.Connection, crosswalk: Any
) -> tuple[dict[str, float], dict[str, dict[str, float | None]]]:
    """Population and the nine crosswalk-derived indicators, as the scorer forms them."""
    import run_scoring as scoring

    population, _ = await scoring.hex_population(
        conn, crosswalk, acs_vintage=scoring.ACS_VINTAGE
    )
    values, _ = await scoring.acs_indicators(conn, crosswalk, acs_vintage=scoring.ACS_VINTAGE)
    values.update(
        await scoring.modelled_exposure(
            conn, crosswalk, vintage_year=scoring.EXPOSURE_VINTAGE_YEAR
        )
    )
    return population, {k: dict(values[k]) for k in CROSSWALK_INDICATORS}


def _reproduces(
    stored: dict[str, dict[str, float | None]], recomputed: dict[str, dict[str, float | None]]
) -> list[str]:
    """Indicators whose stored values the dasymetric recomputation does not match."""
    drift = []
    for indicator in CROSSWALK_INDICATORS:
        for h3, value in stored.get(indicator, {}).items():
            again = recomputed[indicator].get(h3)
            if value is None or again is None:
                if value is not again:
                    drift.append(f"{indicator} {h3}: stored {value}, recomputed {again}")
                    break
            elif abs(value - again) > REPRODUCTION_TOLERANCE * max(1.0, abs(value)):
                drift.append(f"{indicator} {h3}: stored {value}, recomputed {again}")
                break
    return drift


async def areal_block(conn: asyncpg.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """The `areal` block for a robustness payload already built from the run."""
    from pipeline.dasymetric import areal_counterpart, postgis

    crosswalk = await postgis.load_crosswalk(conn)

    _, dasymetric = await _crosswalk_inputs(conn, crosswalk)
    drift = _reproduces(payload["indicators"], dasymetric)
    if drift:
        raise SystemExit(
            "the dasymetric inputs no longer reproduce this run, so an areal block "
            "built now would not isolate section 7; first mismatches: " + "; ".join(drift)
        )

    population, values = await _crosswalk_inputs(conn, areal_counterpart(crosswalk))
    indicators = {k: dict(v) for k, v in payload["indicators"].items()}
    for indicator in CROSSWALK_INDICATORS:
        indicators[indicator] = values[indicator]

    # Section 5 is re-derived from these populations by `run_robustness.py`.
    # No band and no reason: confidence was computed for the dasymetric
    # interpolation only, and section 11 is applied by the scoring itself.
    hexes = {
        h3: {
            "population": population.get(h3),
            "scored": True,
            "outside_pilot_state": row["outside_pilot_state"],
        }
        for h3, row in payload["hexes"].items()
    }
    return {"hexes": hexes, "indicators": indicators}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, help="write the CS-206 scores file here")
    parser.add_argument("--robustness", type=Path, help="write the CS-212 values file here")
    parser.add_argument("--tiles", type=Path, help="write the CS-207 tile input here")
    parser.add_argument("--run-id", type=int, default=None, help="default: the promoted run")
    parser.add_argument(
        "--areal",
        action="store_true",
        help="add the section 13.5 areal-weighting counterpart to the --robustness file",
    )
    args = parser.parse_args()

    if not args.validation and not args.robustness and not args.tiles:
        parser.error("nothing to write: pass --validation, --robustness or --tiles")
    if args.areal and not args.robustness:
        parser.error("--areal adds a block to the --robustness file; pass both")

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(url, command_timeout=600)
    try:
        run_id, version = await resolve(conn, args.run_id)
        for path, build in (
            (args.validation, validation_payload),
            (args.robustness, robustness_payload),
            (args.tiles, tiles_payload),
        ):
            if path is None:
                continue
            payload = await build(conn, run_id, version)
            if args.areal and build is robustness_payload:
                payload["areal"] = await areal_block(conn, payload)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
            print(f"run {run_id}: {len(payload['hexes'])} hexes -> {path}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
