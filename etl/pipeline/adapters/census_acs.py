"""US Census ACS 5-year: tract demographics, and the tract polygons they sit on.

Feeds S1 and S2 (methodology section 8.3) and P1 through P5 (section 8.4), plus
the race and ethnicity variables of section 8.5 that are recorded, displayed and
analysed but never scored.

Two structural decisions before the details.

**Only published counts are pulled.** Every variable in `SCORED` and `RACE` is
an ACS count, so every row this adapter writes has `is_extensive = true`.
Section 7 forbids recomputing a rate from independently interpolated parts, and
requires that where a rate has a published numerator and denominator, both are
interpolated as extensive quantities and the rate derived once at the end.
Pulling only counts is what makes that the only thing CS-106 *can* do. The
recipes in `INDICATORS` say which counts divide by which; nothing here divides.

**Race and ethnicity go to their own table.** They are stored in
`tract_race_ethnicity`, not in `tract_demographics`, so no indicator query can
reach them by widening a variable filter. Section 14 argues at length that
keeping race out of the arithmetic is what makes the disparity finding of
section 13.6 an independent result rather than a built-in one; a table boundary
enforces that better than a naming convention. `SCORED` and `RACE` are disjoint
and a test holds them so.

Five things about the two upstream services that shaped this adapter, all
established by querying them on 2026-09-11 rather than assumed.

**The data API now requires a key.** Every `?get=` query redirects to
`missing_key.html` without one and to `invalid_key.html` with a bad one, for the
current ACS and for older datasets alike. The historical keyless allowance for
small query volumes is gone. The key arrives through `ctx.credentials` and is
passed as `secret_params` so that it stays out of the artifact URLs, which are
published verbatim in docs/provenance.md.

**The newest 5-year release is 2020-2024.** The variables endpoint answers for
2021 through 2024 and 404s for 2025. `ACS_YEAR` is pinned rather than
discovered, on the same reasoning as `GAZETTEER_YEAR` in the ECHO adapter: a
vintage that advances on its own would change every number on the map on a
night nobody chose. Until it is bumped the recency term of section 12 correctly
reports the data getting older.

**C16002's limited-English variables are not the ones the numbering suggests.**
Position 002 is "English only", and each language block then lists the limited
household *before* the unlimited one, so P3's numerator is 004, 007, 010 and
013. Reading the pattern off the table name would have taken the complements
and inverted the indicator.

**ACS publishes no low-income-by-severe-cost cross tabulation at tract level.**
B25106 crosses tenure and household income against housing cost, and its finest
cost cut is "30 percent or more"; there is no 50 percent bracket. Section 8.4
defines P5 as low-income households paying more than 50 percent, which is
therefore not computable from ACS alone. See `HOUSING_BURDEN_GAP` for what is
stored instead and what it costs.

**TIGERweb refuses a whole-state geometry query.** A statewide tract query with
geometry is rejected outright by a web application firewall, while the same
query paged at 200 features succeeds and one parish at a time succeeds. Paging
needs `orderByFields`, because ArcGIS `resultOffset` without an ordering is not
a stable window and pages would overlap and skip.
"""

import json
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.metadata import Artifact, KnownGap, SourceSpec
from pipeline.policy import RateLimit, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord

# The credential this adapter asks `ctx.credentials` for. Free, instant, and
# obtained from https://api.census.gov/data/key_signup.html.
CREDENTIAL = "census_api_key"

# The pinned release. 2024 means the 2020-2024 five-year window; see the module
# docstring on why this is a constant somebody bumps rather than a probe.
ACS_YEAR = 2024
ACS_WINDOW = f"{ACS_YEAR - 4}-{ACS_YEAR}"

# Two spellings of one release, both deliberate. The manifest's vintage follows
# the form the adapter interface documents (`acs5_2019_2023`); the column that
# keys tract_demographics follows the form the schema documents ('2019-2023').
VINTAGE = f"acs5_{ACS_YEAR - 4}_{ACS_YEAR}"

ACS_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"

# Geography from the TIGER vintage that matches the ACS release, so tracts nest
# inside the state boundary exactly instead of nearly.
TIGER_YEAR = ACS_YEAR
TIGERWEB = (
    f"https://tigerweb.geo.census.gov/arcgis/rest/services/"
    f"TIGERweb/tigerWMS_ACS{TIGER_YEAR}/MapServer"
)
TRACT_LAYER = 8
STATE_LAYER = 80

STATE_FIPS: Mapping[str, str] = {"LA": "22"}

# The API caps `get=` at 50 variables. Each variable is requested as an estimate
# and a margin, so a request carries half that many.
MAX_GET_FIELDS = 50
VARIABLES_PER_REQUEST = MAX_GET_FIELDS // 2

# 200 features per page keeps a response near five megabytes, which the firewall
# in front of TIGERweb accepts; a statewide query does not. The page cap is
# generous for any state: Louisiana is 1,388 tracts, Texas about 6,900.
GEOMETRY_PAGE_SIZE = 200
MAX_GEOMETRY_PAGES = 60

# Seven decimal places is about a centimetre. TIGERweb returns fifteen, which
# inflates every polygon in the state for precision no census boundary has.
WKT_PRECISION = 7

# Section 12: an estimate whose coefficient of variation exceeds this is used
# anyway and lowers c_spatial. There is deliberately no threshold at which one
# is dropped, because dropping high-uncertainty estimates preferentially removes
# small and rural populations.
CV_THRESHOLD = 0.30

# ACS margins are published at the 90 percent confidence level.
MOE_TO_STANDARD_ERROR = 1.645

# The Census "jam values": numbers in the estimate and margin columns that are
# not measurements. Anything at or below the least of them is one of these.
# Mapping them to zero rather than to absent is the exact error section 11
# forbids, and it would read as "nobody here is in poverty" for a tract the
# survey could not measure.
JAM_CEILING = -111111111

# The single jam value that carries information rather than an absence. A
# controlled estimate is one the Bureau fixed to an independent population
# total, so it has no sampling error and its coefficient of variation is zero,
# which is the best a c_spatial input can be.
MOE_CONTROLLED = -555555555


