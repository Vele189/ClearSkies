"""The contributing facilities behind one hexagon.

This is the read path migration 0014 exists to serve, and it is deliberately
thin: one call to `facilities_near_hex`, which is the same neighbour relation
the scoring step aggregates into F1 through F4. The panel and the score
therefore cannot disagree about which facilities are near a hexagon, because
there is one definition of "near" and it lives in the database next to the
index that makes it fast.

Nothing is materialised per hex per run. Migration 0009 records why: that table
would be the largest in the database by a wide margin, to save a distance query
over a few thousand rows that the geography index answers in single-digit
milliseconds.

What this module adds on top of the query is presentation, and only the part
that would otherwise be repeated by every caller: turning four permit flags into
the label the panel prints, and metres into kilometres.
"""

from datetime import date
from typing import Any

from app.schemas import Facility

# Methodology section 8.1. Passed explicitly rather than left to the function's
# default, so the radius the API asks for is visible in the API, the way the H3
# resolution is.
INTERACTION_RADIUS_M = 10_000.0

# The panel lists the nearest few. A hexagon in the industrial corridor along the
# lower Mississippi can have well over a hundred facilities within 10 km, and a
# list that long is not a drill-down, it is a data dump. They all still count
# towards the score; this is only what is shown.
PANEL_LIMIT = 50

NEARBY = """
SELECT * FROM facilities_near_hex($1, $2, $3, $4) LIMIT $5
"""

# How many there are, which is not how many are listed. The panel shows the
# nearest fifty and the model is shown fewer still, and both were presenting
# that cap as the total: a hexagon with 120 facilities within 10 km reported
# 50, in a drill-down whose purpose is to say what produced the score.
NEARBY_COUNT = """
SELECT count(*) FROM facilities_near_hex($1, $2, $3, $4)
"""


def program_label(row: Any) -> str:
    """What the facility is permitted under, as the panel prints it.

    Title V implies major source, so naming both would be noise. A facility with
    no flag set is still in the Clean Air Act feed, which is how it got here.
    """
    programs: list[str] = []
    if row["has_title_v"]:
        programs.append("CAA Title V")
    elif row["is_major_source"]:
        programs.append("CAA major source")
    if row["is_rcra_lqg"]:
        programs.append("RCRA large-quantity generator")
    if row["is_rcra_tsdf"]:
        programs.append("RCRA treatment, storage and disposal")
    return ", ".join(programs) if programs else "Clean Air Act"


def to_facility(row: Any) -> Facility:
    return Facility(
        # registry_id is nullable in the schema because a TRI-only facility has
        # no FRS id. The panel links to the public record by registry id, so a
        # facility without one falls back to the internal id rather than
        # rendering a link to nowhere.
        registry_id=row["registry_id"] or row["facility_id"],
        name=row["name"],
        # Metres on the wire would be false precision: the coordinates these are
        # computed from are self-reported and most of them carry an EPA accuracy
        # estimate in the kilometres.
        distance_km=round(row["distance_m"] / 1000.0, 2),
        program=program_label(row),
        echo_url=row["echo_url"] or "",
        in_hex=row["is_containing"],
        quarters_in_noncompliance=row["quarters_in_noncompliance"],
        formal_actions_5yr=row["formal_actions"],
    )


async def count_contributing(
    conn: Any,
    h3: str,
    *,
    radius_m: float = INTERACTION_RADIUS_M,
    actions_since: date | None = None,
    quarters_since: date | None = None,
) -> int:
    """How many facilities are within the interaction radius, uncapped."""
    return int(await conn.fetchval(NEARBY_COUNT, h3, radius_m, actions_since, quarters_since))


async def contributing(
    conn: Any,
    h3: str,
    *,
    radius_m: float = INTERACTION_RADIUS_M,
    actions_since: date | None = None,
    quarters_since: date | None = None,
    limit: int = PANEL_LIMIT,
) -> list[Facility]:
    """Facilities within the interaction radius of one hexagon, nearest first.

    `actions_since` bounds the formal enforcement count and `quarters_since`
    bounds the non-compliance count, and both default in the database to the
    windows section 8.2 gives F3 and F2 — five years and twelve quarters, ending
    today. A caller rendering a stored run should pass that run's date instead,
    so both counts match the score rather than the calendar. AUD-18: before
    0027 the quarter count had no window at all and could disagree with F2 as
    soon as ECHO's history ran deeper than twelve quarters.

    Quarantined facilities are absent: section 6 keeps them in the table and out
    of the indicators, and the panel shows what produced the score.
    """
    rows = await conn.fetch(NEARBY, h3, radius_m, actions_since, quarters_since, limit)
    return [to_facility(row) for row in rows]
