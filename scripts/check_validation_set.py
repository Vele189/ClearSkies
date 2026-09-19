#!/usr/bin/env python3
"""Verify docs/validation/sites.yml is internally consistent.

The fixture is read-only (methodology section 17). "Read-only" in a comment is
a wish; this script is what makes drift detectable. It re-derives every cell
list from its anchor and fails if the committed cells disagree, so an anchor
cannot be quietly nudged toward a better result without the cells contradicting
it, and cells cannot be edited without the anchor contradicting them.

Run: python scripts/check_validation_set.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import h3
    import yaml
except ImportError:
    print("needs h3 and pyyaml: pip install -e 'api[dev]' pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

FIXTURE = Path(__file__).resolve().parent.parent / "docs/validation/sites.yml"
RESOLUTION = 8
PILOT_STATE = "LA"

SITE_SECTIONS = (
    "high_burden_sites",
    "inactive_out_of_state_sites",
    "negative_controls",
    "stress_not_a_poverty_map",
    "stress_not_an_emissions_map",
)

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def check_site(section: str, site: dict) -> None:
    where = f"{section}[{site.get('id', '?')}]"

    for field in ("id", "name", "state", "lat", "lon", "k", "h3_res8_anchor", "h3_cells"):
        if field not in site:
            fail(f"{where}: missing required field {field!r}")
            return

    anchor, k = site["h3_res8_anchor"], site["k"]
    cells = site["h3_cells"]

    if not h3.is_valid_cell(anchor):
        fail(f"{where}: anchor {anchor} is not a valid H3 cell")
        return
    if h3.get_resolution(anchor) != RESOLUTION:
        fail(f"{where}: anchor is resolution {h3.get_resolution(anchor)}, expected {RESOLUTION}")

    # The anchor must be what the coordinates actually produce.
    derived = h3.latlng_to_cell(site["lat"], site["lon"], RESOLUTION)
    if derived != anchor:
        fail(f"{where}: lat/lon resolve to {derived}, but anchor is recorded as {anchor}")

    # The cell list must be exactly the disk around that anchor.
    expected = sorted(h3.grid_disk(anchor, k))
    if sorted(cells) != expected:
        fail(f"{where}: h3_cells disagree with grid_disk(anchor, k={k}); "
             f"expected {len(expected)} cells, found {len(cells)}")

    if anchor not in cells:
        fail(f"{where}: anchor is not present in its own cell list")

    bad = [c for c in cells if not h3.is_valid_cell(c) or h3.get_resolution(c) != RESOLUTION]
    if bad:
        fail(f"{where}: {len(bad)} cells are invalid or not resolution {RESOLUTION}")

    # Every site needs a citation to public documentation of the burden.
    if section in ("high_burden_sites", "inactive_out_of_state_sites"):
        if not site.get("citations"):
            fail(f"{where}: no citations")

    active = site.get("active")
    if active is None:
        fail(f"{where}: missing 'active'")
    elif section == "inactive_out_of_state_sites":
        if active:
            fail(f"{where}: out-of-state site is marked active; it cannot be scored in v0")
        if site["state"] == PILOT_STATE:
            fail(f"{where}: filed as out-of-state but its state is the pilot state")
        if not site.get("activate_when"):
            fail(f"{where}: inactive site needs a pre-declared activate_when trigger")
    else:
        if not active:
            fail(f"{where}: in-state site is not active")
        if site["state"] != PILOT_STATE:
            fail(f"{where}: in {section} but state is {site['state']}, not {PILOT_STATE}")


def main() -> int:
    doc = yaml.safe_load(FIXTURE.read_text())

    if doc.get("status") != "closed":
        fail("status is not 'closed'; the set is meant to be read-only")

    seen_ids: set = set()
    all_cells: dict[str, str] = {}

    for section in SITE_SECTIONS:
        rows = doc.get(section)
        if not rows:
            fail(f"section {section!r} is missing or empty")
            continue
        for site in rows:
            check_site(section, site)
            sid = site.get("id")
            if sid in seen_ids:
                fail(f"duplicate site id {sid!r}")
            seen_ids.add(sid)
            # A cell belonging to two sites would make a pass ambiguous.
            for cell in site.get("h3_cells", []):
                owner = all_cells.get(cell)
                if owner and owner != sid:
                    fail(f"cell {cell} is claimed by both {owner!r} and {sid!r}")
                all_cells[cell] = sid

    active = doc.get("high_burden_sites", [])
    required = doc.get("criteria", {}).get("high_burden", {}).get("of")
    if len(active) != required:
        fail(f"criteria expect {required} active high-burden sites, found {len(active)}")

    if errors:
        print(f"FAIL: {len(errors)} problem(s) in {FIXTURE.name}")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"ok: {len(active)} active sites, "
        f"{len(doc['inactive_out_of_state_sites'])} registered out-of-state, "
        f"{len(all_cells)} distinct cells, all anchors and cell lists consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
