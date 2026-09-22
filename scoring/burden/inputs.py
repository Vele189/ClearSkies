"""What a scoring run hands this package, decided without a database.

`scripts/run_scoring.py` reads what the pipeline loaded and passes it here in
the shape sections 9 to 12 expect. Most of that is plumbing, but five parts of
it are methodology decisions, and every one of them was once wrong in a way no
test could see because the script itself imports asyncpg and nothing imported
the script. They live here instead, with no SQL and no dependencies, so that
the rules are tested where the rest of the arithmetic is:

* **Zero versus missing for the proximity indicators** (sections 9 and 11). E3
  and F1 to F4 are zero for a scored hex with no qualifying facility within
  10 km, and absent only when the source they are counted from did not load.
* **Which quarters F2 counts** (section 8.2). A quarter in violation or high
  priority violation, not one ECHO marked `unknown`, over the twelve quarters
  ending at the run's as-of date.
* **Which vintage an indicator carries** (section 12). The oldest snapshot the
  run actually read for each contributing source, and unknown when any
  contributing source was not read at all.
* **The two inputs to c_spatial** (section 12). The mean area of the source
  blocks, and the share of the hex's population drawn from ACS estimates whose
  coefficient of variation exceeds 0.30.
* **Which `hex_indicator` rows a run writes** (section 11 rule 5). All fifteen
  for every hex, an unobserved one as an unobserved row rather than no row.
"""

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date
from typing import Protocol

from burden.indicators import GROUP_INDICATORS

#: Sections 7 and 12. Above this an ACS estimate is still used, and the hex's
#: spatial support falls instead. The ingestion package holds the same figure
#: as `pipeline.dasymetric.quantities.HIGH_UNCERTAINTY_CV`; this package cannot
#: import it, for the reason `burden.indicators` gives.
HIGH_UNCERTAINTY_CV = 0.30

#: The fifteen, in registry order.
INDICATOR_IDS: tuple[str, ...] = tuple(
    indicator for indicators in GROUP_INDICATORS.values() for indicator in indicators
)

#: Section 8.2's trailing window for F2.
COMPLIANCE_QUARTERS = 12

#: The statuses F2 counts. `in_compliance` is clean and `unknown` is an
#: unmonitored quarter, which migration 0004 is explicit is not a clean one --
#: but it is not a violation either. Counting it as one would give a facility
#: nobody inspected the maximum 12 of 12, which is section 8.2's
#: regulatory-attention confounder turned upside down. The drill-down panel's
#: `facilities_near_hex` counts the same two statuses.
NONCOMPLIANT_STATUSES: frozenset[str] = frozenset({"violation", "high_priority_violation"})

#: Which loaded sources each indicator's value depends on, by the names
#: `source_snapshot.source` uses.
#:
#: E3 names two: TRI publishes the released quantities and RSEI the toxicity
#: weights that scale them, and a score built from a 2024 extract and a 2012
#: weighting table is as old as the older half.
INDICATOR_SOURCES: Mapping[str, tuple[str, ...]] = {
    "E1": ("airtoxscreen",),
    "E2": ("airtoxscreen",),
    "E3": ("tri", "rsei"),
    "E4": ("openaq",),
    "F1": ("echo",),
    "F2": ("echo",),
    "F3": ("echo",),
    "F4": ("echo",),
    "S1": ("acs",),
    "S2": ("acs",),
    "P1": ("acs",),
    "P2": ("acs",),
    "P3": ("acs",),
    "P4": ("acs",),
    "P5": ("acs",),
}


# ---- zero versus missing -----------------------------------------------


def proximity_values(
    sums: Mapping[str, float | None], *, hexes: Collection[str], loaded: bool
) -> dict[str, float | None]:
    """One proximity indicator over the scored hexes, zero where nothing is near.

    `sums` is the decayed aggregate for the hexes that have a qualifying
    facility within the radius, which is all a query over the links relation can
    return: a hex with nothing near it has no row at all. Section 9 says such a
    hex is zero, and section 11 says zero is an observation. Leaving it out
    instead dropped it from the zero block and from the denominator, and when
    enough of a group went that way the whole group became non-computable and
    coverage was penalised for facilities that were looked for and are not there.

    A null sum is also zero. It is what `sum(...) FILTER (...)` returns for a
    hex whose nearby facilities all fail the filter.

    When the source was not loaded at all there is nothing to have looked in,
    and every hex is absent. That is the one case a zero would be a claim the
    run cannot make.
    """
    if not loaded:
        return dict.fromkeys(hexes)
    out: dict[str, float | None] = {}
    for h3 in hexes:
        value = sums.get(h3)
        out[h3] = 0.0 if value is None else float(value)
    return out


