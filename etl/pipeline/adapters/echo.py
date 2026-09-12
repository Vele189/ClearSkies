"""EPA ECHO / ICIS: facilities, permits, compliance history and enforcement.

Feeds F1 through F4 (methodology section 8.2). This is the only source that
carries regulatory *behaviour* rather than emissions, and section 8.2 is worth
reading before trusting it: a facility accumulates violations when somebody
inspects it, so F2 and F3 partly measure regulatory attention rather than
pollution. That is why the group carries weight 0.5, and it is a known bias
rather than a solved problem.

Three things about ECHO that shaped this adapter, all established by querying
the live service rather than assumed:

**One physical facility can hold several air permits.** In a 5,000-row
Louisiana sample, 220 rows repeated a REGISTRY_ID that a previous row had
already used. The FRS registry id identifies a site; the air feed returns one
row per permitted source at that site. `fetch` therefore groups rows into one
raw record per site, because `facility.facility_id` is a primary key and the
runner fails a pull whose natural keys repeat.

**The twelve-quarter compliance history is a twelve-character string, oldest
quarter first.** EPA does not document the ordering, so it was settled against
a facility whose history is partial: CITGO Lake Charles reports
`SSSSSSSSSS__`, and its Detailed Facility Report labels Qtr1 through Qtr10
"High Priority Violation" and Qtr11, Qtr12 "No Violation Identified", with
Qtr1Start the oldest quarter. Position 1 is the oldest. See `_QUARTER_STATUS`.

**Query ids expire.** `get_facilities` returns a QueryID and a row count, and
the rows come from `get_qid`. A qid that worked minutes earlier returns nothing
later, so `fetch` creates the query and pages it immediately.

F4 needs a second ECHO service, and three things about it shaped the rest of
this adapter:

**The air feed carries nothing about hazardous waste.** `facility.is_rcra_lqg`
and `facility.is_rcra_tsdf` come from `rcra_rest_services`, which publishes
RCRAInfo the way `air_rest_services` publishes ICIS-Air. Louisiana returns 23,782
handler rows there against 13,842 air permits, and most of them have no business
in F4: 13,558 are very small quantity generators, 2,827 small quantity
generators and 724 transporters. 754 FRS sites are large-quantity generators or
TSD facilities, and 272 of those join the air feed on the registry id. The other
482 are hazardous-waste sites that hold no air permit, so they are loaded as
their own facility rows on the terms `pipeline/adapters/tri.py` uses for an
unmatched TRI site; without that, two thirds of the state's generators would
never reach F4.

**The service ignores query parameters it does not recognise.** `p_st=LA&p_gs=L`
returns the same 23,782 rows as `p_st=LA` alone, and so does every other spelling
of a generator-status filter tried against it. A filter passed upstream would
look like it worked and quietly do nothing, so the LQG and TSDF screen is applied
here, on rows this adapter has actually read.

**A TSD facility is identified by its permitted units, not by RCRA_UNIVERSE.**
The universe string labels 25 sites an operating TSDF and 24 a legacy one, while
the `TSDF` column lists permitted unit types for 103 sites and is a strict
superset of the first: every universe TSDF has one. The 54 sites it adds are not
clerical. BASF at Zachary reports its universe as `LQG` alone and its units as
`Land Disposal (L); Incinerator (I); Storage (S); Treatment (T)`; Benton
Creosoting Works reports `VSQG` and a land disposal unit. Reading the universe
string alone would leave a hazardous-waste incinerator and a creosote land
disposal site out of F4, so the unit list decides the flag and the universe token
is a fallback for a row that has one without the other.

Legacy TSDFs count. Methodology section 8.2 qualifies F1 with "active" and F4
with nothing, and the waste in a closed land disposal unit does not leave when
the permit lapses: Marine Shale Processors at Amelia stopped burning in the 1990s
and its cells are still there. The count is published in the manifest so a reader
who disagrees can see how much of F4 rests on it.

A failed RCRA pull fails the whole source rather than loading the air feed alone.
False in both flags for every facility is the "measured, and there are none
nearby" reading of a question nobody asked, which is the failure this ticket
exists to remove.
"""

import csv
import io
import json
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import ClassVar

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.geo import Geocode, classify, containing_cell
from pipeline.metadata import Artifact, KnownGap, SourceSpec
from pipeline.policy import RateLimit, SourcePolicy
from pipeline.records import NormalizedRecord

ECHO = "https://echodata.epa.gov/echo"
GET_FACILITIES = f"{ECHO}/air_rest_services.get_facilities"
GET_QID = f"{ECHO}/air_rest_services.get_qid"
DFR_URL = "https://echo.epa.gov/detailed-facility-report?fid={registry_id}"

# ECHO caps a page well below the row count for a state, so fetch pages.
PAGE_SIZE = 5000
MAX_PAGES = 20

