"""Checks no single adapter can make, because no adapter sees more than itself.

The adapter interface is built so that a source knows nothing about the other
four. That is what makes adding a sixth a contained change, and it is also why
the four failures below can only be caught here:

- TRI names facilities by FRS registry id and ECHO is where those ids come from.
  A TRI pull that matches nothing still looks perfect to TRI.
- Tract coverage is complete or not only when the tract list and the tract values
  are compared, and they arrive from two different agencies.
- The hex grid is written by several sources and has to agree between them, or a
  join silently returns fewer hexes than the map draws.
- Section 11's group minimums are a property of the assembled indicator set, not
  of any one indicator.

**A check that cannot run says so.** Four of the five Phase 1 adapters are on
unmerged branches and the hex-level indicator tables are CS-106, CS-107 and
CS-202. Rather than guessing at schema that does not exist, a check whose inputs
are absent returns `skip` naming exactly what it wanted. The gate turns a skip on
a required source into a failure, so "not yet built" and "was supposed to be here
and is not" stay different answers.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pipeline.quality.checks import values
from pipeline.quality.dataset import Dataset
from pipeline.quality.results import CheckResult, Severity

CROSS = "cross"


# ---- section 11, on the ETL side ---------------------------------------
#
# `api/app/indicators.py` is the registry of record for the fifteen indicators
# and their groups. The ingestion package cannot import it: `api` and `etl` are
# separate distributions with separate dependency sets, which is what lets the
# API deploy without h3 and the pipeline run without asyncpg. So the small part
# of that registry the gate needs is restated here, and
# `test_quality_cross.py::test_group_table_matches_the_api` reads the API module
# off disk and fails if the two ever disagree.

Group = str

GROUP_INDICATORS: dict[Group, tuple[str, ...]] = {
    "exposures": ("E1", "E2", "E3", "E4"),
    "environmental_effects": ("F1", "F2", "F3", "F4"),
    "sensitive_populations": ("S1", "S2"),
    "socioeconomic_factors": ("P1", "P2", "P3", "P4", "P5"),
}

# Methodology section 11, rule 2.
GROUP_MINIMUM_PRESENT: dict[Group, int] = {
    "exposures": 2,
    "environmental_effects": 2,
    "sensitive_populations": 1,
    "socioeconomic_factors": 4,
}


@dataclass(frozen=True, slots=True)
class HexIndicator:
    """Where a hex-level indicator's value is found after a run.

    Only the three indicators that already have a hex-keyed table are listed.
    E3 and F1 through F4 need the facility-to-hex assignment of CS-107 and the
    proximity calculations of CS-202; S1, S2 and P1 through P5 need the
    dasymetric interpolation of CS-106. Their table names are not invented here,
    because a check pointed at a table that never gets built is a check that
    reports "skipped" forever without anyone noticing it was wrong.

    Adding an entry as each of those lands is all that is needed to bring its
    group's minimum under the gate.
    """

    indicator: str
    table: str
    key: str
    value: str


HEX_INDICATORS: tuple[HexIndicator, ...] = (
    HexIndicator("E1", "hex_exposure", "h3", "cancer_risk_per_million"),
    HexIndicator("E2", "hex_exposure", "h3", "respiratory_hazard_index"),
    HexIndicator("E4", "hex_air_quality", "h3", "annual_mean"),
)


# ---- the checks --------------------------------------------------------


def check_tri_matches_echo(
    data: Dataset,
    *,
    min_matched: float = 0.90,
    fail_below: float = 0.75,
) -> CheckResult:
    """How many TRI facilities are facilities ECHO also knows about.

    CS-102 counts unmatched facilities in its own manifest. This is the other
    half: the manifest says how many did not match, and nothing in it says
    whether that number is survivable. A TRI pull matching a third of ECHO still
    loads cleanly and quietly removes two thirds of indicator E3's signal from
    the map.

    Below `fail_below` the join key has almost certainly changed shape. Between
    the two it warns, because facilities genuinely enter and leave TRI reporting
    between an annual release and ECHO's weekly one.
    """
    missing = _absent_tables(data, ("tri_release", "facility"))
    if missing:
        return _skip(
            "tri_matches_echo",
            f"needs {' and '.join(missing)}; TRI or ECHO has not loaded",
        )

    echo_ids = {str(v) for v in values(data.rows("facility"), "facility_id")[0]}
    tri_ids = {str(v) for v in values(data.rows("tri_release"), "facility_id")[0]}
    if not tri_ids:
        return _skip("tri_matches_echo", "tri_release holds no facility ids")

    matched = tri_ids & echo_ids
    rate = len(matched) / len(tri_ids)
    unmatched = sorted(tri_ids - echo_ids)

    status: Severity | None = None
    if rate < fail_below:
        status = "fail"
    elif rate < min_matched:
        status = "warn"

    if status is None:
        detail = (
            f"{len(matched)} of {len(tri_ids)} TRI facilities match an ECHO facility ({rate:.1%})."
        )
    else:
        detail = (
            f"only {len(matched)} of {len(tri_ids)} TRI facilities match an ECHO facility "
            f"({rate:.1%}); {len(unmatched)} unmatched, first {unmatched[0]}. "
            "Indicator E3 loses the releases of every unmatched facility."
        )
    return CheckResult(
        check="tri_matches_echo",
        scope=CROSS,
        status=status or "pass",
        detail=detail,
        table="tri_release",
        field="facility_id",
        observed=rate,
        expected=f"at least {min_matched:.0%} matched",
    )


def check_tract_coverage(
    data: Dataset,
    *,
    min_covered: float = 0.98,
    fail_below: float = 0.95,
) -> list[CheckResult]:
    """Every tract the pipeline knows about has the values that make it usable.

    `census_tract` is the tract list, from TIGER. `tract_exposure` and
    `tract_demographics` are what has to exist for a tract to contribute
    anything. A tract present in the list and absent from either is a hole that
    survives interpolation and becomes a hex with a missing indicator, which
    section 11 then drops from its subgroup mean. That is the correct behaviour
    for a genuine absence and a silent loss of coverage for a broken join, so the
    gate insists on knowing which it is looking at.
    """
    if "census_tract" not in data.table_names():
        return [_skip("tract_coverage", "needs census_tract; the ACS adapter has not loaded")]

    tracts = {str(v) for v in values(data.rows("census_tract"), "geoid")[0]}
    if not tracts:
        return [_skip("tract_coverage", "census_tract holds no geoids")]

    results = []
    for table, label in (
        ("tract_exposure", "modeled exposure"),
        ("tract_demographics", "demographics"),
    ):
        if table not in data.table_names():
            results.append(
                _skip(f"tract_coverage.{table}", f"needs {table}; that source has not loaded")
            )
            continue
        covered = {str(v) for v in values(data.rows(table), "tract_geoid")[0]}
        present = tracts & covered
        rate = len(present) / len(tracts)
        orphans = sorted(covered - tracts)

        status: Severity | None = None
        if rate < fail_below:
            status = "fail"
        elif rate < min_covered:
            status = "warn"

        detail = (
            f"{len(present)} of {len(tracts)} tracts have {label} ({rate:.1%})."
            if status is None
            else (
                f"only {len(present)} of {len(tracts)} tracts have {label} ({rate:.1%}); "
                f"{len(tracts) - len(present)} tracts will carry a missing indicator."
            )
        )
        if orphans:
            detail += (
                f" {len(orphans)} rows name a tract the tract list does not contain, "
                f"first {orphans[0]}."
            )
            status = status or "warn"

        results.append(
            CheckResult(
                check=f"tract_coverage.{table}",
                scope=CROSS,
                status=status or "pass",
                detail=detail,
                table=table,
                field="tract_geoid",
                observed=rate,
                expected=f"at least {min_covered:.0%} of tracts",
            )
        )
    return results


def check_hex_grid_agreement(data: Dataset, *, max_disagreement: float = 0.01) -> CheckResult:
    """Every source writing hex-keyed rows agrees on which hexes exist.

    After interpolation each hex-keyed table should describe the same grid, one
    row per cell, differing only in what it says about each cell. Two tables that
    disagree produce a score built from an inner join, so the map loses hexes
    without anything reporting a loss. Absence is expressed inside the row, as an
    absent `Measurement`, never by leaving the row out.
    """
    hex_tables = [t.table for t in HEX_INDICATORS]
    present = [t for t in dict.fromkeys(hex_tables) if t in data.table_names()]
    if len(present) < 2:
        return _skip(
            "hex_grid_agreement",
            f"needs two hex-keyed tables, found {len(present)}; interpolation has not run",
        )

    grids = {table: {str(v) for v in values(data.rows(table), "h3")[0]} for table in present}
    union: set[str] = set().union(*grids.values())
    if not union:
        return _skip("hex_grid_agreement", "no hex cells were loaded")

    shared = set.intersection(*grids.values())
    disagreement = 1 - len(shared) / len(union)
    ok = disagreement <= max_disagreement

    if ok:
        detail = f"{len(present)} hex-keyed tables agree on {len(shared)} cells."
    else:
        worst = max(grids, key=lambda t: len(union - grids[t]))
        detail = (
            f"{len(union) - len(shared)} of {len(union)} cells are missing from at least one "
            f"table ({disagreement:.1%}); {worst} is short by {len(union - grids[worst])}. "
            "A score built over these joins away the difference."
        )
    return CheckResult(
        check="hex_grid_agreement",
        scope=CROSS,
        status="pass" if ok else "fail",
        detail=detail,
        observed=disagreement,
        expected=f"at most {max_disagreement:.0%} disagreement",
    )


def check_group_minimums(data: Dataset, *, min_computable: float = 0.95) -> list[CheckResult]:
    """Section 11 rule 2, measured over the grid rather than assumed.

    For each group whose every indicator has a hex-level table, this reports the
    share of cells holding at least the minimum number of observed indicators.
    A cell below the minimum is not an error — section 11 says the group is not
    computable and, if its partner group is also not computable, the hex becomes
    `no_score`. What is an error is that share collapsing, because it means the
    map is about to lose a region and the only visible symptom is a smaller map.

    A group with an indicator that has no hex-level table yet is skipped and
    names the indicator. Evaluating it on the indicators that do exist would
    invent failures: a cell holding E1 and E2 fails a minimum of 2 of 4 only
    because E3 and E4 could not be looked for.
    """
    located = {i.indicator: i for i in HEX_INDICATORS}
    results = []

    for group, indicators in GROUP_INDICATORS.items():
        minimum = GROUP_MINIMUM_PRESENT[group]
        unlocated = [i for i in indicators if i not in located]
        if unlocated:
            results.append(
                _skip(
                    f"group_minimum.{group}",
                    f"no hex-level table yet for {', '.join(unlocated)}; "
                    "evaluating the rest would invent failures",
                )
            )
            continue

        missing_tables = _absent_tables(data, tuple({located[i].table for i in indicators}))
        if missing_tables:
            results.append(
                _skip(
                    f"group_minimum.{group}",
                    f"needs {', '.join(missing_tables)}; that source has not loaded",
                )
            )
            continue

        present_per_cell = _observed_per_cell(data, [located[i] for i in indicators])
        if not present_per_cell:
            results.append(_skip(f"group_minimum.{group}", "no hex cells were loaded"))
            continue

        computable = sum(1 for count in present_per_cell.values() if count >= minimum)
        rate = computable / len(present_per_cell)
        ok = rate >= min_computable
        detail = (
            f"{computable} of {len(present_per_cell)} cells hold at least {minimum} of "
            f"{len(indicators)} {group.replace('_', ' ')} indicators ({rate:.1%})."
        )
        if not ok:
            detail += (
                f" Below {min_computable:.0%} the group stops being computable across the grid "
                "and section 11 pushes those hexes toward no_score."
            )
        results.append(
            CheckResult(
                check=f"group_minimum.{group}",
                scope=CROSS,
                status="pass" if ok else "fail",
                detail=detail,
                observed=rate,
                expected=f"at least {min_computable:.0%} of cells computable",
            )
        )
    return results


def check_scored_hexes_meet_minimums(data: Dataset, *, table: str = "hex_score") -> CheckResult:
    """No hex carries a score it was not entitled to under section 11.

    The other direction of the same rule, and the one the ticket names. Once
    CS-204 writes scores, every scored cell must satisfy the minimums of the
    groups its score was built from. A cell that received a score without them is
    the most damaging defect in the pipeline, because it looks exactly like a
    cell that earned one.

    Skipped until scoring exists, which is the honest answer rather than a pass.
    """
    if table not in data.table_names():
        return _skip("scored_hex_minimums", f"needs {table}; scoring (CS-204) has not run")

    located = {i.indicator: i for i in HEX_INDICATORS}
    evaluable = {
        group: indicators
        for group, indicators in GROUP_INDICATORS.items()
        if all(i in located for i in indicators)
        and not _absent_tables(data, tuple({located[i].table for i in indicators}))
    }
    if not evaluable:
        return _skip("scored_hex_minimums", "no group has a complete set of hex-level tables")

    scored = {str(v) for v in values(data.rows(table), "h3")[0]}
    violations: list[str] = []
    for group, indicators in evaluable.items():
        minimum = GROUP_MINIMUM_PRESENT[group]
        per_cell = _observed_per_cell(data, [located[i] for i in indicators])
        violations += [
            f"{cell} ({group}: {per_cell.get(cell, 0)} of {minimum})"
            for cell in scored
            if per_cell.get(cell, 0) < minimum
        ]

    ok = not violations
    detail = (
        f"all {len(scored)} scored cells meet the section 11 minimums for "
        f"{len(evaluable)} checkable group(s)."
        if ok
        else (
            f"{len(violations)} scored cells hold fewer indicators than section 11 permits, "
            f"first {violations[0]}. These carry a score the data does not support."
        )
    )
    return CheckResult(
        check="scored_hex_minimums",
        scope=CROSS,
        status="pass" if ok else "fail",
        detail=detail,
        table=table,
        observed=float(len(violations)),
        expected="no violations",
    )


def run_cross_checks(data: Dataset) -> list[CheckResult]:
    """Every cross-source check, in the order a reader wants to see them fail."""
    results: list[CheckResult] = [check_tri_matches_echo(data)]
    results += check_tract_coverage(data)
    results.append(check_hex_grid_agreement(data))
    results += check_group_minimums(data)
    results.append(check_scored_hexes_meet_minimums(data))
    return results


# ---- helpers -----------------------------------------------------------


def _observed_per_cell(data: Dataset, locators: Sequence[HexIndicator]) -> dict[str, int]:
    """How many of these indicators each hex cell actually holds a value for."""
    counts: dict[str, int] = {}
    for locator in locators:
        for record in data.rows(locator.table):
            cell = getattr(record, locator.key, None)
            if not isinstance(cell, str):
                continue
            counts.setdefault(cell, 0)
            raw = getattr(record, locator.value, None)
            # A Measurement says for itself whether it was observed; anything
            # else counts as present when it is not null. Section 11 turns on
            # this distinction, so it is read from the value rather than assumed.
            marker = getattr(raw, "observed", None)
            present = marker if marker is not None else raw is not None
            if present:
                counts[cell] += 1
    return counts


def _absent_tables(data: Dataset, wanted: tuple[str, ...]) -> list[str]:
    known = set(data.table_names())
    return [table for table in wanted if table not in known]


def _skip(check: str, why: str) -> CheckResult:
    return CheckResult(check=check, scope=CROSS, status="skip", detail=why)


__all__ = [
    "CROSS",
    "GROUP_INDICATORS",
    "GROUP_MINIMUM_PRESENT",
    "HEX_INDICATORS",
    "HexIndicator",
    "check_group_minimums",
    "check_hex_grid_agreement",
    "check_scored_hexes_meet_minimums",
    "check_tract_coverage",
    "check_tri_matches_echo",
    "run_cross_checks",
]