@dataclass(frozen=True, slots=True)
class AcsVariable:
    """One published ACS variable, with the label the API reports for it."""

    code: str
    label: str
    # False for a rate, ratio or median. Nothing here sets it: see the module
    # docstring on why the adapter pulls only counts. It exists because
    # tract_demographics has the column and a later ticket may need it.
    extensive: bool = True

    @property
    def estimate_field(self) -> str:
        return f"{self.code}E"

    @property
    def margin_field(self) -> str:
        return f"{self.code}M"


def _sequence(table: str, numbers: Sequence[int], label: str) -> tuple[AcsVariable, ...]:
    """A run of variables from one table sharing a label. Ranges are pinned by test."""
    return tuple(AcsVariable(code=f"{table}_{n:03d}", label=label) for n in numbers)


# ---- what is pulled ----------------------------------------------------
#
# Every code and every label below was read from
# https://api.census.gov/data/2024/acs/acs5/groups/<table>.json on 2026-09-11.
# The endpoint needs no key, so `test_the_declared_variables_match_the_tables`
# can be re-pointed at it whenever a release is bumped.

POPULATION = AcsVariable("B01003_001", "total population")
AGE_TOTAL = AcsVariable("B01001_001", "total population by sex and age")
HOUSEHOLDS = AcsVariable("B11001_001", "total households")

UNDER_5 = (
    AcsVariable("B01001_003", "male under 5 years"),
    AcsVariable("B01001_027", "female under 5 years"),
)
# 020 to 025 is male 65-66 through 85 and over; 044 to 049 is the same for
# female. 019 and 043 are the 62-to-64 brackets and are correctly excluded.
OVER_64 = _sequence("B01001", range(20, 26), "male 65 years and over") + _sequence(
    "B01001", range(44, 50), "female 65 years and over"
)

# C17002 is the collapsed ratio-of-income-to-poverty table. 002 through 007 run
# from "Under .50" to "1.85 to 1.99"; 008 is "2.00 and over".
POVERTY_TOTAL = AcsVariable("C17002_001", "population with a poverty ratio determined")
UNDER_200_POVERTY = _sequence("C17002", range(2, 8), "income below 200% of the poverty level")

# B15003 covers the population 25 and over. 002 is "No schooling completed" and
# 016 is "12th grade, no diploma"; 017 is the first credential.
EDUCATION_TOTAL = AcsVariable("B15003_001", "population 25 years and over")
NO_DIPLOMA = _sequence("B15003", range(2, 17), "no high school diploma")

# See the module docstring: the limited household is the first entry in each
# language block, not the second.
LANGUAGE_TOTAL = AcsVariable("C16002_001", "total households")
LIMITED_ENGLISH = (
    AcsVariable("C16002_004", "Spanish-speaking limited English household"),
    AcsVariable("C16002_007", "other Indo-European limited English household"),
    AcsVariable("C16002_010", "Asian and Pacific Island limited English household"),
    AcsVariable("C16002_013", "other language limited English household"),
)

LABOUR_FORCE = (
    AcsVariable("B23025_001", "population 16 years and over"),
    AcsVariable("B23025_003", "civilian labour force"),
    AcsVariable("B23025_004", "civilian labour force, employed"),
    AcsVariable("B23025_005", "civilian labour force, unemployed"),
)

# B25106 crosses tenure and household income against housing cost. The four
# totals are the low-income households; the four "30 percent or more" cells are
# the burdened ones among them. There is no 50 percent bracket to use instead.
HOUSING_TOTAL = AcsVariable("B25106_001", "occupied housing units")
LOW_INCOME_HOUSEHOLDS = (
    AcsVariable("B25106_003", "owner households under $20,000"),
    AcsVariable("B25106_007", "owner households $20,000 to $34,999"),
    AcsVariable("B25106_025", "renter households under $20,000"),
    AcsVariable("B25106_029", "renter households $20,000 to $34,999"),
)
LOW_INCOME_BURDENED = (
    AcsVariable("B25106_006", "owner under $20,000 paying 30% or more"),
    AcsVariable("B25106_010", "owner $20,000 to $34,999 paying 30% or more"),
    AcsVariable("B25106_028", "renter under $20,000 paying 30% or more"),
    AcsVariable("B25106_032", "renter $20,000 to $34,999 paying 30% or more"),
)
# The severe-burden half of section 8.4's definition, at every income level
# because ACS publishes it no other way. Stored so that the 50 percent
# threshold stays recoverable without a second pull; see HOUSING_BURDEN_GAP.
SEVERE_BURDEN = (
    AcsVariable("B25070_001", "renter households with gross rent computed"),
    AcsVariable("B25070_010", "renter households paying 50% or more of income"),
    AcsVariable("B25091_001", "owner households with costs computed"),
    AcsVariable("B25091_011", "owner with a mortgage paying 50% or more of income"),
    AcsVariable("B25091_022", "owner without a mortgage paying 50% or more of income"),
)

SCORED: tuple[AcsVariable, ...] = (
    POPULATION,
    AGE_TOTAL,
    HOUSEHOLDS,
    *UNDER_5,
    *OVER_64,
    POVERTY_TOTAL,
    *UNDER_200_POVERTY,
    EDUCATION_TOTAL,
    *NO_DIPLOMA,
    LANGUAGE_TOTAL,
    *LIMITED_ENGLISH,
    *LABOUR_FORCE,
    HOUSING_TOTAL,
    *LOW_INCOME_HOUSEHOLDS,
    *LOW_INCOME_BURDENED,
    *SEVERE_BURDEN,
)

