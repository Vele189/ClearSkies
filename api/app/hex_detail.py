"""One hexagon's score and everything behind it.

The panel shows a number and the argument for it in the same view, so this
assembles both in one pass: the score, the two components decomposed into
their groups, all fifteen indicators whether or not they were observed, the
four-term confidence breakdown, the demographics that are displayed and never
scored, and the facilities near enough to have contributed.

Three round trips on one connection. The score, the hex and the demographics
share a grain and are joined in the database; the indicators are fifteen rows;
the facilities are a geography query the database is indexed for. Everything
else the payload needs is the run context, which is the same for every hexagon
in a run and is cached in app/runs.py.

Every query is keyed by the run id from that one context, so a payload cannot
mix a score from one run with the inputs of another.
"""

import logging
from datetime import date
from typing import Any

from app.facilities import contributing
from app.indicators import (
    COMPONENT_COLUMNS,
    COMPONENT_GROUPS,
    GROUP_MEAN_COLUMNS,
    GROUP_MINIMUM_PRESENT,
    GROUP_WEIGHTS,
    INDICATORS,
)
from app.runs import RunContext
from app.schemas import (
    ComponentScore,
    Confidence,
    Demographics,
    GroupScore,
    HexDetail,
    IndicatorValue,
)

log = logging.getLogger(__name__)

# Methodology section 8.2. The enforcement window is five years back from the
# run, not from today, so a stored score and the panel explaining it count the
# same actions however long ago the run was.
ENFORCEMENT_WINDOW_YEARS = 5

# The hexagon, its score and its demographic profile share the grain (run, h3),
# so they are one row. Outer joins throughout: a cell in the grid that this run
# did not score still has a hex row, and that difference is what separates a
# 404 from a scored hex carrying a no_score_reason.
CORE = """
    SELECT h.h3::text        AS h3,
           h.resolution,
           h.state_fips,
           h.parish_name,
           h.in_pilot_state,
           ST_X(h.centroid)  AS lon,
           ST_Y(h.centroid)  AS lat,

           s.h3 IS NOT NULL  AS has_score_row,
           s.score,
           s.percentile,
           s.pollution_burden,
           s.population_characteristics,
           s.exposures_mean,
           s.env_effects_mean,
           s.sensitive_mean,
           s.socioeconomic_mean,
           s.confidence,
           s.confidence_band,
           s.c_coverage,
           s.c_recency,
           s.c_spatial,
           s.c_monitor,
           s.nearest_monitor_km,
           s.no_score_reason,

           d.h3 IS NOT NULL  AS has_demographics,
           d.population,
           d.under_5_pct,
           d.over_64_pct,
           d.poverty_200pct,
           d.black_pct,
           d.hispanic_pct,
           d.people_of_color_pct
      FROM hex h
      LEFT JOIN hex_score s
             ON s.h3 = h.h3 AND s.run_id = $2
      LEFT JOIN hex_demographics d
             ON d.h3 = h.h3 AND d.run_id = $2
     WHERE h.h3 = $1::h3_cell
"""

# Reads the (run_id, h3) prefix of the primary key, so this is an index scan
# returning at most fifteen rows.
INDICATOR_VALUES = """
    SELECT indicator_id, value, percentile, observed
      FROM hex_indicator
     WHERE run_id = $1 AND h3 = $2::h3_cell
"""


def enforcement_window_start(run_day: date) -> date:
    """Five years before the run, section 8.2's window."""
    year = run_day.year - ENFORCEMENT_WINDOW_YEARS
    try:
        return run_day.replace(year=year)
    except ValueError:
        # 29 February, five years before a year that has no 29 February.
        return run_day.replace(year=year, day=28)


def _float(value: Any) -> float | None:
    """Postgres numeric arrives as Decimal. JSON has one number type."""
    return None if value is None else float(value)


def build_indicators(rows: list[Any]) -> list[IndicatorValue]:
    """All fifteen, in registry order, present or not.

    An indicator absent from this run has no row at all, and it is still
    rendered, as an indicator that was dropped rather than one that scored
    zero. Section 11 turns on that distinction and so does the panel.
    """
    by_id = {r["indicator_id"]: r for r in rows}

    unknown = by_id.keys() - {i.id for i in INDICATORS}
    if unknown:
        # The run scored something this build of the API cannot name. Worth a
        # line: it means the registry and the pipeline are on different
        # versions of the methodology.
        log.warning(
            "run holds indicators the registry does not define",
            extra={"unknown_indicators": sorted(unknown)},
        )

    values: list[IndicatorValue] = []
    for indicator in INDICATORS:
        row = by_id.get(indicator.id)
        values.append(
            IndicatorValue(
                id=indicator.id,
                name=indicator.name,
                group=indicator.group,
                value=_float(row["value"]) if row is not None else None,
                unit=indicator.unit,
                percentile=_float(row["percentile"]) if row is not None else None,
                source=indicator.source,
                observed=bool(row["observed"]) if row is not None else False,
            )
        )
    return values


