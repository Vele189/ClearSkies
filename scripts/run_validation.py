#!/usr/bin/env python3
"""Run the methodology section 13 validation protocol against a scored run.

One command, so that a validation result is something anyone can reproduce
rather than something someone reports:

    make validate SCORES=path/to/scores.json

The gate logic lives in `scoring/burden/validation.py` and has no dependencies
and no I/O. This script is the I/O: it reads the frozen fixture, reads a scored
run, and prints the write-up. Keeping the two apart is what lets the criteria be
unit-tested without a database and lets this file be dull.

**The scores file.** A JSON object with a `source` string, a
`methodology_version`, and a `hexes` map from H3 index to `percentile` and
`confidence_band`. A real run exports it from `hex_score`; the fixture under
`scoring/tests/fixtures` exports nothing real and exists so CI can prove this
command still works without a database, on the same terms as `pipeline run fake`.

**This script never edits the fixture.** `docs/validation/sites.yml` is opened
read-only and section 13.7 does not permit a failing gate to be answered by
changing it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scoring"))

import yaml  # noqa: E402

from burden.validation import (  # noqa: E402
    HIGH_BURDEN,
    NEGATIVE_CONTROL,
    STRESS_EMISSIONS,
    STRESS_POVERTY,
    Criteria,
    ScoredCell,
    Site,
    evaluate,
    report,
)

SITES_YML = REPO_ROOT / "docs" / "validation" / "sites.yml"

# Which fixture section feeds which protocol category. The out-of-state sites
# are registered but inactive; `evaluate` skips them by their own flag rather
# than by being handed a shorter list, so flipping `active` is all it would take
# if coverage ever extended.
SECTIONS: dict[str, str] = {
    "high_burden_sites": HIGH_BURDEN,
    "inactive_out_of_state_sites": HIGH_BURDEN,
    "negative_controls": NEGATIVE_CONTROL,
    "stress_not_a_poverty_map": STRESS_POVERTY,
    "stress_not_an_emissions_map": STRESS_EMISSIONS,
}


def load_sites(path: Path) -> tuple[list[Site], Criteria]:
    fixture = yaml.safe_load(path.read_text())

    sites: list[Site] = []
    for section, category in SECTIONS.items():
        for entry in fixture.get(section, []):
            sites.append(
                Site(
                    id=str(entry["id"]),
                    name=str(entry["name"]),
                    category=category,
                    state=str(entry.get("state", "")),
                    active=bool(entry.get("active", False)),
                    cells=tuple(entry.get("h3_cells", [])),
                )
            )

    return sites, _criteria(fixture["criteria"])


def _criteria(block: dict[str, Any]) -> Criteria:
    """The thresholds, taken from the fixture rather than defaulted in code.

    Section 13.7 does not permit loosening a criterion in response to a result,
    and a default in the code is one edit away from doing exactly that without
    the fixture recording it.
    """
    high = block["high_burden"]
    negative = block["negative_control"]
    poverty = block["stress_not_a_poverty_map"]
    emissions = block["stress_not_an_emissions_map"]
    band = poverty["expected_band"]

    return Criteria(
        high_burden_percentile=float(high["threshold_percentile"]),
        high_burden_required=int(high["required"]),
        high_burden_of=int(high["of"]),
        negative_control_percentile=float(negative["threshold_percentile"]),
        negative_control_required=int(negative["required"]),
        negative_control_of=int(negative["of"]),
        poverty_band=(float(band[0]), float(band[1])),
        emissions_below_percentile=float(emissions["expected_below_percentile"]),
    )


def load_scores(path: Path) -> tuple[dict[str, ScoredCell], str, str]:
    payload = json.loads(path.read_text())
    cells = {
        h3: ScoredCell(percentile=float(row["percentile"]), band=str(row["confidence_band"]))
        for h3, row in payload["hexes"].items()
    }
    return cells, str(payload.get("source", path.name)), str(payload["methodology_version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scores",
        type=Path,
        required=True,
        help="JSON export of a scored run: h3 -> percentile and confidence_band",
    )
    parser.add_argument("--sites", type=Path, default=SITES_YML)
    parser.add_argument("--out", type=Path, help="write the report here instead of stdout")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit non-zero unless the gate passed, for the CI phase gate",
    )
    args = parser.parse_args(argv)

    sites, criteria = load_sites(args.sites)
    cells, source, methodology_version = load_scores(args.scores)

    gate = evaluate(
        sites, cells, criteria=criteria, methodology_version=methodology_version
    )
    written = report(gate, scores_from=source)

    if args.out:
        args.out.write_text(written)
        print(f"wrote {args.out}")
    else:
        print(written)

    primary = gate.category(HIGH_BURDEN)
    print(
        f"\nprimary gate: {primary.passed} of {primary.of} passed, "
        f"{primary.required} required -> {'PASS' if gate.passed else 'FAIL'}",
        file=sys.stderr,
    )

    if args.require_pass and not gate.passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