# Section 8.5. Recorded, displayed on every hex, and used in the disparity
# analysis of section 13.6. Never an input to any indicator, which is why they
# are written to a different table. B03002 crosses race with Hispanic origin;
# B02001_003 is the "Black or African American alone" total of any ethnicity,
# which is the headline the hex panel shows.
RACE: tuple[AcsVariable, ...] = (
    AcsVariable("B03002_001", "total population"),
    AcsVariable("B03002_002", "not Hispanic or Latino"),
    AcsVariable("B03002_003", "not Hispanic, White alone"),
    AcsVariable("B03002_004", "not Hispanic, Black or African American alone"),
    AcsVariable("B03002_005", "not Hispanic, American Indian and Alaska Native alone"),
    AcsVariable("B03002_006", "not Hispanic, Asian alone"),
    AcsVariable("B03002_007", "not Hispanic, Native Hawaiian and Other Pacific Islander alone"),
    AcsVariable("B03002_008", "not Hispanic, some other race alone"),
    AcsVariable("B03002_009", "not Hispanic, two or more races"),
    AcsVariable("B03002_012", "Hispanic or Latino"),
    AcsVariable("B02001_001", "total population"),
    AcsVariable("B02001_003", "Black or African American alone"),
)

PULLED: tuple[AcsVariable, ...] = SCORED + RACE


@dataclass(frozen=True, slots=True)
class Indicator:
    """Which published counts an indicator divides by which.

    Declared here and read by CS-106, so the numerator and denominator are
    interpolated as extensive quantities and the rate is formed once at the end,
    which is what section 7 requires. Nothing in this module evaluates one.
    """

    id: str
    label: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    note: str = ""


def _codes(*groups: Sequence[AcsVariable]) -> tuple[str, ...]:
    return tuple(variable.code for group in groups for variable in group)


INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        id="S1",
        label="percent of population under 5",
        numerator=_codes(UNDER_5),
        denominator=(AGE_TOTAL.code,),
    ),
    Indicator(
        id="S2",
        label="percent of population 65 and over",
        numerator=_codes(OVER_64),
        denominator=(AGE_TOTAL.code,),
    ),
    Indicator(
        id="P1",
        label="percent below 200% of the federal poverty level",
        numerator=_codes(UNDER_200_POVERTY),
        denominator=(POVERTY_TOTAL.code,),
        note=(
            "The denominator is the population for whom a poverty ratio was determined, "
            "which excludes people in institutions and unrelated people under 15. It is "
            "smaller than the tract population and is the correct denominator."
        ),
    ),
    Indicator(
        id="P2",
        label="percent of adults 25 and over without a high school diploma",
        numerator=_codes(NO_DIPLOMA),
        denominator=(EDUCATION_TOTAL.code,),
    ),
    Indicator(
        id="P3",
        label="percent of households with no member 14+ speaking English very well",
        numerator=_codes(LIMITED_ENGLISH),
        denominator=(LANGUAGE_TOTAL.code,),
    ),
    Indicator(
        id="P4",
        label="percent of the civilian labour force unemployed",
        numerator=("B23025_005",),
        denominator=("B23025_003",),
        note="The denominator is the civilian labour force, so it excludes the armed forces.",
    ),
    Indicator(
        id="P5",
        label="percent of low-income households paying 30% or more of income on housing",
        numerator=_codes(LOW_INCOME_BURDENED),
        denominator=_codes(LOW_INCOME_HOUSEHOLDS),
        note=(
            "Section 8.4 defines P5 at more than 50 percent of income. ACS publishes no "
            "low-income-by-severe-cost cross tabulation at tract level, so this recipe "
            "keeps the low-income half of the definition and takes the 30 percent cut "
            "that B25106 does publish. See HOUSING_BURDEN_GAP."
        ),
    ),
)


# ---- records -----------------------------------------------------------


class CensusTract(NormalizedRecord):
    """One TIGER tract polygon, validated against the state boundary."""

    table: ClassVar[str] = "census_tract"

    geoid: str
    state_fips: str
    county_fips: str
    name: str | None
    geom_wkt: str
    aland_m2: int | None
    awater_m2: int | None
    tiger_year: int

    def natural_key(self) -> tuple[str, ...]:
        return (self.geoid,)


class TractVariable(NormalizedRecord):
    """One tract, one release, one variable: the estimate and its margin.

    Long rather than wide, because section 7 forbids recomputing a rate from
    independently interpolated parts and a wide table invites exactly that.

    Both numbers are `Measurement`s. An ACS count of zero is an observation: no
    households in a tract are linguistically isolated. A jam value is an
    absence: the survey could not measure the tract. Section 11 turns on the
    difference and the type refuses to blur it.

    Abstract in the one way that matters: it sets no `table`. The two concrete
    subclasses below are siblings rather than one deriving from the other, so no
    `isinstance` check for a scored row can ever match a race row.
    """

    tract_geoid: str
    acs_vintage: str
    # Keeps the published `E` suffix, as the schema's own example does, even
    # though the row carries the margin too. The margin is the same id with `M`.
    variable: str
    estimate: Measurement
    margin_of_error: Measurement
    is_extensive: bool

    def natural_key(self) -> tuple[str, ...]:
        return (self.tract_geoid, self.acs_vintage, self.variable)

    @property
    def coefficient_of_variation(self) -> float | None:
        """`(margin / 1.645) / estimate`, or None where it is not defined.

        The one place this ratio is computed. It travels into `c_spatial`
        (section 12), where a value above 0.30 lowers the hex's confidence and
        never removes its estimate. Undefined for an absent estimate and for a
        zero estimate, where the ratio has no meaning rather than a large value.
        """
        if not self.estimate.observed or not self.margin_of_error.observed:
            return None
        estimate, margin = self.estimate.value, self.margin_of_error.value
        if estimate is None or margin is None or estimate <= 0:
            return None
        return (margin / MOE_TO_STANDARD_ERROR) / estimate


class TractEstimate(TractVariable):
    """A variable that feeds an indicator. Goes to `tract_demographics`."""

    table: ClassVar[str] = "tract_demographics"


class TractRaceEthnicity(TractVariable):
    """Section 8.5, in a table no indicator query reads.

    Identical in shape to `TractEstimate` and separate in destination. The
    separation is the point: section 14 keeps race out of the arithmetic so that
    the disparity finding of section 13.6 is an independent result, and a table
    boundary survives a future widened `WHERE variable LIKE` in a way a naming
    convention does not.
    """

    table: ClassVar[str] = "tract_race_ethnicity"


# ---- geometry ----------------------------------------------------------

Ring = tuple[tuple[float, float], ...]
Polygon = tuple[Ring, ...]


