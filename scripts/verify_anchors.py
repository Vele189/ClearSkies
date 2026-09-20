#!/usr/bin/env python3
"""Check every anchor in docs/validation/sites.yml against external evidence.

`scripts/check_validation_set.py` proves the fixture is consistent with itself:
that each anchor is what its coordinates produce and each cell list is the disk
around its anchor. That is a closed loop. It cannot tell you that the anchor
named "Welcome" is anywhere near Welcome, because nothing in the file knows
where Welcome is.

This script closes that gap. `docs/validation/anchor-references.yml` carries
coordinates for each site's community and for the facilities its citations
name, each sourced from USGS GNIS, the US Census, or EPA. Two checks run
against them:

  administrative  the parish or county recorded for the site is the one the
                  Census says the anchor coordinate actually falls in.
  community       the site's anchor is tied to a community it names, by either
                  of two routes:

                    point       a `community` reference resolves to a
                                resolution 8 cell that is in the site's frozen
                                cell list. Not near it, in it: the frozen cells
                                are what CS-206 scores, so landing outside them
                                means the site is not being measured where it
                                lives.
                    boundary    the Census place the anchor actually falls in
                                is the community the site names. A named point
                                is a single coordinate, so for a city the size
                                of Port Arthur the downtown point can sit
                                several rings outside a k=2 disk while the
                                anchor is unambiguously inside the city. Being
                                within the boundary settles the same question
                                the point was standing in for.

                  The route taken is printed, because the two are not equally
                  strong: `point` places the community inside the scored cells,
                  `boundary` only places the anchor inside the community.

A site passes when both hold, and `verified: true` is allowed only then. The
script fails if any `verified` flag disagrees with its own verdict, so the flags
cannot drift away from the evidence.

`secondary` and `citation` references are reported with their ring distance but
do not gate. A refinery outside the frozen cells is a fact worth printing, not
a failure: cells are anchored on where people live, not on the fence line.

Run: python scripts/verify_anchors.py [--verbose]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    import h3
    import yaml
except ImportError:
    print("needs h3 and pyyaml: pip install -e 'api[dev]' pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "docs/validation/sites.yml"
REFERENCES = ROOT / "docs/validation/anchor-references.yml"
RESOLUTION = 8

SITE_SECTIONS = (
    "high_burden_sites",
    "inactive_out_of_state_sites",
    "negative_controls",
    "stress_not_a_poverty_map",
    "stress_not_an_emissions_map",
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def normalise_county(name: str | None) -> str:
    """'Genesee County' and 'Genesee' are the same place; so are 'St.' and 'Saint'."""
    if not name:
        return ""
    n = name.strip().casefold()
    for suffix in (" county", " parish"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.replace("saint ", "st. ").strip()


def normalise_place(name: str | None) -> str:
    """'City of Lafayette' and 'Lafayette' are the same place.

    Deliberately an exact match after stripping the civil prefix and any
    parenthetical the manifest carries. A loose match here would let a site
    anchored anywhere in Baton Rouge claim to be Alsen.
    """
    if not name:
        return ""
    n = name.split("(")[0].strip().casefold()
    for prefix in ("city of ", "town of ", "village of "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.replace("saint ", "st. ").strip()


def check_site(site: dict, refs: dict | None) -> dict:
    sid = str(site["id"])
    anchor = site["h3_res8_anchor"]
    cells = set(site["h3_cells"])
    stated = site.get("parish") or site.get("county")

    result = {
        "id": sid,
        "name": site["name"],
        "k": site["k"],
        "stated_county": stated,
        "declared_verified": bool(site.get("verified")),
        "problems": [],
        "notes": [],
        "references": [],
    }

    if refs is None:
        result["problems"].append("no reference entry in anchor-references.yml")
        result["verdict"] = False
        return result

    # Administrative: is the anchor in the parish or county the fixture claims?
    actual = refs.get("anchor_county_actual")
    result["actual_county"] = actual
    admin_ok = normalise_county(stated) == normalise_county(actual)
    if not admin_ok:
        result["problems"].append(
            f"anchor falls in {actual}, but the site records {stated}"
        )

    # Community: does a named community land inside the frozen cells?
    community_hits = 0
    community_total = 0
    for ref in refs.get("references", []):
        cell = h3.latlng_to_cell(ref["lat"], ref["lon"], RESOLUTION)
        inside = cell in cells
        row = {
            "role": ref["role"],
            "label": ref["label"],
            "inside": inside,
            "km": round(haversine_km(site["lat"], site["lon"], ref["lat"], ref["lon"]), 2),
            "rings": h3.grid_distance(anchor, cell),
            "source": ref["source"],
        }
        result["references"].append(row)
        if ref["role"] == "community":
            community_total += 1
            community_hits += inside
        elif not inside:
            kind = "second community" if ref["role"] == "secondary" else "cited facility"
            result["notes"].append(
                f"{kind} {ref['label']!r} is {row['km']} km from the anchor, "
                f"{row['rings']} rings out, outside the frozen cells"
            )

    # Route 2: the anchor sits inside the boundary of a community the site names.
    actual_place = refs.get("anchor_place_actual")
    boundary_match = next(
        (r["label"] for r in refs.get("references", [])
         if r["role"] == "community"
         and normalise_place(r["label"]) == normalise_place(actual_place)),
        None,
    )

    if community_total and community_hits:
        result["route"] = "point"
    elif boundary_match:
        result["route"] = "boundary"
        result["notes"].append(
            f"community established by boundary, not by point: the anchor is inside "
            f"{actual_place}, but that community's reference point is outside the frozen cells"
        )
    else:
        result["route"] = None
        outside = [r for r in result["references"] if r["role"] == "community"]
        detail = "; ".join(f"{r['label']} {r['km']} km, {r['rings']} rings out" for r in outside)
        result["problems"].append(
            f"anchor is not tied to any community the site names: no community reference "
            f"falls inside the frozen cells ({detail}), and the anchor sits in "
            f"{actual_place or 'no Census place'}"
        )

    result["verdict"] = admin_ok and result["route"] is not None
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="print every reference point")
    args = ap.parse_args()

    doc = yaml.safe_load(FIXTURE.read_text())
    refdoc = yaml.safe_load(REFERENCES.read_text())
    refs = refdoc["sites"]

    results = []
    for section in SITE_SECTIONS:
        for site in doc.get(section) or []:
            results.append(check_site(site, refs.get(str(site["id"]))))

    passed = [r for r in results if r["verdict"]]
    failed = [r for r in results if not r["verdict"]]
    drift = [r for r in results if r["declared_verified"] != r["verdict"]]

    for r in results:
        mark = "PASS" if r["verdict"] else "FAIL"
        route = f"via {r['route']}" if r.get("route") else ""
        print(f"[{mark}] {r['id']:>14}  {r['name'][:38]:38} k={r['k']}  "
              f"{str(r['stated_county']):20} {route}")
        for p in r["problems"]:
            print(f"         problem: {p}")
        for n in r["notes"]:
            print(f"         note:    {n}")
        if args.verbose:
            for ref in r["references"]:
                where = "in " if ref["inside"] else "out"
                print(f"         {where} {ref['role']:9} {ref['label'][:44]:44} "
                      f"{ref['km']:6.2f} km  ring {ref['rings']}")

    print()
    print(f"{len(passed)} of {len(results)} anchors verified against external evidence")

    if drift:
        print()
        print(f"FAIL: {len(drift)} site(s) carry a 'verified' flag that disagrees with the check")
        for r in drift:
            print(f"  - {r['id']}: file says verified: {str(r['declared_verified']).lower()}, "
                  f"check says {str(r['verdict']).lower()}")
        return 1

    if failed:
        print(f"{len(failed)} site(s) remain unverified, each recorded with a note in the fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
