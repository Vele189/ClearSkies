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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scoring"))

from burden.eligibility import (  # noqa: E402
    Eligibility,
    ExcludedHex,
    NoScoreReason,
    eligible,
)
from burden.robustness import Interpolation, check, report  # noqa: E402

Values = dict[str, dict[str, float | None]]


#: Why a hex section 5 would score carries no score anyway. The scorer records
#: it per hex; `eligible` cannot re-derive it, because it is a fact about which
#: indicators were observed rather than about how many people live there.
UNSCORED_FALLBACK: NoScoreReason = "insufficient_pollution_data"


def load_run(payload: dict[str, Any]) -> tuple[Eligibility, dict[str, str], Values]:
    """One interpolation's worth of a run: who is scored, how trusted, and what was measured.

    Section 5's split is re-derived here from population rather than read, so
    that the eligibility rule is an input to the checks and not something
    already applied to them. What it cannot re-derive is section 11: a hex can
    clear the population threshold and still produce no score, because the
    minimum-indicator rules were not met for it. The scorer records that as a
    `no_score_reason`, and this moves those hexes where they belong.

    **AUD-19.** They belong in `excluded`, not in `scored`, and this is the
    decision that ticket asked for. Three things would otherwise be true at
    once, and they cannot be. Section 12 gives confidence only to a hex that
    has a score, because confidence measures how well supported a score is.
    `robustness._universe` refuses a scored hex with no band, because a run
    whose confidence was never computed cannot honour section 12's exclusion.
    And section 5 calls these hexes scored. The old loader resolved it by
    writing the missing band as the string "None", which is neither a band nor
    absent: it passed the guard and put hexes carrying no score and no
    confidence into the comparison universe the checks correlate over.

    Neither the scorer nor `robustness.py` is wrong. Both are saying something
    true and narrow, and this function was flattening two different absences --
    "no confidence was computed for this run", which must fail, and "this hex
    has no score to be confident about", which is ordinary -- into one.
    """
    hexes = payload["hexes"]

    population: dict[str, float | None] = {}
    outside: list[str] = []
    bands: dict[str, str] = {}
    unscored: dict[str, NoScoreReason] = {}

    for h3, row in hexes.items():
        estimate = row.get("population")
        population[h3] = None if estimate is None else float(estimate)
        if row.get("outside_pilot_state"):
            outside.append(h3)

        # Absent stays absent. `check` refuses a scored hex with no band rather
        # than assuming it is trustworthy, and that guard only works if a null
        # arrives as a missing key instead of as a string.
        band = row.get("confidence_band")
        if band is not None:
            bands[h3] = str(band)

        # An export that predates this field says nothing about which hexes the
        # run scored, and the band is then the only evidence there is: under
        # section 12 a hex has one exactly when it has a score.
        scored = row["scored"] if "scored" in row else band is not None
        if not scored:
            unscored[h3] = row.get("no_score_reason") or UNSCORED_FALLBACK

    values: Values = {
        indicator: {h3: (None if value is None else float(value)) for h3, value in column.items()}
        for indicator, column in payload["indicators"].items()
    }

    return _without_unscored(
        eligible(population, outside_pilot_state=outside), unscored, population
    ), bands, values


def _without_unscored(
    eligibility: Eligibility,
    unscored: Mapping[str, NoScoreReason],
    population: Mapping[str, float | None],
) -> Eligibility:
    """Move the hexes the run did not score out of `scored` and into `excluded`.

    They keep the reason the scorer gave them, so the report can say how many
    eligible hexes produced no score and why, rather than losing them.
    """
    if not unscored:
        return eligibility

    kept = tuple(h3 for h3 in eligibility.scored if h3 not in unscored)
    added = tuple(
        ExcludedHex(h3=h3, reason=unscored[h3], population=population.get(h3))
        for h3 in eligibility.scored
        if h3 in unscored
    )
    return Eligibility(
        scored=kept,
        excluded=tuple(sorted(eligibility.excluded + added, key=lambda row: row.h3)),
    )


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