def rings_of(geometry: Mapping[str, object]) -> tuple[Polygon, ...]:
    """A GeoJSON Polygon or MultiPolygon as nested tuples of positions.

    TIGERweb returns single-part tracts as `Polygon` and island parishes as
    `MultiPolygon`. `census_tract.geom` is typed MultiPolygon, so the single
    case is wrapped rather than stored as a different type on some rows.
    """
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return ()
    if kind == "Polygon":
        parts: list[object] = [coordinates]
    elif kind == "MultiPolygon":
        parts = list(coordinates)
    else:
        return ()

    polygons: list[Polygon] = []
    for part in parts:
        if not isinstance(part, list):
            return ()
        ring_list: list[Ring] = []
        for ring in part:
            if not isinstance(ring, list):
                return ()
            positions: list[tuple[float, float]] = []
            for position in ring:
                if not isinstance(position, list | tuple) or len(position) < 2:
                    return ()
                x, y = position[0], position[1]
                if not isinstance(x, int | float) or not isinstance(y, int | float):
                    return ()
                positions.append((float(x), float(y)))
            ring_list.append(tuple(positions))
        polygons.append(tuple(ring_list))
    return tuple(polygons)


def geometry_fault(polygons: Sequence[Polygon]) -> str | None:
    """What makes this geometry unusable, or None. A short reason, for the histogram."""
    if not polygons:
        return "no geometry"
    for polygon in polygons:
        if not polygon:
            return "polygon with no rings"
        for ring in polygon:
            # Four positions is the minimum a closed triangle needs.
            if len(ring) < 4:
                return "ring with fewer than four positions"
            if ring[0] != ring[-1]:
                # GeoJSON requires closure and PostGIS will refuse the polygon.
                # Quietly closing it would hide an upstream change of shape.
                return "unclosed ring"
            for x, y in ring:
                if not (math.isfinite(x) and math.isfinite(y)):
                    return "non-finite coordinate"
                if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
                    return "coordinate outside the world"
    return None


def to_wkt(polygons: Sequence[Polygon]) -> str:
    """Nested positions as a MULTIPOLYGON literal, at `WKT_PRECISION` decimals."""
    body = ", ".join(
        "("
        + ", ".join(
            "(" + ", ".join(f"{x:.{WKT_PRECISION}f} {y:.{WKT_PRECISION}f}" for x, y in ring) + ")"
            for ring in polygon
        )
        + ")"
        for polygon in polygons
    )
    return f"MULTIPOLYGON({body})"