# ---- F2 ----------------------------------------------------------------


def quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def compliance_window(as_of: date, *, quarters: int = COMPLIANCE_QUARTERS) -> tuple[date, ...]:
    """The quarter start dates F2 looks at, oldest first.

    The twelve quarters ending with the one that contains `as_of`, which is the
    window ECHO's own twelve-quarter history describes (see
    `pipeline.adapters.echo.twelve_quarters_ending`). Taken from the run's date
    rather than from whichever rows are newest: "the last twelve rows" is the
    same thing only while one program is loaded.
    """
    last = quarter_start(as_of)
    index = last.year * 4 + (last.month - 1) // 3
    return tuple(date(i // 4, 3 * (i % 4) + 1, 1) for i in range(index - quarters + 1, index + 1))


def noncompliant_quarters(rows: Iterable[tuple[str, date, str]], *, as_of: date) -> dict[str, int]:
    """Quarters in non-compliance per facility, over the section 8.2 window.

    `rows` are `(facility_id, quarter, status)`. A quarter counts once however
    many programs were in violation during it: F2 is a count of facility-quarters,
    and a facility in breach of two programs in March has had one bad quarter,
    not two. Facilities with none are left out, and read as zero by the caller.
    """
    window = frozenset(compliance_window(as_of))
    bad: dict[str, set[date]] = {}
    for facility_id, quarter, status in rows:
        if quarter in window and status in NONCOMPLIANT_STATUSES:
            bad.setdefault(facility_id, set()).add(quarter)
    return {facility_id: len(quarters) for facility_id, quarters in bad.items()}


# ---- vintages ----------------------------------------------------------


def source_vintages(snapshots: Iterable[tuple[str, date]]) -> dict[str, date]:
    """The vintage of each source as this run read it.

    `snapshots` are `(source, vintage_end)` for every snapshot the rows the run
    read were loaded from, not every snapshot the database holds. The newest
    snapshot of a source is not what was scored when the run pinned an older
    release, and a source can have rows from more than one snapshot. Where it
    does the oldest wins, for the same reason `indicator_vintages` takes the
    oldest source: the data is no fresher than the stalest part of it.
    """
    out: dict[str, date] = {}
    for source, vintage_end in snapshots:
        known = out.get(source)
        if known is None or vintage_end < known:
            out[source] = vintage_end
    return out


def loaded_indicators(
    per_source: Mapping[str, date],
    *,
    sources: Mapping[str, tuple[str, ...]] = INDICATOR_SOURCES,
) -> frozenset[str]:
    """The indicators every contributing source of which the run read."""
    return frozenset(
        indicator
        for indicator, names in sources.items()
        if all(name in per_source for name in names)
    )


def indicator_vintages(
    per_source: Mapping[str, date],
    *,
    sources: Mapping[str, tuple[str, ...]] = INDICATOR_SOURCES,
) -> dict[str, date]:
    """The vintage_end behind each indicator, keyed the way section 12 asks.

    `confidence._recency` looks these up by *indicator*. The oldest contributing
    source wins: an indicator is no fresher than the stalest thing it is built
    from.

    An indicator any of whose sources the run did not read has an unknown
    vintage and is left out. Taking the oldest of the sources that *were* read
    instead would date E3 by its TRI extract alone when the RSEI weights that
    scale it are missing, which is a date for a quantity the run did not have.
    """
    loaded = loaded_indicators(per_source, sources=sources)
    return {
        indicator: min(per_source[name] for name in names)
        for indicator, names in sources.items()
        if indicator in loaded
    }


# ---- c_spatial ---------------------------------------------------------


class SupportRow(Protocol):
    """One tract's share of one hex, as `tract_hex_weight` stores it."""

    @property
    def tract_geoid(self) -> str: ...

    @property
    def population(self) -> float: ...

    @property
    def mean_block_area_m2(self) -> float: ...


def mean_block_area_m2(rows: Iterable[SupportRow]) -> float | None:
    """Population-weighted mean source block area over a hex's tracts.

    One tract per hex used to be kept here, whichever came last, so a hex split
    between a town tract and a rural one was scored on whichever the crosswalk
    happened to list second. Weighted by population because section 7's
    uniformity error matters in proportion to the people it misplaces, as
    `Crosswalk.mean_block_area_m2` weights it.

    A row with no positive area is a tract whose block area was not recorded,
    and it is left out rather than averaged in as zero, which would read as
    perfect support. With no known area at all the answer is None, which
    `confidence` treats as no support rather than good support. A hex with
    known areas but no block population falls back to the plain mean.
    """
    known = [row for row in rows if row.mean_block_area_m2 > 0]
    if not known:
        return None
    support = math.fsum(row.population for row in known)
    if support <= 0:
        return math.fsum(row.mean_block_area_m2 for row in known) / len(known)
    return math.fsum(row.mean_block_area_m2 * row.population for row in known) / support


def high_cv_population_share(
    rows: Iterable[SupportRow], tract_cvs: Mapping[str, Sequence[float | None]]
) -> float:
    """Share of a hex's population drawn from ACS estimates with a CV over 0.30.

    Section 12's first c_spatial input. `rows` are the hex's tracts with the
    block-apportioned population each contributes, P(t n h). `tract_cvs` holds,
    per tract, the coefficient of variation of each ACS estimate the score draws
    on there: the tract-level value of each of the seven ACS indicators, S1, S2
    and P1 to P5.

    Every person in the hex is drawn from each of those estimates once, so the
    share is taken over (population, estimate) pairs:

        share(h) = sum_t sum_k P(t n h) * [CV_{t,k} > 0.30]
                   / sum_t sum_k P(t n h)

    over the pairs whose CV is defined. With one estimate per tract this is
    exactly "the population share of the hex under a tract whose estimate
    exceeds 0.30". With seven it is that share averaged over the estimates, so a
    tract whose linguistic isolation count is noisy degrades the hex by one
    seventh of its population rather than by all of it.

    An undefined CV, from an estimate of zero, is unknown rather than worst
    case, as `pipeline.dasymetric.quantities.coefficient_of_variation` says, and
    takes no part. A hex with no defined CV at all returns 0.0: nothing is known
    to be uncertain, and the block-area half of the term still applies.
    """
    high = 0.0
    total = 0.0
    for row in rows:
        for cv in tract_cvs.get(row.tract_geoid, ()):
            if cv is None:
                continue
            total += row.population
            if cv > HIGH_UNCERTAINTY_CV:
                high += row.population
    if total <= 0:
        return 0.0
    return min(1.0, high / total)


# ---- hex_indicator -----------------------------------------------------


def indicator_rows(
    values: Mapping[str, Mapping[str, float | None]],
    percentiles: Mapping[str, Mapping[str, float | None]],
    *,
    hexes: Collection[str],
    indicators: Sequence[str] = INDICATOR_IDS,
) -> list[tuple[str, str, float | None, float | None, bool]]:
    """Every `(h3, indicator, value, percentile, observed)` row a run writes.

    All fifteen for every hex, observed or not. Writing only the observed ones
    made `observed = false` a state the table could not hold, so an absence and
    an indicator the run never considered were the same missing row, and the
    robustness export read a different set of indicators from the one the run
    ranked. An unobserved row carries no value and no percentile, which is what
    the table's `hex_indicator_absent_has_no_value` constraint requires.
    """
    rows: list[tuple[str, str, float | None, float | None, bool]] = []
    for indicator in sorted(indicators):
        by_hex = values.get(indicator, {})
        ranked = percentiles.get(indicator, {})
        for h3 in sorted(hexes):
            value = by_hex.get(h3)
            observed = value is not None
            rows.append((h3, indicator, value, ranked.get(h3) if observed else None, observed))
    return rows