# Requested by ColumnID, because the default response omits the compliance
# history and enforcement columns that F2 and F3 exist to use. Ids come from
# air_rest_services.metadata; the names are only here to make the list readable.
QCOLUMNS: tuple[tuple[int, str], ...] = (
    (8, "REGISTRY_ID"),
    (2, "SOURCE_ID"),
    (1, "AIR_NAME"),
    (3, "AIR_STREET"),
    (4, "AIR_CITY"),
    (5, "AIR_STATE"),
    (7, "AIR_ZIP"),
    (23, "FAC_LAT"),
    (24, "FAC_LONG"),
    (14, "FAC_FIPS_CODE"),
    (22, "AIR_NAICS"),
    (103, "AIR_MAJOR_FLAG"),
    (27, "AIR_STATUS"),
    (29, "AIR_CLASSIFICATION"),
    (104, "AIR_3YR_COMPL_QTRS_HISTORY"),
    (44, "AIR_COMPL_STATUS"),
    (77, "AIR_FEA_CNT"),
    (84, "AIR_PENALTIES"),
    (81, "AIR_LAST_FEA_DATE"),
    (117, "CALCULATED_ACCURACY_METERS"),
)

# RCRAInfo, for the two hazardous-waste flags F4 reads. Same shape as the air
# service: a query id, then pages of rows.
RCRA_GET_FACILITIES = f"{ECHO}/rcra_rest_services.get_facilities"
RCRA_GET_QID = f"{ECHO}/rcra_rest_services.get_qid"

# Requested by ColumnID from rcra_rest_services.metadata, as above. RCRA_UNIVERSE
# and TSDF are what F4 exists to read; the rest is what a site holding no air
# permit needs in order to become a facility row of its own.
RCRA_QCOLUMNS: tuple[tuple[int, str], ...] = (
    (8, "REGISTRY_ID"),
    (2, "SOURCE_ID"),
    (1, "RCR_NAME"),
    (3, "RCR_STREET"),
    (4, "RCR_CITY"),
    (5, "RCR_STATE"),
    (7, "RCR_ZIP"),
    (14, "FAC_FIPS_CODE"),
    (22, "RCRA_NAICS"),
    (23, "FAC_LAT"),
    (24, "FAC_LONG"),
    (25, "RCRA_UNIVERSE"),
    (26, "TSDF"),
    (92, "CALCULATED_ACCURACY_METERS"),
)

# The generator token F4 counts. Compared as a whole token rather than searched
# for, because 'SQG' is a substring of 'VSQG' and a smaller generator is not a
# large one.
LQG_TOKEN = "LQG"

# Matched inside a token, because the universe string spells it two ways:
# 'Operating TSDF' and 'Legacy TSDF'. Both count; see the module docstring.
TSDF_TOKEN = "TSDF"

# Census ZCTA centroids, for the two-kilometre check in methodology section 6.
# Pinned to a vintage: a moving gazetteer would silently change which
# facilities are flagged between runs.
GAZETTEER_YEAR = 2024
GAZETTEER_URL = (
    f"https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    f"{GAZETTEER_YEAR}_Gazetteer/{GAZETTEER_YEAR}_Gaz_zcta_national.zip"
)

QUARTERS = 12

# Established empirically; see the module docstring. ECHO returns only '_' and
# 'S' anywhere in Louisiana's 13,842 air facilities, but the wider alphabet is
# mapped so a character appearing later is not silently read as compliance.
_QUARTER_STATUS: Mapping[str, str] = {
    "S": "high_priority_violation",
    "V": "violation",
    "N": "in_compliance",
}


class Facility(NormalizedRecord):
    """One physical site, however many air permits it holds."""

    table: ClassVar[str] = "facility"

    facility_id: str
    registry_id: str
    # Set by the TRI adapter on the facility rows it owns; ECHO's air feed does
    # not carry a TRI id. See pipeline/adapters/tri.py.
    tri_facility_id: str | None = None
    name: str
    street: str | None
    city: str | None
    state: str | None
    zip5: str | None
    county_fips: str | None
    naics_code: str | None
    # The coordinate worth storing as geometry, which is None when upstream
    # reported no point or reported one that is not a place on Earth. The
    # reported_* pair below is what upstream actually said, kept whatever the
    # verdict so a quarantine can be audited rather than taken on trust.
    latitude: float | None
    longitude: float | None
    reported_latitude: float | None
    reported_longitude: float | None
    h3: str | None
    coordinate_status: str
    geocode_quality: str
    geocode_accuracy_m: float | None
    is_major_source: bool
    has_title_v: bool
    # The two columns F4 reads, from ECHO's RCRA feed. False means RCRAInfo was
    # read and holds no large-quantity generator or TSD record for this site, which
    # is a different statement from the "never asked" these columns carried while
    # the adapter left them at their schema default.
    is_rcra_lqg: bool = False
    is_rcra_tsdf: bool = False
    echo_url: str
    air_source_ids: tuple[str, ...]
    operating_status: str | None

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id,)


class ComplianceQuarter(NormalizedRecord):
    """One facility's Clean Air Act compliance status for one quarter."""

    table: ClassVar[str] = "facility_compliance_quarter"

    facility_id: str
    quarter: date
    program: str
    status: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id, self.quarter.isoformat(), self.program)


class EnforcementAction(NormalizedRecord):
    """A formal enforcement action, dated."""

    table: ClassVar[str] = "enforcement_action"

    action_id: str
    facility_id: str
    program: str
    action_type: str
    settled_on: date | None
    penalty_usd: float | None
    is_formal: bool

    def natural_key(self) -> tuple[str, ...]:
        return (self.action_id,)


def universe(row: Mapping[str, str]) -> tuple[str, ...]:
    """RCRA_UNIVERSE as its tokens: 'LQG, Operating TSDF' is two of them."""
    return tuple(
        token.strip() for token in (row.get("RCRAUniverse") or "").split(",") if token.strip()
    )