def bounds(polygons: Sequence[Polygon]) -> tuple[float, float, float, float]:
    """West, south, east, north."""
    xs = [x for polygon in polygons for ring in polygon for x, _ in ring]
    ys = [y for polygon in polygons for ring in polygon for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


# Latitude bands for the edge index below. 128 buckets turns Louisiana's
# 21,548-vertex outline into about 160 candidate edges per query.
BOUNDARY_BANDS = 128

# How far a tract's bounding box may reach past the state's before it is worth
# recording. About 1.1 km. Both geometries come from the same TIGER vintage, so
# this should never fire; it is the guard that would catch a geometry vintage
# and a boundary vintage drifting apart.
BOUNDARY_TOLERANCE_DEG = 0.01


class StateBoundary:
    """Point-in-polygon against one state, without a geometry library.

    Ray casting over 21,548 edges for each of 1,388 tracts is thirty million
    operations, so edges are bucketed by latitude and a query touches only the
    band its point falls in. That is the difference between two milliseconds and
    half a minute, and it keeps the dependency list at httpx, pydantic and h3.
    """

    def __init__(self, polygons: Sequence[Polygon]) -> None:
        if not polygons:
            raise ValueError("a state boundary needs at least one polygon")
        self.west, self.south, self.east, self.north = bounds(polygons)
        self._span = (self.north - self.south) or 1e-9
        self._bands: list[list[tuple[float, float, float, float]]] = [
            [] for _ in range(BOUNDARY_BANDS)
        ]
        for polygon in polygons:
            for ring in polygon:
                for index in range(len(ring)):
                    x1, y1 = ring[index]
                    x2, y2 = ring[(index + 1) % len(ring)]
                    if y1 == y2:
                        # A horizontal edge is never crossed by a horizontal ray.
                        continue
                    first = self._band(min(y1, y2))
                    last = self._band(max(y1, y2))
                    for band in range(first, last + 1):
                        self._bands[band].append((x1, y1, x2, y2))

    def _band(self, latitude: float) -> int:
        raw = int((latitude - self.south) / self._span * (BOUNDARY_BANDS - 1))
        return min(max(raw, 0), BOUNDARY_BANDS - 1)

    def contains(self, longitude: float, latitude: float) -> bool:
        if not (self.south <= latitude <= self.north and self.west <= longitude <= self.east):
            return False
        crossings = 0
        for x1, y1, x2, y2 in self._bands[self._band(latitude)]:
            if (y1 > latitude) != (y2 > latitude):
                crossing_x = x1 + (latitude - y1) * (x2 - x1) / (y2 - y1)
                if crossing_x > longitude:
                    crossings += 1
        return crossings % 2 == 1

    def encloses_bounds(self, box: tuple[float, float, float, float]) -> bool:
        west, south, east, north = box
        tolerance = BOUNDARY_TOLERANCE_DEG
        return (
            west >= self.west - tolerance
            and south >= self.south - tolerance
            and east <= self.east + tolerance
            and north <= self.north + tolerance
        )


# ---- the raw record ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class TractProfile:
    """One tract: its geometry, its ACS values, and the verdict on its polygon.

    `fetch` produces one of these per GEOID seen in either service, so a tract
    present in one and absent from the other becomes a counted rejection rather
    than a silently short table. The geometry verdict is settled in `fetch`
    because the runner asks for known gaps before the first record is
    normalized, so a count discovered later could never reach the manifest.
    """

    geoid: str
    state_fips: str
    county_fips: str
    name: str | None
    polygons: tuple[Polygon, ...]
    internal_point: tuple[float, float] | None
    aland_m2: int | None
    awater_m2: int | None
    values: Mapping[str, tuple[Measurement, Measurement]]
    geometry_fault: str | None = None
    inside_state: bool = True
    within_state_bounds: bool = True

    @property
    def has_acs(self) -> bool:
        return bool(self.values)


# ---- parsing -----------------------------------------------------------


def _key_problem(payload: bytes) -> str | None:
    """The API's two credential refusals, which arrive as HTML behind a redirect."""
    head = payload[:2048].decode("utf-8", errors="replace").lower()
    if "missing_key" in head or "missing key" in head:
        return "no API key was accepted; the request reached the missing-key page"
    if "invalid_key" in head or "invalid key" in head:
        return "the API key was rejected as invalid"
    return None


def parse_rows(payload: bytes, url: str) -> list[dict[str, str]]:
    """The API's array-of-arrays as dicts, header row consumed."""
    problem = _key_problem(payload)
    if problem is not None:
        raise PermanentSourceError(f"{url}: {problem}")
    try:
        document = json.loads(payload)
    except ValueError as exc:
        raise PermanentSourceError(f"{url}: response was not JSON ({exc})") from None
    if not isinstance(document, list) or not document:
        raise PermanentSourceError(f"{url}: response was not a non-empty array")
    header = document[0]
    if not isinstance(header, list) or not all(isinstance(name, str) for name in header):
        raise PermanentSourceError(f"{url}: first row was not a header")
    rows: list[dict[str, str]] = []
    for row in document[1:]:
        if not isinstance(row, list) or len(row) != len(header):
            raise PermanentSourceError(f"{url}: a row does not match the header width")
        rows.append(
            {
                name: "" if cell is None else str(cell)
                for name, cell in zip(header, row, strict=True)
            }
        )
    return rows


def read_estimate(raw: str) -> Measurement:
    """An estimate cell. Jam values and blanks are absences, zero is an observation."""
    text = raw.strip()
    if not text:
        return Measurement.absent()
    try:
        value = float(text)
    except ValueError:
        return Measurement.absent()
    if value <= JAM_CEILING:
        return Measurement.absent()
    return Measurement.of(value)


def read_margin(raw: str) -> Measurement:
    """A margin cell. `-555555555` is a controlled estimate, so its margin is zero."""
    text = raw.strip()
    if not text:
        return Measurement.absent()
    try:
        value = float(text)
    except ValueError:
        return Measurement.absent()
    if value == MOE_CONTROLLED:
        return Measurement.of(0.0)
    if value <= JAM_CEILING:
        return Measurement.absent()
    # A negative margin that is not a jam value is not a margin.
    return Measurement.of(value) if value >= 0 else Measurement.absent()


def chunks(variables: Sequence[AcsVariable], size: int) -> list[tuple[AcsVariable, ...]]:
    return [tuple(variables[i : i + size]) for i in range(0, len(variables), size)]


def _geojson_features(payload: bytes, url: str) -> list[dict[str, object]]:
    try:
        document = json.loads(payload)
    except ValueError as exc:
        raise PermanentSourceError(f"{url}: response was not JSON ({exc})") from None
    if not isinstance(document, dict):
        raise PermanentSourceError(f"{url}: response was not a GeoJSON object")
    error = document.get("error")
    if isinstance(error, dict):
        raise PermanentSourceError(f"{url}: {error.get('message', 'unknown ArcGIS error')}")
    features = document.get("features")
    if not isinstance(features, list):
        raise PermanentSourceError(f"{url}: no features array")
    return [f for f in features if isinstance(f, dict)]


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _as_point(properties: Mapping[str, object]) -> tuple[float, float] | None:
    """TIGER's internal point, which is guaranteed to lie inside the polygon.

    Signed and zero-padded as text, `+29.9636785` and `-090.0152401`, so it is
    parsed rather than read as a float by luck.
    """
    latitude, longitude = properties.get("INTPTLAT"), properties.get("INTPTLON")
    if not isinstance(latitude, str) or not isinstance(longitude, str):
        return None
    try:
        return float(longitude), float(latitude)
    except ValueError:
        return None


# ---- gaps that are true of the source every time -----------------------

HOUSING_BURDEN_GAP = KnownGap(
    scope="methodological",
    detail=(
        "P5 is defined in section 8.4 as the percent of low-income households paying "
        "more than 50 percent of income on housing, and ACS publishes no such cross "
        "tabulation at tract level. B25106 crosses tenure and household income against "
        "housing cost but stops at a '30 percent or more' bracket, and the tables that "
        "do publish a 50 percent bracket, B25070 and B25091, are not broken out by "
        "income. The indicator recipe therefore keeps the low-income half of the "
        "definition and uses the 30 percent cut, which counts more households than the "
        "definition intends and understates how severe their burden is. Both sets of "
        "variables are stored, so the severe-burden numbers are available without a "
        "second pull, and HUD's CHAS tables would supply the true cross tabulation as a "
        "separate source. Changing which one P5 uses is a section 17 revision."
    ),
    affects=("P5",),
)

ACS_UNCERTAINTY_GAP = KnownGap(
    scope="attribute",
    detail=(
        "ACS five-year estimates are survey estimates, and at tract level for small "
        "subgroups the published margin of error is frequently larger than the estimate "
        "itself. Every margin is stored beside its estimate and the coefficient of "
        "variation travels into c_spatial, where section 12 lowers a hex's confidence. "
        "No estimate is dropped for uncertainty at any threshold, because dropping "
        "high-uncertainty estimates preferentially removes small and rural populations, "
        "which are the populations this project exists to see."
    ),
    affects=("S1", "S2", "P1", "P2", "P3", "P4", "P5"),
)

POOLING_GAP = KnownGap(
    scope="temporal",
    detail=(
        f"The {ACS_WINDOW} release pools five years of interviews, so it describes the "
        f"middle of that window rather than its end and cannot show a change that "
        f"happened inside it. A neighbourhood that emptied or gentrified during the "
        f"window reads as its five-year average. The recency term of section 12 is "
        f"computed from the release, not from the download date."
    ),
    affects=("S1", "S2", "P1", "P2", "P3", "P4", "P5"),
)

RACE_SEPARATION_GAP = KnownGap(
    scope="methodological",
    detail=(
        "Race and ethnicity are pulled by this adapter and written to "
        "tract_race_ethnicity, never to tract_demographics, so no indicator query can "
        "reach them. Section 14 accepts a known cost for that: the score will "
        "understate burden in a Black community that is not also poor, because "
        "mechanisms operating through race independently of income are outside the "
        "arithmetic by construction. That is what makes the section 13.6 disparity "
        "finding an independent result."
    ),
)


@register
class CensusAcsAdapter(SourceAdapter[TractProfile]):
    """ACS 5-year tract demographics, with the tract polygons they attach to."""

    spec = SourceSpec(
        name="census_acs",
        title="US Census American Community Survey, 5-year estimates",
        homepage="https://www.census.gov/programs-surveys/acs",
        cadence="annual release, five pooled years per release",
        native_geography="census tract",
        provides=("S1", "S2", "P1", "P2", "P3", "P4", "P5"),
    )

    # The Census API publishes no rate limit and TIGERweb sits behind a firewall
    # that has already refused one query, so two requests a second. The timeout
    # is the second departure from the default and the one with a measured
    # reason: a geometry page is about five megabytes and thirty seconds is not
    # a generous allowance for that on a slow link.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit(requests_per_second=2.0, burst=2),
        request_timeout_s=90.0,
    )

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[TractProfile]:
        key = (ctx.credentials.get(CREDENTIAL) or "").strip()
        if not key:
            raise PermanentSourceError(
                f"{ACS_URL}: no {CREDENTIAL} in the run credentials. Every ACS query "
                f"needs one; sign up at https://api.census.gov/data/key_signup.html and "
                f"set CENSUS_API_KEY."
            )
        fips = STATE_FIPS.get(ctx.pilot_state)
        if fips is None:
            raise PermanentSourceError(f"no FIPS code known for pilot state {ctx.pilot_state!r}")

        artifacts: list[Artifact] = []
        values, acs_artifacts, unkeyed = await self._fetch_estimates(ctx, fips, key)
        artifacts.extend(acs_artifacts)

        boundary, boundary_artifact = await self._fetch_boundary(ctx, fips)
        artifacts.append(boundary_artifact)

        geometries, geometry_artifacts, pages = await self._fetch_geometry(ctx, fips)
        artifacts.extend(geometry_artifacts)

        profiles = tuple(self._assemble(values, geometries, boundary))
        counts = self._tally(profiles)

        notes = [
            f"{len(values)} tracts from the ACS API in "
            f"{len(chunks(PULLED, VARIABLES_PER_REQUEST))} requests "
            f"covering {len(PULLED)} variables",
            f"{len(geometries)} tract geometries from TIGER {TIGER_YEAR} in {pages} pages",
            f"{len(SCORED)} variables to tract_demographics, {len(RACE)} to tract_race_ethnicity",
        ]
        if unkeyed:
            # Not a rejection, because there is no tract to reject: the release
            # returned a row whose geography columns do not name one. Counted
            # rather than dropped quietly, which is the whole point of counting.
            notes.append(f"{unkeyed} ACS rows carried no eleven-digit tract GEOID and were skipped")
        if counts["high_cv"]:
            notes.append(
                f"{counts['high_cv']} of {counts['comparable']} estimates have a "
                f"coefficient of variation above {CV_THRESHOLD:.2f}"
            )

        return FetchResult(
            records=profiles,
            # The release, not the download date. Section 12 computes recency
            # from this, and a six-year-old release downloaded tonight is still
            # a six-year-old release.
            vintage=VINTAGE,
            artifacts=artifacts,
            known_gaps=self._pull_gaps(counts, len(profiles)),
            notes=notes,
        )

    async def _fetch_estimates(
        self, ctx: RunContext, fips: str, key: str
    ) -> tuple[dict[str, dict[str, tuple[Measurement, Measurement]]], list[Artifact], int]:
        """Every declared variable for every tract in the state, chunked.

        The variable list goes in the URL and the key goes in `secret_params`.
        Both halves of that matter: the URL is the snapshot key, so chunks that
        shared one would overwrite each other and a stale night would replay a
        single chunk for all of them; and the URL is published in
        docs/provenance.md, so a key in it would be a key in the repository.
        """
        collected: dict[str, dict[str, tuple[Measurement, Measurement]]] = {}
        artifacts: list[Artifact] = []
        # The worst any one request saw, not the sum over requests. Every chunk
        # asks for the same geography, so summing would report one bad row four
        # times over.
        unkeyed = 0

        for batch in chunks(PULLED, VARIABLES_PER_REQUEST):
            fields = [field for v in batch for field in (v.estimate_field, v.margin_field)]
            url = f"{ACS_URL}?get={','.join(fields)}&for=tract:*&in=state:{fips}"
            download = await ctx.http.get(url, secret_params={"key": key})
            artifacts.append(download.artifact)

            # Named by the chunk, not by the base endpoint: four requests go to
            # one URL prefix and a message that did not say which would send a
            # reader looking through all of them.
            rows = parse_rows(download.content, f"{ACS_URL} [{batch[0].code}..{batch[-1].code}]")
            if not rows:
                raise PermanentSourceError(
                    f"{ACS_URL}: state {fips} returned no tract rows for {batch[0].code} onwards"
                )
            skipped = 0
            for row in rows:
                geoid = f"{row.get('state', '')}{row.get('county', '')}{row.get('tract', '')}"
                if len(geoid) != 11:
                    # A row whose geography columns name no tract. There is no
                    # record to reject yet, so it is counted into a note instead
                    # of vanishing.
                    skipped += 1
                    continue
                bucket = collected.setdefault(geoid, {})
                for variable in batch:
                    bucket[variable.code] = (
                        read_estimate(row.get(variable.estimate_field, "")),
                        read_margin(row.get(variable.margin_field, "")),
                    )
            unkeyed = max(unkeyed, skipped)
        return collected, artifacts, unkeyed

    async def _fetch_boundary(self, ctx: RunContext, fips: str) -> tuple[StateBoundary, Artifact]:
        url = (
            f"{TIGERWEB}/{STATE_LAYER}/query?where=STATE%3D%27{fips}%27"
            f"&outFields=GEOID,NAME&returnGeometry=true&outSR=4326&f=geojson"
        )
        download = await ctx.http.get(url)
        features = _geojson_features(download.content, url)
        if not features:
            raise PermanentSourceError(f"{url}: state {fips} has no boundary geometry")
        geometry = features[0].get("geometry")
        polygons = rings_of(geometry) if isinstance(geometry, dict) else ()
        fault = geometry_fault(polygons)
        if fault is not None:
            # Without a boundary there is nothing to validate tracts against,
            # and loading them unvalidated would quietly drop the acceptance
            # criterion this check exists to satisfy.
            raise PermanentSourceError(f"{url}: state boundary is unusable ({fault})")
        return StateBoundary(polygons), download.artifact

    async def _fetch_geometry(
        self, ctx: RunContext, fips: str
    ) -> tuple[dict[str, dict[str, object]], list[Artifact], int]:
        """Tract polygons, paged. See the module docstring on why paged at all."""
        geometries: dict[str, dict[str, object]] = {}
        artifacts: list[Artifact] = []
        pages = 0

        for page in range(MAX_GEOMETRY_PAGES):
            offset = page * GEOMETRY_PAGE_SIZE
            url = (
                f"{TIGERWEB}/{TRACT_LAYER}/query?where=STATE%3D%27{fips}%27"
                f"&outFields=GEOID,STATE,COUNTY,TRACT,NAME,AREALAND,AREAWATER,"
                f"INTPTLAT,INTPTLON&returnGeometry=true&outSR=4326"
                f"&orderByFields=GEOID&resultOffset={offset}"
                f"&resultRecordCount={GEOMETRY_PAGE_SIZE}&f=geojson"
            )
            download = await ctx.http.get(url)
            artifacts.append(download.artifact)
            features = _geojson_features(download.content, url)
            pages += 1

            for feature in features:
                properties = feature.get("properties")
                if not isinstance(properties, dict):
                    continue
                geoid = str(properties.get("GEOID") or "")
                if geoid:
                    geometries[geoid] = feature
            if len(features) < GEOMETRY_PAGE_SIZE:
                break
        else:
            raise PermanentSourceError(
                f"{TIGERWEB}/{TRACT_LAYER}: still returning full pages after "
                f"{MAX_GEOMETRY_PAGES}; refusing to page further"
            )

        if not geometries:
            raise PermanentSourceError(f"{TIGERWEB}/{TRACT_LAYER}: state {fips} returned no tracts")
        return geometries, artifacts, pages

    def _assemble(
        self,
        values: Mapping[str, Mapping[str, tuple[Measurement, Measurement]]],
        geometries: Mapping[str, Mapping[str, object]],
        boundary: StateBoundary,
    ) -> Iterator[TractProfile]:
        """One profile per GEOID in either service, so a mismatch stays visible."""
        for geoid in sorted(set(values) | set(geometries)):
            feature = geometries.get(geoid)
            properties: Mapping[str, object] = {}
            polygons: tuple[Polygon, ...] = ()
            if feature is not None:
                raw = feature.get("properties")
                properties = raw if isinstance(raw, dict) else {}
                geometry = feature.get("geometry")
                polygons = rings_of(geometry) if isinstance(geometry, dict) else ()

            fault = geometry_fault(polygons) if feature is not None else "no geometry"
            point = _as_point(properties)
            inside = True
            within = True
            if fault is None:
                within = boundary.encloses_bounds(bounds(polygons))
                # TIGER's internal point is guaranteed to lie inside its own
                # tract, so testing it against the state is a real containment
                # test for the tract and not merely for a centroid.
                inside = point is not None and boundary.contains(point[0], point[1])

            yield TractProfile(
                geoid=geoid,
                state_fips=str(properties.get("STATE") or geoid[:2]),
                county_fips=str(properties.get("COUNTY") or geoid[2:5]),
                name=str(properties.get("NAME")) if properties.get("NAME") else None,
                polygons=polygons,
                internal_point=point,
                aland_m2=_as_int(properties.get("AREALAND")),
                awater_m2=_as_int(properties.get("AREAWATER")),
                values=dict(values.get(geoid, {})),
                geometry_fault=fault,
                inside_state=inside,
                within_state_bounds=within,
            )

    def _tally(self, profiles: Sequence[TractProfile]) -> dict[str, int]:
        """What this pull needs to publish about itself, counted before normalize."""
        counts = dict.fromkeys(
            (
                "no_acs",
                "no_geometry",
                "bad_geometry",
                "outside_state",
                "beyond_state_bounds",
                "comparable",
                "high_cv",
                "absent",
                "zero_estimate",
            ),
            0,
        )
        for profile in profiles:
            if not profile.has_acs:
                counts["no_acs"] += 1
            if profile.geometry_fault == "no geometry":
                counts["no_geometry"] += 1
            elif profile.geometry_fault is not None:
                counts["bad_geometry"] += 1
            elif not profile.inside_state:
                counts["outside_state"] += 1
            elif not profile.within_state_bounds:
                counts["beyond_state_bounds"] += 1

            for estimate, margin in profile.values.values():
                if not estimate.observed:
                    counts["absent"] += 1
                    continue
                if estimate.value == 0:
                    counts["zero_estimate"] += 1
                    continue
                if not margin.observed:
                    continue
                counts["comparable"] += 1
                value, error = estimate.value, margin.value
                if value and error is not None:
                    if (error / MOE_TO_STANDARD_ERROR) / value > CV_THRESHOLD:
                        counts["high_cv"] += 1
        return counts

    def _pull_gaps(self, counts: Mapping[str, int], total: int) -> tuple[KnownGap, ...]:
        gaps: list[KnownGap] = []
        social = ("S1", "S2", "P1", "P2", "P3", "P4", "P5")

        if counts["high_cv"]:
            share = counts["high_cv"] / max(counts["comparable"], 1)
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{counts['high_cv']} of {counts['comparable']} estimates in the "
                        f"{ACS_WINDOW} release, {share:.1%}, have a coefficient of "
                        f"variation above {CV_THRESHOLD:.2f}. All of them are loaded and "
                        f"all of them lower c_spatial for the hexes they reach; none is "
                        f"dropped. Section 12."
                    ),
                    affects=social,
                )
            )
        if counts["absent"]:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{counts['absent']} tract-variable cells carry no estimate: a "
                        f"blank, or one of the Census jam values for a quantity the "
                        f"survey could not compute. They are stored as absent, never as "
                        f"zero, which section 11 requires and which keeps them out of "
                        f"the rates CS-106 derives rather than pulling those rates down."
                    ),
                    affects=social,
                )
            )
        if counts["no_acs"] or counts["no_geometry"]:
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{counts['no_acs']} of {total} tracts appear in TIGER "
                        f"{TIGER_YEAR} with no {ACS_WINDOW} estimates, and "
                        f"{counts['no_geometry']} appear in the release with no geometry. "
                        f"Both are rejected and counted rather than half-loaded, because "
                        f"a tract without a polygon reaches no hex and a polygon without "
                        f"estimates contributes nothing but area."
                    ),
                    affects=social,
                )
            )
        if counts["bad_geometry"] or counts["outside_state"]:
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{counts['bad_geometry']} tract geometries were unusable and "
                        f"{counts['outside_state']} had an internal point outside the "
                        f"TIGER {TIGER_YEAR} state boundary. Both are rejected: an "
                        f"invalid polygon cannot be intersected with the hex grid, and a "
                        f"tract outside the state would put population where the "
                        f"percentile denominators of section 9 do not look."
                    ),
                    affects=social,
                )
            )
        if counts["beyond_state_bounds"]:
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{counts['beyond_state_bounds']} tracts are loaded although "
                        f"their bounding box reaches more than "
                        f"{BOUNDARY_TOLERANCE_DEG} degrees past the state's. Tract and "
                        f"boundary geometry come from the same TIGER vintage and should "
                        f"nest exactly, so this count is the signal that the two have "
                        f"drifted apart."
                    ),
                    affects=social,
                )
            )
        return tuple(gaps)

    # ---- validate ------------------------------------------------------

    def validate(self, record: TractProfile, ctx: RunContext) -> None:
        if len(record.geoid) != 11 or not record.geoid.isdigit():
            raise RecordRejected("malformed tract GEOID", field="GEOID", record_id=record.geoid)

        fips = STATE_FIPS.get(ctx.pilot_state)
        if fips is not None and record.state_fips != fips:
            raise RecordRejected(
                f"state {record.state_fips} is not {ctx.pilot_state}",
                field="STATE",
                record_id=record.geoid,
            )
        if not record.has_acs:
            raise RecordRejected(f"no {ACS_WINDOW} estimates for the tract", record_id=record.geoid)
        if record.geometry_fault is not None:
            raise RecordRejected(record.geometry_fault, field="geometry", record_id=record.geoid)
        if record.internal_point is None:
            raise RecordRejected(
                "no TIGER internal point", field="INTPTLAT", record_id=record.geoid
            )
        if not record.inside_state:
            # The acceptance criterion this satisfies: geometries validated
            # against the state boundary, not against a bounding box.
            raise RecordRejected(
                "internal point outside the state boundary",
                field="geometry",
                record_id=record.geoid,
            )

        # A tract with no population is ordinary: an airport, a park, open
        # water. It is not a reason to reject one, and rejecting it would
        # remove a real polygon from the interpolation. Only a tract whose
        # population was never reported at all is unusable, and that is what
        # the missing-estimates check above already covers.

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: TractProfile, ctx: RunContext) -> Iterator[NormalizedRecord]:
        yield CensusTract(
            geoid=record.geoid,
            state_fips=record.state_fips,
            county_fips=record.county_fips,
            name=record.name,
            geom_wkt=to_wkt(record.polygons),
            aland_m2=record.aland_m2,
            awater_m2=record.awater_m2,
            tiger_year=TIGER_YEAR,
        )
        yield from self._estimates(record, SCORED, TractEstimate)
        yield from self._estimates(record, RACE, TractRaceEthnicity)

    def _estimates(
        self,
        record: TractProfile,
        variables: Sequence[AcsVariable],
        row: type[TractVariable],
    ) -> Iterator[TractVariable]:
        """One row per declared variable, in the table the declaration chose.

        A variable the release did not return is emitted as an absent estimate
        rather than skipped, so a reader can tell "the survey had nothing to say
        about this tract" from "nobody asked".
        """
        for variable in variables:
            estimate, margin = record.values.get(
                variable.code, (Measurement.absent(), Measurement.absent())
            )
            yield row(
                tract_geoid=record.geoid,
                acs_vintage=ACS_WINDOW,
                variable=variable.estimate_field,
                estimate=estimate,
                margin_of_error=margin,
                is_extensive=variable.extensive,
            )

    # ---- gaps ----------------------------------------------------------

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            ACS_UNCERTAINTY_GAP,
            POOLING_GAP,
            HOUSING_BURDEN_GAP,
            RACE_SEPARATION_GAP,
            KnownGap(
                scope="methodological",
                detail=(
                    "Tract boundaries are redrawn every decennial census and ACS "
                    "releases mid-decade use the 2020 vintage, so a tract id is not a "
                    "stable place over time. Nothing in the pilot compares two releases, "
                    "and a later time series would have to reconcile the boundaries "
                    "rather than join on the id."
                ),
                affects=("S1", "S2", "P1", "P2", "P3", "P4", "P5"),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "The section 8.3 sensitive-population subgroup is two indicators, "
                    "both age structure, because no free tract-level national source "
                    "publishes the health outcomes that would belong there. Section 16 "
                    "records it; ACS cannot fill it."
                ),
                affects=("S1", "S2"),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "Every ACS query now requires an API key, including the older "
                    "datasets that once allowed a small keyless volume. The snapshot "
                    "that a stale night falls back to is keyed by request URL, and the "
                    "key is deliberately not part of that URL, so snapshots survive a "
                    "key rotation. A run with no key at all fails immediately rather "
                    "than falling back, because a missing credential is a "
                    "misconfiguration and not an unavailable upstream."
                ),
                affects=("S1", "S2", "P1", "P2", "P3", "P4", "P5"),
            ),
        )
