"""Running methodology section 7 over a whole state, county by county.

The other modules in this package are each one idea: `weights` folds the block
layer into a crosswalk, `interpolate` applies the two section 7 formulas,
`reconcile` says whether the totals held, `postgis` holds the SQL. This module
is the order they go in, and it exists so that the statewide acceptance of
section 7 is something the pipeline runs rather than something a person
remembers to check by hand.

**County at a time, and why.** Intersecting a quarter of a million census
blocks with a hex grid is the most expensive operation in the pipeline. Doing
it statewide holds every overlap in memory at once and turns any failure into a
restart from the beginning. A county is small enough to hold, and
`store_crosswalk` replaces exactly one county's rows, so a run that dies in
Terrebonne can be resumed there instead of re-running Orleans.

**Each county is its own transaction.** `store_crosswalk` deletes the county's
existing weights before inserting the new ones, and between those two
statements the county has no crosswalk at all. A reader that saw that state
would score the county as empty rather than as broken, which is the worse of
the two failures. The transaction is opened here, around both.

**The crosswalk is checked against the block layer before any ACS value moves.**
`reconcile_crosswalk` compares the 2020 block population that went in against
the hex population that came out. Running it per county, before interpolation,
separates a broken geometry from a broken estimate: only one of those is worth
re-running the intersection for, and after interpolation the two are
indistinguishable from the totals alone.

**The statewide population check is the ticket's acceptance criterion.**
Section 7 requires that statewide totals after interpolation match tract totals
within a documented tolerance. `verify_statewide_population` is that check,
and `reconcile` documents the tolerance and the reasoning behind the number.
It is deliberately a second, separate pass over the stored crosswalk rather
than an accumulation of the per-county builds: checking the thing that was
written, rather than the thing that was about to be written, is what makes it a
check rather than a restatement.

Nothing here imports a database driver. `postgis.Connection` is a protocol, so
this orchestration is unit tested end to end against an in-memory stand-in and
gains nothing from a live Postgres beyond the SQL that `postgis` already holds.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pipeline.dasymetric import postgis
from pipeline.dasymetric.interpolate import interpolate_extensive
from pipeline.dasymetric.quantities import Kind, KindMismatch
from pipeline.dasymetric.reconcile import (
    DEFAULT_RELATIVE_TOLERANCE,
    Reconciliation,
    reconcile_crosswalk,
    reconcile_population,
    require,
)
from pipeline.dasymetric.weights import CrosswalkReport, build_crosswalk

log = logging.getLogger("pipeline.dasymetric")

#: The ACS total-population variable, written to `tract_demographics` by the
#: CS-105 adapter. It is the default subject of the statewide check because it
#: is the quantity every other apportioned count is weighted by: if population
#: closes, the rest closes with it. Passed rather than assumed wherever the
#: caller has a reason to check a different count.
TOTAL_POPULATION = "B01003_001"


@dataclass(frozen=True, slots=True)
class CountyCrosswalk:
    """What building one county's crosswalk produced."""

    county_fips: str
    rows_written: int
    report: CrosswalkReport
    reconciliation: Reconciliation

    @property
    def ok(self) -> bool:
        return self.reconciliation.ok


@dataclass(frozen=True, slots=True)
class StateCrosswalk:
    """Every county's result, and the totals that span them.

    The per-county reports are kept rather than summed away because the numbers
    that matter for section 7's known error are distributional: one county
    whose blocks are enormous is the signal, and it disappears into a statewide
    mean.
    """

    state_fips: str
    counties: tuple[CountyCrosswalk, ...]

    @property
    def rows_written(self) -> int:
        return sum(county.rows_written for county in self.counties)

    @property
    def block_count(self) -> int:
        return sum(county.report.block_count for county in self.counties)

    @property
    def hex_count(self) -> int:
        return sum(county.report.hex_count for county in self.counties)

    @property
    def total_block_population(self) -> int:
        return sum(county.report.total_block_population for county in self.counties)

    @property
    def unassigned_population(self) -> int:
        """2020 block population that met no hexagon, statewide.

        A statement about the grid, not about any ACS value. Section 7's step 2
        can only place a block that reaches a hexagon; one that reaches none
        leaves the ancillary layer on both sides, so the tract's weights still
        sum to 1 and its estimate still lands in full. What this number
        measures is lost spatial detail.
        """
        return sum(county.report.unassigned_population for county in self.counties)

    @property
    def area_fallback_tracts(self) -> tuple[str, ...]:
        """Tracts with no 2020 block population, whose weights are areal.

        Worth surfacing statewide rather than per county: these are the only
        rows in the crosswalk that are not dasymetric, and section 7's argument
        for the whole method does not cover them.
        """
        return tuple(
            tract for county in self.counties for tract in county.report.area_fallback_tracts
        )

    @property
    def ok(self) -> bool:
        return all(county.ok for county in self.counties)

    def describe(self) -> str:
        lines = [
            f"crosswalk built for state {self.state_fips}: "
            f"{len(self.counties)} counties, {self.rows_written:,} tract-hex weights",
            f"  {self.block_count:,} blocks -> {self.hex_count:,} hexes",
            f"  2020 block population {self.total_block_population:,}, "
            f"unassigned {self.unassigned_population:,}",
        ]
        if self.area_fallback_tracts:
            lines.append(
                f"  {len(self.area_fallback_tracts)} tracts had no 2020 block population; "
                "their weights are areal, not dasymetric"
            )
        failed = [county.county_fips for county in self.counties if not county.ok]
        if failed:
            lines.append(f"  OUT OF TOLERANCE in counties: {', '.join(failed)}")
        return "\n".join(lines)


