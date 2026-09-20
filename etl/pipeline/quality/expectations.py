"""What each of the five Phase 1 sources should look like after a good load.

These are the thresholds CS-108 adds on top of the interface's generic ones. The
interface already refuses a pull that rejected too many records; it has no way to
notice that a pull kept every record and still returned a third of Louisiana, or
that a modeled cancer risk arrived three orders of magnitude too large because a
unit changed upstream. That needs a number per source, and a number per source
needs a reason.

**Every threshold below carries the reason it holds that value.** A threshold
without one gets tightened by whoever is on call at 2am and stops meaning
anything. Two kinds appear here and they are labelled:

*Grounded* numbers come from something checkable — a published tract count, a row
count observed against the live service and recorded in the adapter that observed
it. These are tight, because a violation really is a defect.

*Envelope* numbers are deliberately loose. Four of these five adapters have not
yet run against live upstream, so a tight range would be a guess that fails the
first honest night. They are set to catch catastrophe — a source returning
nothing, a join fanning out, a unit changing — and not to catch drift. Every gate
run persists the value it observed (`quality.store`), so after a fortnight of
nightly runs these get replaced by ranges taken from history rather than from
judgement. That is the whole reason "trends over time are visible" is an
acceptance criterion and not a nicety.

**Where these live.** An adapter owns its own domain knowledge, so the intended
home for each declaration is an `expectations` class variable on the adapter, the
way `policy` already works. CS-102 through CS-105 are on unmerged branches, so
the five declarations sit here keyed by registry name and `for_source` prefers
whatever the adapter class declares. As each adapter merges, its entry moves onto
its class and drops out of `TUNED`. `test_quality_checks.py` holds the guard
that every rule still names a field its record class actually has, and it starts
covering each adapter the day that adapter's branch lands.
"""

from typing import Any

from pipeline.quality.checks import (
    Bounds,
    Categories,
    Geometry,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
)

# Louisiana had 1,388 census tracts in the 2020 TIGER release. The ranges below
# bracket it rather than pinning it, because a tract count changes with a
# decennial redistricting and a boundary revision, and the gate should report
# that as a number to look at rather than as a failed night.
LA_TRACTS_LOW = 1_200
LA_TRACTS_HIGH = 1_600


EPA_ECHO = SourceExpectations(
    source="epa_echo",
    tables=(
        TableExpectations(
            table="facility",
            # Grounded, loosely. The adapter's own module docstring records
            # 13,842 Louisiana air facilities from the live service, of which
            # roughly one row in twenty-three repeats a registry id, so distinct
            # sites land near 13,200. The range is wide on both sides because
            # ECHO refreshes weekly and permits are issued and retired.
            rows=RowCount(9_000, 20_000, note="Live service returned ~13.8k rows, ~13.2k sites."),
            null_rates=(
                NullRate("facility_id", 0.0),
                NullRate("registry_id", 0.0),
                NullRate("name", 0.0, note="validate rejects an unnamed site, so this must be 0."),
                NullRate("echo_url", 0.0),
                # Coordinates are self-reported and section 6 expects some to be
                # missing or wrong. A tenth is tolerable; a third means the
                # coordinate columns moved.
                NullRate("latitude", 0.10),
                NullRate("longitude", 0.10),
                NullRate("h3", 0.10),
                NullRate("county_fips", 0.05),
                NullRate("naics_code", 0.35, severity="warn", note="Often blank upstream."),
            ),
            geometry=(
                Geometry("latitude", "latitude", max_invalid_fraction=0.01),
                Geometry("longitude", "longitude", max_invalid_fraction=0.01),
                Geometry("h3", "h3_cell"),
            ),
            categories=(
                Categories(
                    "coordinate_status",
                    frozenset({"ok", "missing", "outside_state", "zip_mismatch"}),
                    note="Section 6 publishes the exclusion count, so the codes must stay mapped.",
                ),
            ),
        ),
        TableExpectations(
            table="facility_compliance_quarter",
            # Envelope. Twelve quarters per facility that reports a history, and
            # not every facility does. Below one per facility the history column
            # has stopped arriving, which would silently zero F2.
            rows=RowCount(9_000, 260_000, note="Up to 12 quarters per site; F2 depends on it."),
            null_rates=(NullRate("facility_id", 0.0), NullRate("quarter", 0.0)),
            categories=(
                Categories(
                    "status",
                    frozenset({"high_priority_violation", "violation", "in_compliance", "unknown"}),
                    note="An unmapped quarter code reads downstream as compliance.",
                ),
                Categories("program", frozenset({"CAA"})),
            ),
        ),
        TableExpectations(
            table="enforcement_action",
            # Envelope, and deliberately floored at zero: a quiet five years is a
            # real answer, so an empty table warns rather than fails.
            rows=RowCount(0, 60_000, severity="warn", note="F3 covers five years of actions."),
            null_rates=(NullRate("action_id", 0.0), NullRate("facility_id", 0.0)),
            bounds=(
                Bounds(
                    "penalty_usd",
                    low=0.0,
                    high=1_000_000_000.0,
                    note="A negative penalty is a parse error; a billion-dollar one "
                    "is a unit error.",
                ),
            ),
        ),
    ),
    notes=(
        "F2 and F3 partly measure regulatory attention rather than pollution "
        "(methodology section 8.2). These checks test the data, not that bias.",
    ),
)