def is_large_quantity_generator(row: Mapping[str, str]) -> bool:
    return LQG_TOKEN in universe(row)


def is_tsd_facility(row: Mapping[str, str]) -> bool:
    """A site with permitted TSD units, or one the universe string labels a TSDF.

    The unit list leads because it is the wider and the better-populated of the
    two; see the module docstring. The universe token is still read, so a row
    that carries one without the other is not lost.
    """
    if (row.get("Tsdf") or "").strip():
        return True
    return any(TSDF_TOKEN in token for token in universe(row))


@dataclass(frozen=True, slots=True)
class RcraHandler:
    """What the RCRA feed says about one FRS site, reduced to what F4 needs.

    One site can hold several RCRA handler ids for the same reason it can hold
    several air permits, and Louisiana has 13 that do: Dow's Plaquemine complex
    reports `LAD008187080` and `LAR000086074` under registry id 110001244724. The
    flags are therefore OR-ed across the site's handlers, because a site with any
    large-quantity generator on it is a large-quantity generator site.

    The address and coordinate fields are only read for a site the air feed does
    not hold. Where both feeds describe one site, the air feed's account wins, so
    a facility's row does not change shape depending on which service was read
    last.
    """

    registry_id: str
    handler_ids: tuple[str, ...]
    is_lqg: bool
    is_tsdf: bool
    name: str | None
    street: str | None
    city: str | None
    state: str | None
    zip5: str | None
    fips: str | None
    naics: str | None
    latitude: float | None
    longitude: float | None
    accuracy_m: float | None

    @classmethod
    def of(cls, registry_id: str, rows: Sequence[Mapping[str, str]]) -> "RcraHandler":
        def first(key: str) -> str | None:
            for row in rows:
                value = (row.get(key) or "").strip()
                if value:
                    return value
            return None

        return cls(
            registry_id=registry_id,
            handler_ids=tuple(
                sorted({sid for row in rows if (sid := (row.get("SourceID") or "").strip())})
            ),
            is_lqg=any(is_large_quantity_generator(row) for row in rows),
            is_tsdf=any(is_tsd_facility(row) for row in rows),
            name=first("RCRAName"),
            street=first("RCRAStreet"),
            city=first("RCRACity"),
            state=first("RCRAState"),
            zip5=(first("RCRAZip") or "")[:5] or None,
            fips=first("FacFIPSCode"),
            naics=first("RCRANAICS"),
            latitude=_parse_float(first("FacLat")),
            longitude=_parse_float(first("FacLong")),
            accuracy_m=_parse_float(first("CalculatedAccuracyMeters")),
        )


@dataclass(frozen=True, slots=True)
class RcraJoin:
    """What the RCRA pull found, and how much of it reached an air facility.

    Acceptance criterion three: an unjoined generator is an F4 contribution that
    silently did not happen, so the counts are carried out of `fetch` and into the
    manifest rather than logged and forgotten.
    """

    screened: int
    sites: int
    matched: int
    unkeyed: int

    @property
    def unmatched(self) -> int:
        return self.sites - self.matched


@dataclass(frozen=True, slots=True)
class EchoSite:
    """One FRS site, every air permit ECHO returned for it, and its geocoding verdict.

    `fetch` produces these rather than raw rows so that one raw record means one
    facility, which is what makes the runner's duplicate-key check mean
    something.

    `geocode` is settled here rather than in `normalize` because the runner asks
    an adapter for its known gaps before the first record is normalized. A count
    discovered during normalize could never reach the manifest, and section 6
    requires the exclusion count to be published.
    """

    registry_id: str
    sources: tuple[dict[str, str], ...]
    # What RCRAInfo says about this site, where it says anything. None for a site
    # that holds air permits and no hazardous-waste record; `sources` is empty for
    # a hazardous-waste site that holds no air permit. Both are facilities.
    rcra: RcraHandler | None = None
    geocode: Geocode = field(default_factory=lambda: Geocode(status="ok", quality="unverified"))

    def first(self, key: str) -> str | None:
        """The first non-empty value any of this site's permits reports."""
        for source in self.sources:
            value = (source.get(key) or "").strip()
            if value:
                return value
        return None

    def any_equals(self, key: str, value: str) -> bool:
        return any((source.get(key) or "").strip() == value for source in self.sources)

    @property
    def facility_id(self) -> str:
        """The schema's rule, extended to RCRA: the FRS registry id, or the
        handler id prefixed `rcra:`.

        Every Louisiana large-quantity generator and TSD site carries an FRS id
        today, so the prefix is a fallback rather than a path the current extract
        exercises. It exists because a generator with no registry id is still a
        generator, and dropping one is an F4 contribution that silently did not
        happen. TRI does the same with a `tri:` prefix.
        """
        if self.registry_id:
            return self.registry_id
        if self.rcra is not None and self.rcra.handler_ids:
            return f"rcra:{self.rcra.handler_ids[0]}"
        return ""

    @property
    def has_air_permits(self) -> bool:
        return bool(self.sources)

    def attribute(self, air_key: str, rcra_field: str) -> str | None:
        """The air feed's account of an attribute, or RCRA's where there is no air permit."""
        value = self.first(air_key)
        if value:
            return value
        return getattr(self.rcra, rcra_field) if self.rcra is not None else None

    @property
    def name(self) -> str | None:
        return self.attribute("AIRName", "name")

    @property
    def state(self) -> str | None:
        return self.attribute("AIRState", "state")

    @property
    def zip5(self) -> str | None:
        reported = self.attribute("AIRZip", "zip5")
        return reported[:5] if reported else None

    @property
    def county_fips(self) -> str | None:
        """Both feeds report state plus county; the schema column holds the county."""
        fips = self.attribute("FacFIPSCode", "fips") or ""
        return fips[2:5] if len(fips) >= 5 else None

    @property
    def naics_code(self) -> str | None:
        """Both feeds report a space-separated list, primary code first."""
        return (self.attribute("AIRNAICS", "naics") or "").split(" ")[0] or None

    @property
    def reported_point(self) -> tuple[float | None, float | None]:
        latitude = _parse_float(self.first("FacLat"))
        longitude = _parse_float(self.first("FacLong"))
        if latitude is None and longitude is None and self.rcra is not None:
            return self.rcra.latitude, self.rcra.longitude
        return latitude, longitude

    @property
    def accuracy_m(self) -> float | None:
        reported = _parse_float(self.first("CalculatedAccuracyMeters"))
        if reported is None and self.rcra is not None:
            return self.rcra.accuracy_m
        return reported

    @property
    def is_rcra_lqg(self) -> bool:
        return self.rcra is not None and self.rcra.is_lqg

    @property
    def is_rcra_tsdf(self) -> bool:
        return self.rcra is not None and self.rcra.is_tsdf


def quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def twelve_quarters_ending(day: date) -> tuple[date, ...]:
    """The twelve quarter start dates the history string describes, oldest first.

    ECHO's window ends with the quarter containing the report date: a report run
    in September 2026 labels Qtr12 as 07/01/2026 and Qtr1 as 10/01/2023.
    """
    year, month = quarter_start(day).year, quarter_start(day).month
    starts: list[date] = []
    for _ in range(QUARTERS):
        starts.append(date(year, month, 1))
        month -= 3
        if month < 1:
            month += 12
            year -= 1
    return tuple(reversed(starts))


def _as_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _as_rows(value: object) -> list[dict[str, str]]:
    """The Facilities array, or nothing. A different shape is not silently accepted."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _parse_date(value: str | None) -> date | None:
    """ECHO dates are MM/DD/YYYY. An unparseable one is dropped, not guessed."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_zip_centroids(archive: bytes) -> dict[str, tuple[float, float]]:
    """ZIP code to (lat, lon), from the Census gazetteer archive."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [n for n in bundle.namelist() if n.endswith(".txt")]
        if not names:
            raise PermanentSourceError(f"{GAZETTEER_URL}: no .txt member in the archive")
        text = bundle.read(names[0]).decode("utf-8", errors="replace")

    centroids: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        geoid = clean.get("GEOID", "")
        lat, lon = _parse_float(clean.get("INTPTLAT")), _parse_float(clean.get("INTPTLONG"))
        if len(geoid) == 5 and lat is not None and lon is not None:
            centroids[geoid] = (lat, lon)
    if not centroids:
        raise PermanentSourceError(f"{GAZETTEER_URL}: parsed no ZIP centroids")
    return centroids


@register
class EpaEchoAdapter(SourceAdapter[EchoSite]):
    """Clean Air Act facilities, compliance quarters and enforcement actions."""

    spec = SourceSpec(
        name="epa_echo",
        title="EPA Enforcement and Compliance History Online (ECHO: ICIS-Air and RCRAInfo)",
        homepage="https://echo.epa.gov/tools/web-services",
        cadence="refreshed weekly upstream",
        native_geography="point (facility lat/lon, self-reported)",
        provides=("F1", "F2", "F3", "F4"),
    )

    # ECHO publishes no rate limit. Two requests a second is well under what a
    # browser session generates and is the only number here that departs from
    # the default. Everything else about failure handling is the runner's.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit(requests_per_second=2.0, burst=2),
    )

    def __init__(self) -> None:
        # Reference data, loaded once by fetch and read per record. Not
        # per-record state: validate and normalize stay pure functions of the
        # record plus this lookup.
        self._zip_centroids: dict[str, tuple[float, float]] = {}

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[EchoSite]:
        state = ctx.pilot_state
        columns = ",".join(str(cid) for cid, _ in QCOLUMNS)

        opened = await ctx.http.get(GET_FACILITIES, params={"output": "JSON", "p_st": state})
        results = self._results(opened.content, GET_FACILITIES)
        qid = _as_text(results.get("QueryID"))
        expected = _as_int(results.get("QueryRows"))
        if not qid:
            raise PermanentSourceError(f"{GET_FACILITIES}: no QueryID in the response")
        if expected == 0:
            raise PermanentSourceError(f"{GET_FACILITIES}: {state} matched no facilities")

        artifacts = [opened.artifact]
        rows: list[dict[str, str]] = []
        for page in range(1, MAX_PAGES + 1):
            download = await ctx.http.get(
                GET_QID,
                params={
                    "output": "JSON",
                    "qid": str(qid),
                    "pageno": str(page),
                    "responseset": str(PAGE_SIZE),
                    "qcolumns": columns,
                },
            )
            artifacts.append(download.artifact)
            batch = _as_rows(self._results(download.content, GET_QID).get("Facilities"))
            rows.extend(batch)
            if len(batch) < PAGE_SIZE or len(rows) >= expected:
                break

        if not rows:
            # A qid that returns nothing is usually an expired query rather than
            # an empty state, and retrying the same qid will not help.
            raise PermanentSourceError(f"{GET_QID}: qid {qid} returned no rows")

        # Before the gazetteer, so a hazardous-waste site that holds no air permit
        # is classified on the same ZIP centroids as every other facility.
        handlers, screened, unkeyed, rcra_artifacts = await self._rcra_handlers(ctx, state)
        artifacts.extend(rcra_artifacts)

        gazetteer = await ctx.http.get(GAZETTEER_URL)
        artifacts.append(gazetteer.artifact)
        self._zip_centroids = load_zip_centroids(gazetteer.content)

        air_sites = self._group_by_site(rows)
        merged, matched = self._merge_rcra(air_sites, handlers)
        join = RcraJoin(screened=screened, sites=len(handlers), matched=matched, unkeyed=unkeyed)
        sites = tuple(self._classify(site, state) for site in merged)
        flagged: dict[str, int] = {}
        for site in sites:
            status = site.geocode.status
            flagged[status] = flagged.get(status, 0) + 1
        unchecked = sum(1 for site in sites if not site.geocode.zip_checked)

        notes = [
            f"{len(rows)} air permits over {len(air_sites)} FRS sites",
            f"{join.sites} RCRA large-quantity generator or TSD sites over "
            f"{join.screened} handler rows; {join.matched} joined the air feed, "
            f"{join.unmatched} loaded on their own facility rows",
            f"ZIP centroids from the {GAZETTEER_YEAR} Census gazetteer "
            f"({len(self._zip_centroids)} ZIP codes)",
        ]
        if len(rows) < expected:
            notes.append(f"upstream reported {expected} rows, {len(rows)} were paged")

        return FetchResult(
            records=sites,
            known_gaps=self._positional_gaps(flagged, unchecked, len(sites))
            + self._rcra_gaps(join),
            # ECHO republishes continuously rather than in numbered releases, so
            # the refresh date is the only release identifier it has. Section 12
            # computes recency from this.
            vintage=f"weekly/{ctx.now.date().isoformat()}",
            artifacts=artifacts,
            notes=notes,
        )

    async def _rcra_handlers(
        self, ctx: RunContext, state: str
    ) -> tuple[dict[str, RcraHandler], int, int, list[Artifact]]:
        """The pilot state's large-quantity generators and TSD facilities, by site.

        Every handler the state holds is paged and screened here rather than
        filtered upstream, because the service ignores query parameters it does not
        recognise and would answer a generator-status filter with all 23,782 rows.
        See the module docstring.

        A failure raises, which fails the whole ECHO pull rather than loading the
        air feed on its own. Both flags false for every facility is the reading
        "measured, and there are none nearby" of a question that was never asked,
        and F4 would be a column of honest-looking zeroes.
        """
        columns = ",".join(str(cid) for cid, _ in RCRA_QCOLUMNS)

        opened = await ctx.http.get(RCRA_GET_FACILITIES, params={"output": "JSON", "p_st": state})
        results = self._results(opened.content, RCRA_GET_FACILITIES)
        qid = _as_text(results.get("QueryID"))
        expected = _as_int(results.get("QueryRows"))
        if not qid:
            raise PermanentSourceError(f"{RCRA_GET_FACILITIES}: no QueryID in the response")
        if expected == 0:
            raise PermanentSourceError(f"{RCRA_GET_FACILITIES}: {state} matched no RCRA handlers")

        artifacts = [opened.artifact]
        rows: list[dict[str, str]] = []
        for page in range(1, MAX_PAGES + 1):
            download = await ctx.http.get(
                RCRA_GET_QID,
                params={
                    "output": "JSON",
                    "qid": str(qid),
                    "pageno": str(page),
                    "responseset": str(PAGE_SIZE),
                    "qcolumns": columns,
                },
            )
            artifacts.append(download.artifact)
            batch = _as_rows(self._results(download.content, RCRA_GET_QID).get("Facilities"))
            rows.extend(batch)
            if len(batch) < PAGE_SIZE or len(rows) >= expected:
                break

        if not rows:
            # As on the air side: a qid returning nothing is an expired query
            # rather than a state without hazardous waste in it.
            raise PermanentSourceError(f"{RCRA_GET_QID}: qid {qid} returned no rows")

        handlers, unkeyed = self._group_handlers(rows)
        return handlers, len(rows), unkeyed, artifacts

    @staticmethod
    def _group_handlers(rows: Sequence[dict[str, str]]) -> tuple[dict[str, RcraHandler], int]:
        """One entry per FRS site, keeping only the sites F4 counts.

        Grouped before screening rather than after, so a site whose large-quantity
        generator is one handler among several is still a large-quantity generator
        site. The key is what `facility_id` will be, which is how the merge against
        the air feed and the schema's primary key stay the same question.
        """
        grouped: dict[str, list[dict[str, str]]] = {}
        unkeyed = 0
        for row in rows:
            key = (row.get("RegistryID") or "").strip()
            if not key:
                handler_id = (row.get("SourceID") or "").strip()
                if not handler_id:
                    # Neither identifier: there is nothing to key a facility on and
                    # nothing to join it by. Counted into the manifest instead.
                    unkeyed += 1
                    continue
                key = f"rcra:{handler_id}"
            grouped.setdefault(key, []).append(row)

        sites: dict[str, RcraHandler] = {}
        for key, group in grouped.items():
            handler = RcraHandler.of("" if key.startswith("rcra:") else key, group)
            if handler.is_lqg or handler.is_tsdf:
                sites[key] = handler
        return sites, unkeyed

    @staticmethod
    def _merge_rcra(
        air: Sequence[EchoSite], handlers: Mapping[str, RcraHandler]
    ) -> tuple[tuple[EchoSite, ...], int]:
        """Attach the flags to the air sites they belong to, then add what is left.

        Acceptance criteria one and two. A site the air feed already holds gets its
        flags on its existing row, because the sink upserts a whole facility on its
        natural key and a second row would overwrite the permit, compliance and
        enforcement knowledge this adapter just built. A site the air feed does not
        hold becomes its own facility, so its proximity still reaches F4.
        """
        sites: list[EchoSite] = []
        matched = 0
        for site in air:
            handler = handlers.get(site.facility_id) if site.facility_id else None
            if handler is None:
                sites.append(site)
                continue
            matched += 1
            sites.append(replace(site, rcra=handler))

        seen = {site.facility_id for site in air if site.facility_id}
        for key, handler in handlers.items():
            if key not in seen:
                sites.append(EchoSite(registry_id=handler.registry_id, sources=(), rcra=handler))
        return tuple(sites), matched

    @staticmethod
    def _results(payload: bytes, url: str) -> dict[str, object]:
        try:
            document = json.loads(payload)
        except ValueError as exc:
            raise PermanentSourceError(f"{url}: response was not JSON ({exc})") from None
        results = document.get("Results")
        if not isinstance(results, dict):
            raise PermanentSourceError(f"{url}: no Results object")
        error = results.get("Error")
        if isinstance(error, dict):
            raise PermanentSourceError(f"{url}: {error.get('ErrorMessage', 'unknown error')}")
        return results

    @staticmethod
    def _group_by_site(rows: Sequence[dict[str, str]]) -> tuple[EchoSite, ...]:
        """One record per FRS site. See the module docstring."""
        grouped: dict[str, list[dict[str, str]]] = {}
        unkeyed: list[dict[str, str]] = []
        for row in rows:
            registry = (row.get("RegistryID") or "").strip()
            if registry:
                grouped.setdefault(registry, []).append(row)
            else:
                # Kept as its own site so validate can reject it and the loss is
                # counted, rather than dropped silently here.
                unkeyed.append(row)
        sites = [EchoSite(registry_id=key, sources=tuple(v)) for key, v in grouped.items()]
        sites.extend(EchoSite(registry_id="", sources=(row,)) for row in unkeyed)
        return tuple(sites)

    # ---- validate ------------------------------------------------------

    def validate(self, record: EchoSite, ctx: RunContext) -> None:
        if not record.facility_id:
            raise RecordRejected("missing FRS registry id", field="RegistryID")
        if not record.sources and record.rcra is None:
            raise RecordRejected("no air permits", record_id=record.facility_id)
        if not record.name:
            raise RecordRejected(
                "missing facility name", field="AIRName", record_id=record.facility_id
            )

        state = record.state
        if state and state.upper() != ctx.pilot_state:
            # The query filtered by state, so this means upstream disagrees with
            # itself. Attributing it to a Louisiana hexagon would be wrong.
            raise RecordRejected(
                f"reported state {state} is not {ctx.pilot_state}",
                field="AIRState",
                record_id=record.facility_id,
            )

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: EchoSite, ctx: RunContext) -> Iterator[NormalizedRecord]:
        facility = self._facility(record)
        yield facility
        # A hazardous-waste site holding no air permit has no Clean Air Act
        # compliance history to report, and twelve 'unknown' CAA quarters for it
        # would assert that somebody looked at it under a statute it is not
        # permitted under. RCRA's own compliance history is a separate feed and a
        # separate ticket; see `known_gaps`.
        if record.has_air_permits:
            yield from self._compliance_quarters(record, facility.facility_id, ctx)
            yield from self._enforcement(record, facility.facility_id)

    def _facility(self, site: EchoSite) -> Facility:
        reported_lat, reported_lon = site.reported_point
        # A verdict that leaves no storable point takes the geometry with it. A
        # placeholder zero written into the table would put a Louisiana refinery
        # in the Gulf of Guinea; the reported_* pair keeps what upstream said so
        # the quarantine is still auditable.
        latitude = reported_lat if site.geocode.has_point else None
        longitude = reported_lon if site.geocode.has_point else None

        return Facility(
            facility_id=site.facility_id,
            registry_id=site.registry_id,
            name=site.name or "",
            street=site.attribute("AIRStreet", "street"),
            city=site.attribute("AIRCity", "city"),
            state=site.state,
            zip5=site.zip5,
            county_fips=site.county_fips,
            naics_code=site.naics_code,
            latitude=latitude,
            longitude=longitude,
            reported_latitude=reported_lat,
            reported_longitude=reported_lon,
            h3=containing_cell(latitude, longitude),
            coordinate_status=site.geocode.status,
            geocode_quality=site.geocode.quality,
            geocode_accuracy_m=site.geocode.accuracy_m,
            # Clean Air Act permitting, from the air feed alone. A hazardous-waste
            # site holding no air permit is not a major source by default; it is a
            # site this feed says nothing about, which is what false means here.
            is_major_source=site.any_equals("AIRMajorFlag", "Y"),
            has_title_v=site.any_equals("AIRClassification", "Major Emissions"),
            is_rcra_lqg=site.is_rcra_lqg,
            is_rcra_tsdf=site.is_rcra_tsdf,
            # The public report is keyed by FRS id, so a site loaded under a
            # `rcra:` key has no report to link to rather than a broken link.
            echo_url=DFR_URL.format(registry_id=site.registry_id) if site.registry_id else "",
            air_source_ids=tuple(
                sid for s in site.sources if (sid := (s.get("SourceID") or "").strip())
            ),
            operating_status=site.first("AIRStatus"),
        )

    def _classify(self, site: EchoSite, state: str) -> EchoSite:
        """Methodology section 6, delegated to `pipeline.geo`.

        The rules live there rather than here because TRI publishes the same
        kind of self-reported coordinate and must reach the same verdict on it.
        What stays the adapter's business is where the inputs come from: ECHO's
        reported ZIP, and its own positional accuracy estimate.

        Flagged facilities are kept, not dropped. The exclusion count is
        published, and proximity indicators filter on 'ok'; deleting the rows
        would hide the problem and make the count unrecoverable.
        """
        latitude, longitude = site.reported_point
        return replace(
            site,
            geocode=classify(
                latitude,
                longitude,
                state=state,
                # None both when no ZIP was reported and when the pinned
                # gazetteer does not carry it. Either way the check could not
                # run, which is not the same as passing it.
                zip_centroid=self._zip_centroids.get(site.zip5 or ""),
                accuracy_m=site.accuracy_m,
            ),
        )

    @staticmethod
    def _positional_gaps(
        flagged: Mapping[str, int], unchecked: int, total: int
    ) -> tuple[KnownGap, ...]:
        """What section 6 requires this pull to publish about itself."""
        gaps: list[KnownGap] = []
        excluded = sum(count for status, count in flagged.items() if status != "ok")
        if excluded:
            breakdown = ", ".join(f"{status} {count}" for status, count in sorted(flagged.items()))
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{excluded} of {total} sites were excluded from proximity "
                        f"indicators on positional accuracy (section 6): {breakdown}. "
                        f"They are retained in the facility table so the count stays "
                        f"recoverable."
                    ),
                    affects=("F1", "F2", "F3", "F4"),
                )
            )
        if unchecked:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{unchecked} of {total} sites could not be ZIP-checked: no reported "
                        f"ZIP, or one absent from the {GAZETTEER_YEAR} gazetteer. They are "
                        f"marked 'ok' because the check could not run, which is not the same "
                        f"as passing it."
                    ),
                    affects=("F1", "F2", "F3", "F4"),
                )
            )
        return tuple(gaps)

    @staticmethod
    def _rcra_gaps(join: RcraJoin) -> tuple[KnownGap, ...]:
        """What this pull has to publish about the hazardous-waste join.

        Acceptance criterion three. The unmatched count is the one a reader needs:
        every site in it is a generator whose proximity reaches F4 only because it
        was loaded on a row of its own, and the same number is what would silently
        have gone missing under a join that dropped its misses.
        """
        gaps: list[KnownGap] = [
            KnownGap(
                scope="attribute",
                detail=(
                    f"{join.screened} RCRA handler rows were screened for the two flags F4 "
                    f"counts, leaving {join.sites} FRS sites that are large-quantity "
                    f"generators, TSD facilities, or both. {join.matched} joined a facility "
                    f"the air feed loaded and carry the flags on that row; {join.unmatched} "
                    f"did not join and are loaded under their own facility rows rather than "
                    f"dropped, so their proximity still reaches F4. A site in that second "
                    f"group holds no Clean Air Act permit, so it contributes to F4 and not "
                    f"to F1, F2 or F3."
                ),
                affects=("F4",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "A TSD facility is flagged from the permitted unit types RCRA reports "
                    "for it, not from the RCRA_UNIVERSE string, which names roughly half as "
                    "many: BASF at Zachary reports its universe as 'LQG' and its units as "
                    "land disposal, incineration, storage and treatment. Legacy TSDFs are "
                    "counted alongside operating ones, because methodology section 8.2 "
                    "qualifies F1 with 'active' and F4 with nothing, and the waste in a "
                    "closed land disposal unit does not leave when the permit lapses. "
                    "Counting only operating TSDFs would be a defensible alternative "
                    "reading and is a methodology revision under section 17."
                ),
                affects=("F4",),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "RCRA's own compliance quarters, violations and enforcement actions are "
                    "not ingested, only the two flags F4 needs. F2 and F3 therefore describe "
                    "Clean Air Act behaviour alone, and a facility with a clean air record "
                    "and a hazardous-waste violation history reads as compliant in both."
                ),
                affects=("F2", "F3"),
            ),
        ]
        if join.unkeyed:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{join.unkeyed} RCRA rows carried neither an FRS registry id nor a "
                        f"handler id. There is nothing to key a facility on and nothing to "
                        f"join them by, so they are not loaded at all. If any of them is a "
                        f"generator, its F4 contribution is missing and this count is the "
                        f"upper bound on how much."
                    ),
                    affects=("F4",),
                )
            )
        return tuple(gaps)

    def _compliance_quarters(
        self, site: EchoSite, facility_id: str, ctx: RunContext
    ) -> Iterator[ComplianceQuarter]:
        """Twelve quarters, worst status across the site's permits.

        The schema keys a quarter by facility, not by permit, so a site holding
        several permits has to resolve to one status per quarter. The worst one
        wins: a site with any permit in high priority violation that quarter was
        a site in high priority violation.
        """
        starts = twelve_quarters_ending(ctx.now.date())
        severity = {"unknown": 0, "in_compliance": 1, "violation": 2, "high_priority_violation": 3}
        worst: dict[date, str] = {}

        for source in site.sources:
            history = (source.get("AIR3yrComplQtrsHistory") or "").strip()
            if len(history) != QUARTERS:
                continue
            # '_' is ECHO's "nothing to report". It means compliance only where
            # the facility has a compliance status at all; where it does not,
            # the quarter is unknown. The schema is explicit that an uninspected
            # quarter is not a clean one.
            monitored = bool((source.get("AIRComplStatus") or "").strip())
            for start, mark in zip(starts, history, strict=True):
                status = _QUARTER_STATUS.get(mark)
                if status is None:
                    status = "in_compliance" if (mark == "_" and monitored) else "unknown"
                if severity[status] > severity.get(worst.get(start, "unknown"), 0):
                    worst[start] = status

        for start in starts:
            yield ComplianceQuarter(
                facility_id=facility_id,
                quarter=start,
                program="CAA",
                status=worst.get(start, "unknown"),
            )

    def _enforcement(self, site: EchoSite, facility_id: str) -> Iterator[EnforcementAction]:
        """The most recent formal action, where the bulk feed reports one.

        See `known_gaps`: this feed carries a five-year count and the date of the
        latest action, not one record per action, so a facility contributes at
        most one row here however many actions it has had.
        """
        settled = _parse_date(site.first("AIRLastFeaDate"))
        if settled is None:
            return
        penalty = _parse_float(site.first("AIRPenalties"))
        yield EnforcementAction(
            action_id=f"echo:{facility_id}:fea:{settled.isoformat()}",
            facility_id=facility_id,
            program="CAA",
            action_type="formal enforcement action",
            settled_on=settled,
            penalty_usd=penalty,
            is_formal=True,
        )

    # ---- gaps ----------------------------------------------------------

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="attribute",
                detail=(
                    "The bulk air feed reports a five-year count of formal enforcement "
                    "actions and the date of the most recent one, not a record per "
                    "action. Each facility contributes at most one enforcement row, so "
                    "F3 currently distinguishes 'has had a formal action' rather than "
                    "counting them."
                ),
                affects=("F3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "Violation and enforcement counts partly measure inspection "
                    "frequency rather than pollution: a facility accumulates a record "
                    "when somebody looks at it. Methodology section 8.2 weights this "
                    "group at 0.5 for that reason; it is a bias, not a solved problem."
                ),
                affects=("F2", "F3"),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "Facility coordinates are self-reported. EPA's own accuracy "
                    "estimate exceeds 2 km for roughly three quarters of Louisiana air "
                    "facilities, which is why section 6 checks the reported ZIP centroid "
                    "rather than trusting the coordinate."
                ),
                affects=("F1", "F2", "F3", "F4"),
            ),
            KnownGap(
                scope="temporal",
                detail=(
                    "Several EPA environmental justice datasets and tools were withdrawn "
                    "from public hosting during 2025. Upstream availability is treated as "
                    "unreliable: every artifact records its URL, retrieval date and "
                    "checksum, and a night when ECHO is unreachable continues on the last "
                    "good snapshot with the recency term degraded rather than skipping."
                ),
                affects=("F1", "F2", "F3", "F4"),
                since=date(2025, 1, 1),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "The section 6 ZIP check measures distance to the ZIP centroid, which "
                    "is not the same question as whether the facility lies inside its ZIP. "
                    "A Louisiana ZIP code has a median land area near 78 square miles, so "
                    "its typical radius is around 8 km and a correctly sited facility is "
                    "routinely more than 2 km from the centroid. Roughly a fifth of "
                    "Louisiana air facilities are excluded on this rule at a median "
                    "distance of 7.2 km, and flagged facilities sit in ZIP codes no larger "
                    "than unflagged ones, so the exclusions are not explained by rural "
                    "geography. Treat the flag as 'unverified location', not 'wrong "
                    "location'. Testing against the ZIP polygon, or scaling the threshold "
                    "by ZIP radius, would be a methodology revision under section 17."
                ),
                affects=("F1", "F2", "F3", "F4"),
            ),
            KnownGap(
                scope="geographic",
                detail=(
                    "The pilot-state check is the state's bounding box widened by the "
                    "10 km interaction radius, not the state boundary. It is that wide on "
                    "purpose: section 5 counts out-of-state facilities close enough to "
                    "affect a Louisiana hexagon, so a coordinate is only treated as wrong "
                    "for being outside the state when it cannot be about Louisiana at "
                    "all. Which facilities actually reach which hexagons is settled by "
                    "the neighbour query on real geometry, not by this box."
                ),
                affects=("F1", "F2", "F3", "F4"),
            ),
            KnownGap(
                scope="geographic",
                detail=(
                    "This adapter queries ECHO one state at a time, so the out-of-state "
                    "facilities section 5 asks for are not ingested yet even though the "
                    "neighbour query includes any that are present. Until a neighbouring-"
                    "state pull lands, hexes along the Texas, Arkansas and Mississippi "
                    "lines understate F1 through F4."
                ),
                affects=("F1", "F2", "F3", "F4"),
            ),
        )
