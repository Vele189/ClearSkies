#!/usr/bin/env python3
"""Run the methodology section 13.5 robustness checks against a scored run.

One command, so that a robustness result is something anyone can reproduce
rather than something someone reports:

    make robustness VALUES=path/to/values.json

The checks live in `scoring/burden/robustness.py` and have no dependencies and
no I/O. This script is the I/O: it reads a run's indicator values, scores them
three ways, and prints the write-up. Keeping the two apart is what lets the
criteria be unit-tested without a database and lets this file be dull, on the
same terms as `run_validation.py`.

**The values file.** A JSON object with a `source` string, a
`methodology_version`, a `hexes` map from H3 index to `population`,
`confidence_band` and an optional `outside_pilot_state` flag, and an
`indicators` map from indicator id to H3 index to raw value. A null value is an
absence and stays one; section 11 does not let it become a zero anywhere in this
pipeline, and it does not become one here either.

Section 13.5's third check needs a second interpolation of the same run, so an
optional `areal` block carries the same `hexes` and `indicators` computed with
simple area share. `pipeline.dasymetric.areal_counterpart` is what produces it.
Without that block the first two checks run and the third reports that it did
not, which is a different thing from reporting that it found no divergence.

**This script never writes a score.** It reads a run and prints a verdict.
Section 13.7 does not permit answering a failing check by adjusting anything, and
nothing here could.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scoring"))

from burden.eligibility import Eligibility, eligible  # noqa: E402
from burden.robustness import Interpolation, check, report  # noqa: E402

Values = dict[str, dict[str, float | None]]


def load_run(payload: dict[str, Any]) -> tuple[Eligibility, dict[str, str], Values]:
    """One interpolation's worth of a run: who is scored, how trusted, and what was measured."""
    hexes = payload["hexes"]

    population: dict[str, float | None] = {}
    outside: list[str] = []
    bands: dict[str, str] = {}

    for h3, row in hexes.items():
        estimate = row.get("population")
        population[h3] = None if estimate is None else float(estimate)
        if row.get("outside_pilot_state"):
            outside.append(h3)
        # Every scored hex needs one, and `check` refuses the run if any is
        # missing rather than assuming the hex is trustworthy.
        if "confidence_band" in row:
            bands[h3] = str(row["confidence_band"])

    values: Values = {
        indicator: {h3: (None if value is None else float(value)) for h3, value in column.items()}
        for indicator, column in payload["indicators"].items()
    }

    return eligible(population, outside_pilot_state=outside), bands, values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--values",
        type=Path,
        required=True,
        help="JSON export of a run: per-hex population and confidence band, and raw "
        "indicator values, with an optional areal-weighted counterpart",
    )
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit non-zero unless every gating check in section 13.5 cleared",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.values.read_text())
    grid, bands, values = load_run(payload)

    areal = None
    if "areal" in payload:
        areal_grid, _, areal_values = load_run(payload["areal"])
        areal = Interpolation(eligibility=areal_grid, values=areal_values)

    result = check(
        values,
        eligibility=grid,
        confidence_bands=bands,
        areal=areal,
        methodology_version=str(payload["methodology_version"]),
    )

    written = report(result, scores_from=str(payload.get("source", args.values.name)))

    if args.out:
        args.out.write_text(written)
        print(f"wrote {args.out}")
    else:
        print(written)

    failures = result.failures()
    if failures:
        print(f"section 13.5 checks that did not clear: {', '.join(failures)}", file=sys.stderr)

    if args.require_pass and not result.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