EPA_TRI = SourceExpectations(
    source="epa_tri",
    tables=(
        TableExpectations(
            table="tri_release",
            # Envelope. One row per facility per chemical per year; Louisiana
            # files in the low thousands. The floor catches a reporting year that
            # returned nothing, the ceiling a year dimension that stopped being
            # filtered.
            rows=RowCount(800, 40_000, note="Facility x chemical x year, one reporting year."),
            null_rates=(
                NullRate("facility_id", 0.0),
                NullRate("cas_number", 0.0),
                NullRate("chemical_name", 0.0),
                # A Form A filer certifies below a threshold without giving a
                # quantity, so an absent measurement here is correct and common.
                # Section 11: absent is not zero, and this rule is what proves
                # the adapter kept the difference rather than defaulting to 0.0.
                NullRate(
                    "fugitive_air",
                    0.60,
                    severity="warn",
                    note="Form A filings report no quantity. All-absent means the columns moved.",
                ),
                NullRate("stack_air", 0.60, severity="warn"),
            ),
            bounds=(
                Bounds(
                    "fugitive_air",
                    low=0.0,
                    high=50_000_000.0,
                    note="Pounds per year. Negative is a parse error; 50M lb exceeds "
                    "any US filing.",
                ),
                Bounds("stack_air", low=0.0, high=50_000_000.0),
                Bounds(
                    "reporting_year",
                    low=1987.0,
                    high=2100.0,
                    note="TRI began in 1987. A year outside this is a column read as "
                    "the wrong field.",
                ),
            ),
        ),
    ),
    notes=(
        "Vintage is the reporting year, not the download date, so one pull holds "
        "one year and the row count should not vary with when it ran.",
    ),
)


AIRTOXSCREEN = SourceExpectations(
    source="airtoxscreen",
    tables=(
        TableExpectations(
            table="tract_exposure",
            # Grounded. AirToxScreen publishes every census tract, so this table
            # should hold one row per Louisiana tract and a shortfall is missing
            # coverage rather than a quiet source.
            rows=RowCount(LA_TRACTS_LOW, LA_TRACTS_HIGH, note="One row per Louisiana tract."),
            null_rates=(
                NullRate("tract_geoid", 0.0),
                # E1 and E2 are the primary pollution inputs precisely because
                # the model covers every area evenly. A tract without a value is
                # a real absence and must stay rare.
                NullRate("cancer_risk_per_million", 0.02),
                NullRate("respiratory_hazard_index", 0.02),
            ),
            bounds=(
                Bounds(
                    "cancer_risk_per_million",
                    low=0.0,
                    high=2_000.0,
                    note="Risk per million. National tract values run tens to low hundreds; "
                    "2000 is generous headroom and still catches a unit change.",
                ),
                Bounds(
                    "respiratory_hazard_index",
                    low=0.0,
                    high=50.0,
                    note="A hazard index is a ratio to a reference concentration, order 1.",
                ),
            ),
            geometry=(Geometry("tract_geoid", "tract_geoid"),),
        ),
        TableExpectations(
            table="hex_exposure",
            # Envelope, and the loosest here by some distance. The hex grid is
            # CS-007 and is not built, so the count follows from Louisiana's land
            # area over the ~0.74 km2 area of a resolution 8 cell, plus coastal
            # water. Replace this range with the grid's own cell count as soon as
            # CS-007 fixes it.
            rows=RowCount(
                60_000,
                400_000,
                note="Provisional: derived from area, not from the CS-007 grid. Retune on CS-007.",
            ),
            null_rates=(NullRate("h3", 0.0), NullRate("vintage_year", 0.0)),
            bounds=(
                Bounds("cancer_risk_per_million", low=0.0, high=2_000.0),
                Bounds("respiratory_hazard_index", low=0.0, high=50.0),
                Bounds(
                    "tract_count",
                    low=0.0,
                    high=200.0,
                    note="Tracts overlapping one 0.74 km2 hex. Dozens is dense urban; "
                    "hundreds is a bad join.",
                ),
                Bounds("population", low=0.0, high=100_000.0),
            ),
            geometry=(Geometry("h3", "h3_cell", allow_null=False),),
        ),
    ),
    notes=(
        "Section 7: these are intensive quantities, combined as a "
        "population-weighted mean. The bounds are the same on the tract table and "
        "the hex table on purpose, because interpolating an intensive quantity "
        "must not move it outside the range of its inputs.",
    ),
)


