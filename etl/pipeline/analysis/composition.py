"""Racial composition per hexagon, for the section 13.6 finding and for display.

`run_scoring` writes every other column of `hex_demographics` and deliberately
leaves these three unset, on the stated grounds that filling them there would
put race one careless join away from the arithmetic. This module fills them,
and it lives in `pipeline.analysis` for the reason the package exists: section
14 keeps racial composition out of every query that computes a score, and this
package is the only code in the project that reads those columns. A package
boundary is one a reviewer sees in a diff, where a stray column reference inside
a scoring module would look ordinary.

So the ordering is not incidental. Scoring runs first and completes without ever
seeing these numbers; this runs afterwards and can only add columns that no
indicator query may read. A composition computed before a score could be
suspected of having informed it. One computed after cannot.

**The shares are rates, formed after interpolation.** Both parts travel to the
hexagon as extensive counts and the division happens there, which is section 7's
rule and the same path the ACS indicators take. Dividing per tract first and
interpolating the ratio would average rates over unequal populations.

**People of colour is summed, not subtracted.** The numerator is every
non-Hispanic category other than white, plus Hispanic of any race. Taking the
total minus white alone would reach the same figure today and would silently
absorb any future category EPA or the Census adds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["SHARES", "ShareSpec", "hex_shares", "store_shares"]

#: `tract_race_ethnicity.variable` stores the published estimate id, suffixed
#: `E`. `census_acs.RACE` names the base codes because the adapter appends the
#: suffix when it queries and when it writes, so everything here converts before
#: it reads the table. The same trap cost this pipeline three separate outages
#: in `dasymetric.build` and `run_scoring`; it is written out here rather than
#: left to be rediscovered.
ESTIMATE_SUFFIX = "E"


def stored(code: str) -> str:
    return f"{code}{ESTIMATE_SUFFIX}"


@dataclass(frozen=True, slots=True)
class ShareSpec:
    """One column of `hex_demographics`, as a rate over published counts."""

    column: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    label: str


SHARES: tuple[ShareSpec, ...] = (
    ShareSpec(
        column="black_pct",
        # B02001 is race alone, without the Hispanic-origin cross-tabulation.
        # Section 8.5 names this the Black share, and it is the series the
        # published Louisiana figure of roughly 31% refers to.
        numerator=("B02001_003",),
        denominator=("B02001_001",),
        label="Black alone",
    ),
    ShareSpec(
        column="hispanic_pct",
        numerator=("B03002_012",),
        denominator=("B03002_001",),
        label="Hispanic or Latino of any race",
    ),
    ShareSpec(
        column="people_of_color_pct",
        numerator=(
            "B03002_004",  # Black or African American alone, not Hispanic
            "B03002_005",  # American Indian and Alaska Native alone, not Hispanic
            "B03002_006",  # Asian alone, not Hispanic
            "B03002_007",  # Native Hawaiian and Other Pacific Islander, not Hispanic
            "B03002_008",  # Some other race alone, not Hispanic
            "B03002_009",  # Two or more races, not Hispanic
            "B03002_012",  # Hispanic or Latino of any race
        ),
        denominator=("B03002_001",),
        label="people of colour",
    ),
)

LOAD_RACE = """
SELECT tract_geoid, variable, estimate, margin_of_error, is_extensive
  FROM tract_race_ethnicity
 WHERE variable = ANY($1) AND acs_vintage = $2
 ORDER BY tract_geoid
"""

STORE_SHARES = """
UPDATE hex_demographics
   SET black_pct            = $3::float8::numeric,
       hispanic_pct         = $4::float8::numeric,
       people_of_color_pct  = $5::float8::numeric
 WHERE run_id = $1 AND h3 = $2::h3_cell
"""


def _fold(estimates: Sequence[Any], codes: Sequence[str], name: str) -> list[Any]:
    """Several published counts as one synthetic count, summed per tract.

    A tract missing any part contributes nothing rather than a short sum: a
    partial numerator over a full denominator is a rate that is wrong, which is
    worse than one that is absent.
    """
    from pipeline.dasymetric.quantities import Kind, TractEstimate

    wanted = {stored(code) for code in codes}
    parts: dict[str, list[Any]] = {}
    for estimate in estimates:
        if estimate.variable in wanted:
            parts.setdefault(estimate.tract_geoid, []).append(estimate)

    summed: list[Any] = []
    for tract, rows in parts.items():
        if len(rows) != len(wanted) or any(row.estimate is None for row in rows):
            continue
        summed.append(
            TractEstimate(
                tract_geoid=tract,
                variable=name,
                estimate=sum(float(row.estimate) for row in rows),
                margin_of_error=None,
                kind=Kind.EXTENSIVE,
            )
        )
    return summed


async def hex_shares(
    conn: Any, crosswalk: Any, *, acs_vintage: str
) -> dict[str, dict[str, float | None]]:
    """Each share, per hexagon, as a percentage.

    Returns `{column: {h3: percent}}`. A hexagon whose denominator is zero or
    absent carries no share rather than a zero: nobody lives there to have a
    composition, and a zero would read as an all-white hexagon.
    """
    from pipeline.dasymetric.interpolate import interpolate_rate
    from pipeline.dasymetric.quantities import Kind, TractEstimate

    codes = {stored(code) for spec in SHARES for code in (*spec.numerator, *spec.denominator)}
    rows = await conn.fetch(LOAD_RACE, sorted(codes), acs_vintage)

    loaded = [
        TractEstimate(
            tract_geoid=str(row["tract_geoid"]),
            variable=str(row["variable"]),
            estimate=None if row["estimate"] is None else float(row["estimate"]),
            margin_of_error=(
                None if row["margin_of_error"] is None else float(row["margin_of_error"])
            ),
            kind=Kind.EXTENSIVE if row["is_extensive"] else Kind.INTENSIVE,
        )
        for row in rows
    ]

    out: dict[str, dict[str, float | None]] = {}
    for spec in SHARES:
        numerator = _fold(loaded, spec.numerator, f"{spec.column}_numerator")
        denominator = _fold(loaded, spec.denominator, f"{spec.column}_denominator")
        # Only the tracts that published both parts: a numerator the ACS had
        # nothing for would otherwise divide as a zero over a denominator that
        # counted everyone, and read as a hexagon with none of that group.
        rate = interpolate_rate(
            crosswalk,
            numerator,
            denominator,
            variable=spec.column,
            scale=100.0,
        )
        out[spec.column] = {h3: value.value for h3, value in rate.items()}
    return out


async def store_shares(
    conn: Any, shares: Mapping[str, Mapping[str, float | None]], *, run_id: int
) -> int:
    """Write the three columns onto one run's `hex_demographics` rows.

    An update rather than an insert: `run_scoring` owns the row and everything
    else in it, and this only ever adds the three columns section 14 keeps apart.
    Rows it does not reach keep their NULLs, which is the correct reading of a
    hexagon whose composition could not be formed.
    """
    reached = sorted({h3 for column in shares.values() for h3 in column})
    payload = [
        (
            run_id,
            h3,
            shares.get("black_pct", {}).get(h3),
            shares.get("hispanic_pct", {}).get(h3),
            shares.get("people_of_color_pct", {}).get(h3),
        )
        for h3 in reached
    ]
    if payload:
        await conn.executemany(STORE_SHARES, payload)
    return len(payload)