async def build_county_crosswalk(
    conn: postgis.Connection,
    *,
    county_fips: str,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> CountyCrosswalk:
    """Intersect, fold, check, store. One county, one transaction.

    The check runs before the store rather than after it. A crosswalk whose hex
    population does not match the block population it was built from is wrong
    in the geometry, and writing it first would leave the county's previous
    weights replaced by worse ones before anyone found out.
    """
    overlaps = await postgis.load_block_overlaps(conn, county_fips=county_fips)
    crosswalk = build_crosswalk(overlaps)
    reconciliation = require(reconcile_crosswalk(crosswalk, relative_tolerance=relative_tolerance))

    async with conn.transaction():
        rows = await postgis.store_crosswalk(conn, crosswalk, county_fips=county_fips)

    return CountyCrosswalk(
        county_fips=county_fips,
        rows_written=rows,
        report=crosswalk.report,
        reconciliation=reconciliation,
    )


async def build_state_crosswalk(
    conn: postgis.Connection,
    *,
    state_fips: str,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
    on_county: Callable[[CountyCrosswalk], None] | None = None,
) -> StateCrosswalk:
    """Build and store `tract_hex_weight` for every county in the pilot state.

    Raises `ReconciliationFailed` on the first county whose crosswalk does not
    match its own block layer, leaving the counties already built in place. That
    is deliberate: the failure is in one county's geometry, the counties before
    it are correct, and a re-run after the fix starts from the county that
    broke rather than from the beginning.
    """
    names = await postgis.counties(conn, state_fips=state_fips)
    results: list[CountyCrosswalk] = []
    for county_fips in names:
        result = await build_county_crosswalk(
            conn, county_fips=county_fips, relative_tolerance=relative_tolerance
        )
        log.info(
            "county %s: %d weights, %d blocks, %d hexes",
            county_fips,
            result.rows_written,
            result.report.block_count,
            result.report.hex_count,
        )
        results.append(result)
        if on_county is not None:
            on_county(result)
    return StateCrosswalk(state_fips=state_fips, counties=tuple(results))


@dataclass(frozen=True, slots=True)
class PopulationCheck:
    """The statewide acceptance of section 7, with what it was measured on."""

    variable: str
    acs_vintage: str
    tract_count: int
    hex_count: int
    reconciliation: Reconciliation

    @property
    def ok(self) -> bool:
        return self.reconciliation.ok

    def describe(self) -> str:
        return "\n".join(
            [
                f"statewide check on {self.variable} ({self.acs_vintage}): "
                f"{self.tract_count:,} tracts -> {self.hex_count:,} hexes",
                self.reconciliation.describe(),
            ]
        )


async def verify_statewide_population(
    conn: postgis.Connection,
    *,
    acs_vintage: str,
    variable: str = TOTAL_POPULATION,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> PopulationCheck:
    """Interpolate one published count statewide and compare it to its source.

    This is the acceptance criterion of section 7 and of CS-106: statewide
    totals after interpolation match tract totals within a documented
    tolerance. The tolerance and the argument for its value are in
    `pipeline.dasymetric.reconcile`.

    The crosswalk is read back from `tract_hex_weight` rather than passed in,
    so the check runs against the rows that were actually stored. A check
    against an in-memory crosswalk would pass even if `store_crosswalk` had
    written something else.

    The crosswalk is also handed to `reconcile_population`, which is what lets
    a tract the interpolation never reached, because no block of it meets the
    hex grid, be named and subtracted rather than read as arithmetic that lost
    people. Those are different defects with different fixes and the message
    says which one happened.
    """
    estimates = await postgis.load_tract_estimates(conn, variable=variable, acs_vintage=acs_vintage)
    if not estimates:
        raise ValueError(
            f"no tract_demographics rows for {variable!r} at vintage {acs_vintage!r}; "
            "the statewide check has nothing to check"
        )
    for estimate in estimates:
        if estimate.kind is not Kind.EXTENSIVE:
            raise KindMismatch(
                f"{variable!r} is stored as {estimate.kind.value}; the statewide "
                "reconciliation compares totals, which only counts have"
            )

    crosswalk = await postgis.load_crosswalk(conn)
    values = interpolate_extensive(crosswalk, estimates)
    published: Mapping[str, float] = {
        estimate.tract_geoid: float(estimate.estimate or 0.0)
        for estimate in estimates
        if estimate.present
    }

    return PopulationCheck(
        variable=variable,
        acs_vintage=acs_vintage,
        tract_count=len(published),
        hex_count=sum(1 for value in values.values() if value.present),
        reconciliation=reconcile_population(
            published,
            values.values(),
            crosswalk=crosswalk,
            relative_tolerance=relative_tolerance,
        ),
    )


async def build_and_verify(
    conn: postgis.Connection,
    *,
    state_fips: str,
    acs_vintage: str,
    variable: str = TOTAL_POPULATION,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> tuple[StateCrosswalk, PopulationCheck]:
    """The whole of section 7 for one state: build the crosswalk, then check it.

    `require` is applied to the statewide result, so a caller that reaches the
    return value has a crosswalk whose totals closed. CS-108's quality gate is
    the intended caller.
    """
    crosswalk = await build_state_crosswalk(
        conn, state_fips=state_fips, relative_tolerance=relative_tolerance
    )
    check = await verify_statewide_population(
        conn,
        acs_vintage=acs_vintage,
        variable=variable,
        relative_tolerance=relative_tolerance,
    )
    require(check.reconciliation)
    return crosswalk, check