OPENAQ = SourceExpectations(
    source="openaq",
    tables=(
        TableExpectations(
            table="monitor",
            # Envelope. Louisiana runs a few dozen regulatory PM2.5 sites; OpenAQ
            # also carries low-cost sensors, so the ceiling is generous. The
            # point of the floor is that E4 and the c_monitor confidence term
            # both become meaningless with no monitors at all.
            rows=RowCount(5, 2_000, note="Regulatory sites are a few dozen; sensors add more."),
            null_rates=(
                NullRate("monitor_id", 0.0),
                NullRate("h3", 0.0),
                NullRate("latitude", 0.0),
                NullRate("longitude", 0.0),
            ),
            geometry=(
                Geometry("latitude", "latitude", allow_null=False),
                Geometry("longitude", "longitude", allow_null=False),
                Geometry("h3", "h3_cell", allow_null=False),
            ),
        ),
        TableExpectations(
            table="monitor_measurement",
            rows=RowCount(0, 5_000_000, severity="warn", note="Daily means, one row per site-day."),
            null_rates=(NullRate("monitor_id", 0.0), NullRate("measured_on", 0.0)),
            bounds=(
                Bounds(
                    "value",
                    low=0.0,
                    high=1_000.0,
                    max_outside_fraction=0.001,
                    note="ug/m3 daily mean. Wildfire smoke reaches the hundreds; above 1000 is a "
                    "faulty sensor, and CS-104 rejects those in validate. A survivor here means "
                    "that rule stopped firing.",
                ),
                Bounds(
                    "observation_count", low=1.0, high=1_440.0, note="At most one reading a minute."
                ),
            ),
            categories=(Categories("unit", frozenset({"ug/m3", "µg/m³", "ppm", "ppb"})),),
        ),
        TableExpectations(
            table="hex_air_quality",
            rows=RowCount(0, 400_000, severity="warn"),
            null_rates=(
                NullRate("h3", 0.0),
                NullRate("nearest_monitor_km", 0.0),
                # Most of the state is beyond the 25 km interpolation radius, so
                # an absent annual mean is the expected case, not a fault. This
                # rule exists only to catch the opposite: every hex observed,
                # which would mean the radius stopped being applied and a
                # neighbour's reading is being spread across the state.
                NullRate(
                    "annual_mean",
                    1.0,
                    severity="warn",
                    note="Absence is expected beyond 25 km. Cross-source checks test the shape.",
                ),
            ),
            bounds=(
                Bounds("annual_mean", low=0.0, high=500.0),
                Bounds(
                    "nearest_monitor_km",
                    low=0.0,
                    high=1_000.0,
                    note="Feeds c_monitor = min(1, 10 km / d). A negative or absurd distance "
                    "inflates confidence for an unmeasured hex.",
                ),
            ),
            geometry=(Geometry("h3", "h3_cell", allow_null=False),),
        ),
    ),
    notes=(
        "An unmonitored area is uncertain, not clean. These checks are written so "
        "that widespread absence passes and widespread presence is what draws "
        "attention.",
    ),
)