def build_components(core: Any, indicators: list[IndicatorValue]) -> list[ComponentScore]:
    """The two components, each decomposed into its groups.

    A component whose score this run could not compute is omitted rather than
    reported as zero. Zero is a real score on a 0 to 10 scale and claiming it
    for a cell with no data is the one thing the methodology is most insistent
    the interface must not do.
    """
    observed_in_group = {
        group: sum(1 for i in indicators if i.group is group and i.observed)
        for group in GROUP_WEIGHTS
    }

    components: list[ComponentScore] = []
    for component, groups in COMPONENT_GROUPS.items():
        score = _float(core[COMPONENT_COLUMNS[component]])
        if score is None:
            continue

        components.append(
            ComponentScore(
                component=component,
                score=score,
                groups=[
                    GroupScore(
                        group=group,
                        mean_percentile=_float(core[GROUP_MEAN_COLUMNS[group]]),
                        weight=GROUP_WEIGHTS[group],
                        indicators_present=observed_in_group[group],
                        indicators_required=GROUP_MINIMUM_PRESENT[group],
                        computable=observed_in_group[group] >= GROUP_MINIMUM_PRESENT[group],
                    )
                    for group in groups
                ],
            )
        )
    return components


def build_confidence(core: Any) -> Confidence:
    """The four-term breakdown, section 12.

    An unscored hexagon has no confidence stored, because the column is
    constrained above zero and there is nothing to be confident about. It is
    reported here as zero in the insufficient band, which is the one reading
    that cannot be mistaken for a weakly supported score.
    """
    value = _float(core["confidence"])
    band = core["confidence_band"]

    return Confidence(
        value=value if value is not None else 0.0,
        band=band if band is not None else "insufficient",
        coverage=_float(core["c_coverage"]) or 0.0,
        recency=_float(core["c_recency"]) or 0.0,
        spatial_support=_float(core["c_spatial"]) or 0.0,
        monitor_support=_float(core["c_monitor"]) or 0.0,
        nearest_monitor_km=_float(core["nearest_monitor_km"]),
    )


def build_demographics(core: Any) -> Demographics:
    """The profile the panel displays and the score never reads. Section 14."""
    if not core["has_demographics"]:
        # No interpolated profile for this run. Reported as an unpopulated
        # hexagon rather than omitted, so the panel has a shape to render; the
        # no_score_reason alongside it says why there is nothing there.
        return Demographics(population=0)

    return Demographics(
        population=int(core["population"]),
        under_5_pct=_float(core["under_5_pct"]),
        over_64_pct=_float(core["over_64_pct"]),
        poverty_200pct=_float(core["poverty_200pct"]),
        black_pct=_float(core["black_pct"]),
        people_of_color_pct=_float(core["people_of_color_pct"]),
        hispanic_pct=_float(core["hispanic_pct"]),
    )


async def load(conn: Any, h3_index: str, run: RunContext) -> HexDetail | None:
    """One hexagon's full payload, or None when this run did not score it.

    None covers two cases the caller reports the same way: a cell outside the
    grid entirely, and a cell in the grid that this run holds no row for. Both
    are "not in the scored set". A cell the run scored as unscorable is not one
    of them; it comes back with its `no_score_reason` set, which is the honest
    answer and a different one.
    """
    core = await conn.fetchrow(CORE, h3_index, run.run_id)
    if core is None or not core["has_score_row"]:
        return None

    indicator_rows = await conn.fetch(INDICATOR_VALUES, run.run_id, h3_index)

    # Bound the enforcement count by the run rather than by today, which is
    # what app/facilities.py asks a caller rendering a stored run to do.
    run_day = run.finished_at.date() if run.finished_at is not None else date.today()
    facilities = await contributing(
        conn,
        h3_index,
        actions_since=enforcement_window_start(run_day),
    )

    indicators = build_indicators(list(indicator_rows))

    return HexDetail(
        h3=core["h3"],
        resolution=core["resolution"],
        state=core["state_fips"],
        parish=core["parish_name"],
        centroid=(core["lon"], core["lat"]),
        score=_float(core["score"]),
        percentile=_float(core["percentile"]),
        components=build_components(core, indicators),
        indicators=indicators,
        confidence=build_confidence(core),
        demographics=build_demographics(core),
        facilities=facilities,
        no_score_reason=core["no_score_reason"],
        methodology_version=run.methodology_version,
        data_vintage=run.data_vintage,
    )
