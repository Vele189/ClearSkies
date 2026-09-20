#!/usr/bin/env python3
"""Rebuild `scoring/tests/fixtures/synthetic_scores.json`, the gate's self-test input.

Lives here rather than beside the fixture it writes because it needs PyYAML, and
the scoring package deliberately has no dependencies at all. Run it from the repo
root with the API virtualenv, which is where the YAML-reading scripts already run:

    api/.venv/bin/python scripts/make_validation_fixture.py

The numbers it writes are invented. Their only job is to drive every branch of
`burden.validation` through `scripts/run_validation.py` so CI can prove that
command still parses the frozen fixture and applies the section 13 criteria
without a database, on the same terms as `pipeline run fake` proves the adapter
contract without an upstream.

It is built to **fail** the gate on purpose. A fixture that produced a green
validation result would sooner or later be quoted as one.
"""

import json
import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "scoring" / "tests" / "fixtures" / "synthetic_scores.json"


def main() -> None:
    fixture = yaml.safe_load((ROOT / "docs" / "validation" / "sites.yml").read_text())
    hexes: dict[str, dict[str, Any]] = {}

    def put(cells: list[str], percentiles: list[float], band: str = "high") -> None:
        for cell, percentile in zip(cells, percentiles, strict=True):
            hexes[cell] = {"percentile": percentile, "confidence_band": band}

    # Active high-burden sites: seven clear the top decile, one scores but does
    # not rank, one is scored only in cells section 12 excludes, one is not
    # scored at all. Seven of ten misses the bar of eight, so the gate fails.
    active = [s for s in fixture["high_burden_sites"] if s.get("active")]
    for index, site in enumerate(active):
        cells = site["h3_cells"]
        if index < 7:
            put(cells, [30.0] * (len(cells) - 1) + [95.5])
        elif index == 7:
            put(cells, [40.0] * (len(cells) - 1) + [71.2])
        elif index == 8:
            put(cells, [99.0] * len(cells), band="insufficient")
        # index 9 is left unscored, so it comes out not_applicable.

    # Three clean controls and one that leaks above the median.
    for index, site in enumerate(fixture["negative_controls"]):
        cells = site["h3_cells"]
        clean = [18.0] * len(cells)
        leaking = [18.0] * (len(cells) - 1) + [64.0]
        put(cells, clean if index < 3 else leaking)

    # Stress A: two inside the expected band, one above it.
    for index, site in enumerate(fixture["stress_not_a_poverty_map"]):
        cells = site["h3_cells"]
        put(cells, [52.0 if index < 2 else 88.0] * len(cells))

    # Stress B: two below the top decile, one inside it.
    for index, site in enumerate(fixture["stress_not_an_emissions_map"]):
        cells = site["h3_cells"]
        put(cells, [61.0 if index < 2 else 97.0] * len(cells))

    payload = {
        "source": "SYNTHETIC HARNESS FIXTURE - invented percentiles, not a scored run",
        "note": (
            "Built by make_synthetic_scores.py to exercise every branch of the "
            "section 13 gate without a database. Deliberately fails, so it cannot "
            "be mistaken for a validation result."
        ),
        "methodology_version": "0.1.2",
        "hexes": hexes,
    }

    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT} with {len(hexes)} hexes over {len(active)} active high-burden sites")


if __name__ == "__main__":
    main()