CENSUS_ACS = SourceExpectations(
    source="census_acs",
    tables=(
        TableExpectations(
            table="census_tract",
            rows=RowCount(
                LA_TRACTS_LOW, LA_TRACTS_HIGH, note="2020 TIGER: 1,388 Louisiana tracts."
            ),
            null_rates=(
                NullRate("geoid", 0.0),
                NullRate("geom_wkt", 0.0),
                NullRate("state_fips", 0.0),
                NullRate("county_fips", 0.0),
            ),
            bounds=(
                Bounds(
                    "aland_m2",
                    low=0.0,
                    high=20_000_000_000.0,
                    note="20,000 km2 exceeds any Louisiana tract; a larger one is a units error.",
                ),
                Bounds("awater_m2", low=0.0, high=20_000_000_000.0),
            ),
            geometry=(
                Geometry("geoid", "tract_geoid", allow_null=False),
                Geometry(
                    "geom_wkt",
                    "wkt_polygon",
                    allow_null=False,
                    note="Rings must close and sit inside the pilot envelope; PostGIS "
                    "refuses the rest.",
                ),
            ),
            categories=(Categories("state_fips", frozenset({"22"})),),
        ),
        TableExpectations(
            table="tract_demographics",
            # Envelope. Tracts times the ACS variables behind S1, S2 and P1-P5.
            # The floor is one variable per tract, which is the point below which
            # a subgroup mean cannot be computed for anyone.
            rows=RowCount(
                LA_TRACTS_LOW,
                200_000,
                note="One row per tract per variable, long rather than wide (section 7).",
            ),
            null_rates=(
                NullRate("tract_geoid", 0.0),
                NullRate("variable", 0.0),
                NullRate("acs_vintage", 0.0),
                # ACS jam values are genuine absences and small tracts get them
                # often. Section 7 forbids dropping high-uncertainty estimates,
                # so this is set where a real survey gap passes and a broken
                # parse does not.
                NullRate(
                    "estimate",
                    0.25,
                    severity="warn",
                    note="Jam values are absences, not zeroes. A spike means the parse broke.",
                ),
                NullRate("margin_of_error", 0.30, severity="warn"),
            ),
            bounds=(
                Bounds(
                    "estimate",
                    low=-1_000_000.0,
                    high=10_000_000.0,
                    note="Wide because the table mixes counts, dollars and percentages. Its job "
                    "is to catch an ACS jam value that was parsed as a number rather than an "
                    "absence: those are large negatives such as -666666666.",
                ),
                Bounds("margin_of_error", low=0.0, high=10_000_000.0),
            ),
            geometry=(Geometry("tract_geoid", "tract_geoid", allow_null=False),),
        ),
        TableExpectations(
            table="tract_race_ethnicity",
            rows=RowCount(LA_TRACTS_LOW, 200_000),
            null_rates=(NullRate("tract_geoid", 0.0), NullRate("variable", 0.0)),
            bounds=(Bounds("estimate", low=-1_000_000.0, high=10_000_000.0),),
            geometry=(Geometry("tract_geoid", "tract_geoid", allow_null=False),),
        ),
    ),
    notes=(
        "Section 14: the race and ethnicity table is checked exactly like the "
        "scored one and is never joined into it. The separation is what makes the "
        "section 13.6 disparity finding an independent result.",
    ),
)


# Keyed by registry name. See the module docstring for why this table exists and
# when each entry leaves it.
TUNED: dict[str, SourceExpectations] = {
    e.source: e for e in (EPA_ECHO, EPA_TRI, AIRTOXSCREEN, OPENAQ, CENSUS_ACS)
}


def for_source(name: str, adapter: Any = None) -> SourceExpectations | None:
    """The expectations that apply to one source, or None if it has declared none.

    The adapter class wins, because domain knowledge belongs with the adapter.
    `None` is a real answer and the gate reports it as a gap: a source running
    with no thresholds beyond the interface default is exactly the state CS-108
    exists to make visible.
    """
    declared = getattr(adapter, "expectations", None)
    if isinstance(declared, SourceExpectations) and declared.tables:
        return declared
    return TUNED.get(name)


__all__ = [
    "AIRTOXSCREEN",
    "CENSUS_ACS",
    "EPA_ECHO",
    "EPA_TRI",
    "LA_TRACTS_HIGH",
    "LA_TRACTS_LOW",
    "OPENAQ",
    "TUNED",
    "for_source",
]
