"""EPA TRI: annual on-site air releases by facility, chemical and reporting year.

Feeds E3 (methodology section 8.1). TRI is self-reported annual accounting, not
measurement: a facility estimates what it released and files it. Section 8.1 uses
it as "how much toxic material is released nearby" rather than as an exposure
estimate, which is what AirToxScreen provides for E1 and E2.

The source is Envirofacts. Two of its tables are used rather than one, and the
reason is the whole of acceptance criterion three.

**The TRI Basic Data File is the release source.** `mv_tri_basic_download` is the
published Basic Data File exposed as a query. It is preferred over the raw
`tri_reporting_form` / `tri_release_qty` pair for two reasons established by
querying both. It resolves TRI's range codes: a facility releasing under 1,000 lb
may report a range instead of a figure, and 73 of Louisiana's 2,324 reported
fugitive-air rows for 2024 do so. The raw table gives only the code, and EPA's
own resolution of codes 1, 3 and 4 is 5, 250 and 750 lb, the range midpoints. It
also carries usable coordinates: `tri_facility` has no latitude for 500 of
Louisiana's 957 TRI facilities, including Denka Performance Elastomer at Reserve,
while the Basic Data File has one for every 2024 filing.

**The FRS identifier comes from `tri_facility`, not from the Basic Data File.**
Both publish one. They disagree for 104 of Louisiana's 2,885 matched 2024 rows,
and the disagreement is not a coin toss: of the filers where they differ, seven
join an ECHO facility on `tri_facility.epa_registry_id` and none join on the
Basic Data File's `frs id`. Note that `tri_facility.frs_id`, the obvious-looking
column, is null for all 957 Louisiana facilities; the populated one is
`epa_registry_id`.

Three further things about TRI that shaped this adapter:

**Longitude is unsigned in `tri_facility` and signed in the Basic Data File.**
All 957 Louisiana rows in `tri_facility` report a positive longitude, and
negating them puts all 957 inside the state envelope. The Basic Data File already
signs them, which is the second reason it is the release source. Reading
`tri_facility` coordinates without negating would place every Louisiana facility
in China.

**Form A is not a report of zero.** A facility below the alternate threshold
files a Form A certification instead of a Form R, and a Form A carries no release
quantities at all. The Basic Data File renders those rows as `0` for fugitive and
stack air, which merges "did not report" into "reported nothing" — exactly what
methodology section 11 and acceptance criterion four forbid. This adapter reads
`form type` and emits `Measurement.absent()` for a Form A filing and
`Measurement.of(0.0)` only where a Form R actually reported zero. Louisiana's
2024 extract holds 158 Form A filings across 68 facilities. No facility filed
both a Form R and a Form A for the same chemical, so the distinction is never
ambiguous within one release record.

**Dioxin is reported in grams.** `unit of measure` is per filing, and 42 of
Louisiana's 2,895 rows for 2024 are dioxin in grams. Reading them as pounds would
overstate them 453.6-fold. The column also spells pounds two ways, `Pounds` and
`POUNDS`, so the comparison is case-folded; an unrecognised unit rejects the
record rather than being assumed.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, ClassVar

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.echo import (
    DFR_URL,
    GAZETTEER_URL,
    GAZETTEER_YEAR,
    GET_FACILITIES,
    GET_QID,
    RCRA_GET_FACILITIES,
    RCRA_GET_QID,
    Facility,
    is_large_quantity_generator,
    is_tsd_facility,
    load_zip_centroids,
)
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.geo import Geocode, classify, containing_cell
from pipeline.metadata import KnownGap, SourceSpec
from pipeline.policy import RateLimit, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord

ENVIROFACTS = "https://data.epa.gov/efservice"
BASIC_FILE = f"{ENVIROFACTS}/mv_tri_basic_download"
TRI_FACILITY = f"{ENVIROFACTS}/tri_facility"

# TRI runs about eighteen months behind: the 2024 reporting year was the newest
# available in September 2026. `fetch` walks back from the current year rather
# than pinning one, and this bounds the walk so a withdrawn dataset fails the run
# instead of silently scoring the state on a decade-old vintage.
MAX_VINTAGE_LOOKBACK = 4

GRAMS_PER_POUND = 453.59237
POUNDS = "pounds"
GRAMS = "grams"

# Form R is the full reporting form and carries quantities. Form A is the
# alternate threshold certification and carries none. See the module docstring.
FORM_R = "R"
FORM_A = "A"

# The Basic Data File's column names contain spaces, so they are named once here
# rather than spelled out at each use.
COL_TRIFD = "trifd"
COL_FRS = "frs id"
COL_NAME = "facility name"
COL_STREET = "street address"
COL_CITY = "city"
COL_STATE = "st"
COL_ZIP = "zip"
COL_LAT = "latitude"
COL_LON = "longitude"
COL_NAICS = "primary naics"
COL_CAS = "cas#"
COL_CHEMICAL = "chemical"
COL_FORM_TYPE = "form type"
COL_UNIT = "unit of measure"
COL_FUGITIVE = "5.1 - fugitive air"
COL_STACK = "5.2 - stack air"

# Only the registry id is needed from ECHO; the ECHO adapter loads everything
# else about these facilities. Column 8 is REGISTRY_ID.
ECHO_REGISTRY_COLUMN = "8"
ECHO_PAGE_SIZE = 5000
ECHO_MAX_PAGES = 20

# The ECHO adapter loads a facility row for a hazardous-waste site too, whether or
# not it holds an air permit (CS-116), so "a facility ECHO already holds" is the
# union of the two feeds. Asking the air feed alone would have this adapter write a
# second row over one of those, and the sink upserts a whole facility on its
# natural key: the hazardous-waste flags F4 reads would be replaced by this
# adapter's defaults, and which of the two nightly pulls ran last would decide
# whether F4 saw the site. Columns 25 and 26 are RCRA_UNIVERSE and TSDF, which is
# all the screen needs.
RCRA_SCREEN_COLUMNS = "8,25,26"


class TriRelease(NormalizedRecord):
    """One facility's air releases of one chemical in one reporting year.

    Both media are `Measurement` rather than floats because the schema's columns
    are `NOT NULL DEFAULT 0` and cannot themselves hold the difference between a
    reported zero and an unreported quantity. Keeping the distinction on the
    record means `load` decides what is storable, instead of `normalize`
    flattening an absence into a zero on the way past.
    """

    table: ClassVar[str] = "tri_release"

    facility_id: str
    reporting_year: int
    cas_number: str
    chemical_name: str
    fugitive_air: Measurement
    stack_air: Measurement

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id, str(self.reporting_year), self.cas_number)

    @property
    def reported(self) -> bool:
        """True when the facility filed a quantity. False for a Form A filing."""
        return self.fugitive_air.observed and self.stack_air.observed

    @property
    def air_lb(self) -> Measurement:
        """Total on-site air, the `m_{f,c}` of the E3 formula in section 8.1."""
        fugitive, stack = self.fugitive_air.value, self.stack_air.value
        if fugitive is None or stack is None:
            return Measurement.absent()
        return Measurement.of(fugitive + stack)


@dataclass(frozen=True, slots=True)
class TriForm:
    """One filed form: one facility, one chemical, one year."""

    cas_number: str
    chemical_name: str
    form_type: str
    unit: str
    fugitive: float | None
    stack: float | None

    @property
    def quantified(self) -> bool:
        return self.form_type == FORM_R


@dataclass(frozen=True, slots=True)
class TriSite:
    """One physical site and every form it filed for the reporting year.

    `fetch` produces these rather than raw rows because `tri_release` is unique
    on facility, year and chemical, and Louisiana's 2024 extract breaks that key
    twice over: 47 facility-chemical pairs are split across several forms, every
    one of them flagged a partial-facility report, and two FRS registry ids are
    each shared by two TRI facilities. Both are the same site reporting in
    pieces, so `normalize` sums them.

    `owns_facility_row` is the join result. It is False when the site's FRS id
    matches a facility ECHO already loads, from either its air feed or its
    hazardous-waste feed, in which case this adapter writes releases only and
    leaves the facility row to the adapter that knows about permits, compliance,
    enforcement and the RCRA flags.
    """

    facility_id: str
    registry_id: str | None
    tri_facility_ids: tuple[str, ...]
    name: str
    street: str | None
    city: str | None
    state: str | None
    zip5: str | None
    county_fips: str | None
    naics_code: str | None
    latitude: float | None
    longitude: float | None
    forms: tuple[TriForm, ...]
    owns_facility_row: bool
    geocode: Geocode = Geocode(status="ok", quality="unverified")

    @property
    def coordinate_status(self) -> str:
        return self.geocode.status

    @property
    def zip_checked(self) -> bool:
        return self.geocode.zip_checked


def to_pounds(value: float, unit: str) -> float:
    """Normalize a reported quantity to pounds. See the module docstring."""
    folded = unit.strip().lower()
    if folded == POUNDS:
        return value
    if folded == GRAMS:
        return value / GRAMS_PER_POUND
    raise RecordRejected(f"unrecognised unit of measure {unit!r}", field=COL_UNIT)


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def _number(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _rows(payload: bytes, url: str) -> list[dict[str, Any]]:
    """Envirofacts returns a bare JSON array, or an object carrying an error."""
    try:
        document = json.loads(payload)
    except ValueError as exc:
        raise PermanentSourceError(f"{url}: response was not JSON ({exc})") from None
    if isinstance(document, dict):
        raise PermanentSourceError(f"{url}: {document.get('error', 'unexpected object response')}")
    if not isinstance(document, list):
        raise PermanentSourceError(f"{url}: expected a JSON array")
    return [row for row in document if isinstance(row, dict)]


@register
class EpaTriAdapter(SourceAdapter[TriSite]):
    """Annual on-site air releases, joined to the ECHO facilities that hold them."""

    spec = SourceSpec(
        name="epa_tri",
        title="EPA Toxics Release Inventory (TRI)",
        homepage="https://www.epa.gov/toxics-release-inventory-tri-program",
        cadence="annual, roughly an 18-month lag",
        native_geography="point (facility lat/lon, self-reported)",
        provides=("E3",),
    )

    # Two departures from the default, both about how Envirofacts serves a
    # full-state query rather than about how failure is handled.
    #
    # Envirofacts publishes no rate limit. Two requests a second matches the ECHO
    # adapter and is well under what a browser session generates; this pull is a
    # handful of large requests rather than many small ones.
    #
    # The timeout is raised as headroom, not to fix an observed break. One
    # Louisiana year of the Basic Data File is 9 MB and took 109 to 126 seconds
    # to serve when this was written, though it began streaming after 2.4, so the
    # default 30 seconds survives it: that default is a per-read timeout rather
    # than a deadline for the whole response. What it would not survive is
    # Envirofacts spending half a minute preparing a query before its first byte,
    # which is a plausible shape for a service that takes two minutes over one
    # state. Everything else about failure handling is the runner's.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit(requests_per_second=2.0, burst=2),
        request_timeout_s=180.0,
    )

    def __init__(self) -> None:
        # Reference data, loaded once by fetch and read per record. Not per-record
        # state: validate and normalize stay pure functions of the record plus
        # these lookups.
        self._zip_centroids: dict[str, tuple[float, float]] = {}
        self._reporting_year = 0

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[TriSite]:
        state = ctx.pilot_state
        artifacts = []

        year, probes = await self._latest_reporting_year(ctx, state)
        artifacts.extend(probes)
        self._reporting_year = year

        releases = await ctx.http.get(f"{BASIC_FILE}/st/{state}/year/{year}/JSON")
        artifacts.append(releases.artifact)
        rows = _rows(releases.content, BASIC_FILE)
        if not rows:
            raise PermanentSourceError(f"{BASIC_FILE}: {state} {year} returned no rows")

        registry, directory = await self._facility_directory(ctx, state)
        artifacts.append(directory)

        echo_ids, echo_artifacts = await self._echo_registry_ids(ctx, state)
        artifacts.extend(echo_artifacts)

        rcra_ids, rcra_artifacts = await self._rcra_registry_ids(ctx, state)
        artifacts.extend(rcra_artifacts)
        echo_ids |= rcra_ids

        gazetteer = await ctx.http.get(GAZETTEER_URL)
        artifacts.append(gazetteer.artifact)
        self._zip_centroids = load_zip_centroids(gazetteer.content)

        sites = tuple(
            self._classify(site, state) for site in self._group_by_site(rows, registry, echo_ids)
        )

        return FetchResult(
            records=sites,
            # Acceptance criterion two. The vintage is the reporting year the
            # releases describe, not the night the file was downloaded, so the
            # recency term in section 12 measures the age of the release and a
            # run can never quietly mix two years.
            vintage=str(year),
            artifacts=artifacts,
            known_gaps=self._pull_gaps(sites),
            notes=self._pull_notes(rows, sites, year, state),
        )

    async def _latest_reporting_year(self, ctx: RunContext, state: str) -> tuple[int, list[Any]]:
        """The newest reporting year upstream actually holds for the pilot state.

        Pinning a year in the source would mean a hand edit every spring and a
        silently stale map in between, and asking for "the current year" would
        return nothing for most of the calendar. Both are worse than one cheap
        count per candidate year.
        """
        artifacts = []
        for offset in range(MAX_VINTAGE_LOOKBACK):
            year = ctx.now.year - offset
            url = f"{BASIC_FILE}/st/{state}/year/{year}/COUNT/JSON"
            probe = await ctx.http.get(url)
            artifacts.append(probe.artifact)
            counts = _rows(probe.content, url)
            total = int(_number(counts[0], "TOTALQUERYRESULTS") or 0) if counts else 0
            if total > 0:
                return year, artifacts
        raise PermanentSourceError(
            f"{BASIC_FILE}: no reporting year for {state} in the "
            f"{MAX_VINTAGE_LOOKBACK} years to {ctx.now.year}"
        )

    async def _facility_directory(
        self, ctx: RunContext, state: str
    ) -> tuple[dict[str, dict[str, Any]], Any]:
        """`tri_facility` keyed by TRI id, for the FRS id and the county FIPS."""
        url = f"{TRI_FACILITY}/state_abbr/{state}/JSON"
        download = await ctx.http.get(url)
        rows = _rows(download.content, url)
        if not rows:
            raise PermanentSourceError(f"{url}: {state} matched no TRI facilities")
        return {_text(row, "tri_facility_id"): row for row in rows}, download.artifact

    async def _echo_registry_ids(self, ctx: RunContext, state: str) -> tuple[set[str], list[Any]]:
        """Every FRS registry id ECHO's air feed holds for the pilot state.

        The join has to be made against the live service because the sink is
        write-only: an adapter cannot ask the database what ECHO loaded. Query
        ids expire, so the query is created and paged immediately, exactly as the
        ECHO adapter does.
        """
        artifacts = []
        opened = await ctx.http.get(GET_FACILITIES, params={"output": "JSON", "p_st": state})
        artifacts.append(opened.artifact)
        try:
            results = json.loads(opened.content)["Results"]
            qid = str(results["QueryID"]).strip()
        except (ValueError, KeyError, TypeError):
            raise PermanentSourceError(f"{GET_FACILITIES}: no QueryID in the response") from None
        if not qid:
            raise PermanentSourceError(f"{GET_FACILITIES}: no QueryID in the response")

        ids: set[str] = set()
        for page in range(1, ECHO_MAX_PAGES + 1):
            download = await ctx.http.get(
                GET_QID,
                params={
                    "output": "JSON",
                    "qid": qid,
                    "pageno": str(page),
                    "responseset": str(ECHO_PAGE_SIZE),
                    "qcolumns": ECHO_REGISTRY_COLUMN,
                },
            )
            artifacts.append(download.artifact)
            document = json.loads(download.content)
            batch = document.get("Results", {}).get("Facilities") or []
            for row in batch:
                if isinstance(row, dict) and (rid := (row.get("RegistryID") or "").strip()):
                    ids.add(rid)
            if len(batch) < ECHO_PAGE_SIZE:
                break

        if not ids:
            # An empty page one is an expired query id rather than a state with no
            # air facilities, and every release would be reported unmatched.
            raise PermanentSourceError(f"{GET_QID}: qid {qid} returned no registry ids")
        return ids, artifacts

    async def _rcra_registry_ids(self, ctx: RunContext, state: str) -> tuple[set[str], list[Any]]:
        """The FRS ids of the hazardous-waste sites the ECHO adapter loads.

        Screened here on the same rule that adapter uses, rather than trusted to a
        query parameter: the RCRA service ignores parameters it does not recognise
        and answers a generator-status filter with every handler in the state.
        """
        artifacts = []
        opened = await ctx.http.get(RCRA_GET_FACILITIES, params={"output": "JSON", "p_st": state})
        artifacts.append(opened.artifact)
        try:
            results = json.loads(opened.content)["Results"]
            qid = str(results["QueryID"]).strip()
        except (ValueError, KeyError, TypeError):
            raise PermanentSourceError(
                f"{RCRA_GET_FACILITIES}: no QueryID in the response"
            ) from None
        if not qid:
            raise PermanentSourceError(f"{RCRA_GET_FACILITIES}: no QueryID in the response")

        ids: set[str] = set()
        for page in range(1, ECHO_MAX_PAGES + 1):
            download = await ctx.http.get(
                RCRA_GET_QID,
                params={
                    "output": "JSON",
                    "qid": qid,
                    "pageno": str(page),
                    "responseset": str(ECHO_PAGE_SIZE),
                    "qcolumns": RCRA_SCREEN_COLUMNS,
                },
            )
            artifacts.append(download.artifact)
            document = json.loads(download.content)
            batch = document.get("Results", {}).get("Facilities") or []
            for row in batch:
                if not isinstance(row, dict):
                    continue
                if not (rid := (row.get("RegistryID") or "").strip()):
                    continue
                if is_large_quantity_generator(row) or is_tsd_facility(row):
                    ids.add(rid)
            if len(batch) < ECHO_PAGE_SIZE:
                break

        # Unlike the air query, an empty result is a legitimate answer: a state
        # need not hold a single large-quantity generator or TSD facility. The
        # expired-qid case is caught on the air side, which runs first against the
        # same service.
        return ids, artifacts

    @staticmethod
    def _group_by_site(
        rows: Sequence[Mapping[str, Any]],
        registry: Mapping[str, Mapping[str, Any]],
        echo_ids: set[str],
    ) -> tuple[TriSite, ...]:
        """One record per physical site. See `TriSite`."""
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(EpaTriAdapter._facility_id(row, registry), []).append(row)

        sites = []
        for facility_id, group in grouped.items():
            # Name, address and coordinate are read from the first filing. They
            # are identical across a facility's own forms in the Louisiana
            # extract. Where two TRI facilities share one FRS id, which is twice
            # in Louisiana's 2024 filers, the site takes one of the two names;
            # the releases are summed either way, and both TRI ids are kept.
            head = group[0]
            trifd = _text(head, COL_TRIFD)
            directory = registry.get(trifd, {})
            fips = _text(directory, "state_county_fips_code")
            registry_id = facility_id if not facility_id.startswith("tri:") else None
            sites.append(
                TriSite(
                    facility_id=facility_id,
                    registry_id=registry_id,
                    tri_facility_ids=tuple(sorted({_text(r, COL_TRIFD) for r in group})),
                    name=_text(head, COL_NAME),
                    street=_text(head, COL_STREET) or None,
                    city=_text(head, COL_CITY) or None,
                    state=_text(head, COL_STATE) or None,
                    zip5=(_text(head, COL_ZIP) or "")[:5] or None,
                    # state_county_fips_code is state plus county; the column in
                    # the schema holds the county part.
                    county_fips=fips[2:5] if len(fips) >= 5 else None,
                    naics_code=_text(head, COL_NAICS) or None,
                    latitude=_number(head, COL_LAT),
                    longitude=_number(head, COL_LON),
                    forms=tuple(EpaTriAdapter._form(r) for r in group),
                    owns_facility_row=registry_id is None or registry_id not in echo_ids,
                )
            )
        return tuple(sites)

    @staticmethod
    def _facility_id(row: Mapping[str, Any], registry: Mapping[str, Mapping[str, Any]]) -> str:
        """The schema's rule: the FRS registry id, or the TRI id prefixed `tri:`.

        `tri_facility.epa_registry_id` is preferred over the Basic Data File's
        `frs id` because it is the one that joins ECHO; see the module docstring.
        """
        trifd = _text(row, COL_TRIFD)
        directory = registry.get(trifd, {})
        return _text(directory, "epa_registry_id") or _text(row, COL_FRS) or f"tri:{trifd}"

    @staticmethod
    def _form(row: Mapping[str, Any]) -> TriForm:
        return TriForm(
            cas_number=_text(row, COL_CAS),
            chemical_name=_text(row, COL_CHEMICAL),
            form_type=_text(row, COL_FORM_TYPE).upper(),
            unit=_text(row, COL_UNIT),
            fugitive=_number(row, COL_FUGITIVE),
            stack=_number(row, COL_STACK),
        )

    def _classify(self, site: TriSite, state: str) -> TriSite:
        """Methodology section 6, delegated to `pipeline.geo`.

        The rule lives there rather than here because ECHO publishes the same
        kind of self-reported coordinate and both adapters write into one
        `facility` table that the proximity indicators filter on
        `coordinate_status = 'ok'`. A coordinate judged leniently here would
        mean something different depending on which adapter wrote the row.

        TRI publishes no positional accuracy estimate of its own, so
        `accuracy_m` stays None and the verdict rests on the envelope and the
        ZIP centroid alone.
        """
        return replace(
            site,
            geocode=classify(
                site.latitude,
                site.longitude,
                state=state,
                zip_centroid=self._zip_centroids.get(site.zip5 or ""),
            ),
        )

    # ---- validate ------------------------------------------------------

    def validate(self, record: TriSite, ctx: RunContext) -> None:
        if not record.facility_id:
            raise RecordRejected("missing facility identifier", field=COL_TRIFD)
        if not record.forms:
            raise RecordRejected("no filed forms", record_id=record.facility_id)
        if not record.name:
            raise RecordRejected(
                "missing facility name", field=COL_NAME, record_id=record.facility_id
            )
        if record.state and record.state.upper() != ctx.pilot_state:
            # The query filtered by state, so this means upstream disagrees with
            # itself. Attributing it to a Louisiana hexagon would be wrong.
            raise RecordRejected(
                f"reported state {record.state} is not {ctx.pilot_state}",
                field=COL_STATE,
                record_id=record.facility_id,
            )

        for form in record.forms:
            if not form.cas_number:
                raise RecordRejected(
                    "missing CAS number", field=COL_CAS, record_id=record.facility_id
                )
            if form.form_type not in (FORM_R, FORM_A):
                raise RecordRejected(
                    f"unknown form type {form.form_type!r}",
                    field=COL_FORM_TYPE,
                    record_id=record.facility_id,
                )
            # Checked here rather than in normalize so that a new unit upstream
            # shows up as a rejection count the tolerance can act on, instead of
            # as a quantity silently read in the wrong scale.
            if form.quantified:
                to_pounds(0.0, form.unit)

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: TriSite, ctx: RunContext) -> Iterator[NormalizedRecord]:
        if record.owns_facility_row:
            yield self._facility(record)
        yield from self._releases(record)

    def _facility(self, site: TriSite) -> Facility:
        """A facility row, written only for sites ECHO does not already hold.

        Writing one for a matched site would overwrite ECHO's permit, compliance
        and enforcement knowledge with this adapter's defaults, because the sink
        upserts a whole record on its natural key.
        """
        # A quarantined coordinate that is still a real place keeps its geometry,
        # so a reviewer can see where the row was excluded from; one that is not a
        # place at all stores no point. The reported_* pair keeps what upstream
        # said either way.
        latitude = site.latitude if site.geocode.has_point else None
        longitude = site.longitude if site.geocode.has_point else None
        return Facility(
            facility_id=site.facility_id,
            registry_id=site.registry_id or "",
            tri_facility_id=site.tri_facility_ids[0] if site.tri_facility_ids else None,
            name=site.name,
            street=site.street,
            city=site.city,
            state=site.state,
            zip5=site.zip5,
            county_fips=site.county_fips,
            naics_code=site.naics_code,
            latitude=latitude,
            longitude=longitude,
            reported_latitude=site.latitude,
            reported_longitude=site.longitude,
            h3=containing_cell(latitude, longitude),
            coordinate_status=site.geocode.status,
            geocode_quality=site.geocode.quality,
            # TRI publishes no positional accuracy estimate.
            geocode_accuracy_m=None,
            # TRI says nothing about Clean Air Act permitting. These stay false
            # rather than being guessed from the fact that a site reports.
            is_major_source=False,
            has_title_v=False,
            echo_url=DFR_URL.format(registry_id=site.registry_id) if site.registry_id else "",
            air_source_ids=(),
            operating_status=None,
        )

    @staticmethod
    def _by_chemical(site: TriSite) -> dict[str, list[TriForm]]:
        """The site's forms grouped into one release record's worth each."""
        grouped: dict[str, list[TriForm]] = {}
        for form in site.forms:
            grouped.setdefault(form.cas_number, []).append(form)
        return grouped

    def _releases(self, site: TriSite) -> Iterator[TriRelease]:
        """One release record per chemical, summing the site's forms for it.

        Acceptance criterion four lives here. A chemical whose forms are all Form
        A yields an absent measurement; a Form R reporting nothing yields
        `Measurement.of(0.0)`, which is an observation that the facility released
        none of it.
        """
        for cas_number, forms in self._by_chemical(site).items():
            quantified = [form for form in forms if form.quantified]
            if quantified:
                fugitive = Measurement.of(
                    sum(to_pounds(form.fugitive or 0.0, form.unit) for form in quantified)
                )
                stack = Measurement.of(
                    sum(to_pounds(form.stack or 0.0, form.unit) for form in quantified)
                )
            else:
                fugitive = stack = Measurement.absent()
            yield TriRelease(
                facility_id=site.facility_id,
                reporting_year=self._reporting_year,
                cas_number=cas_number,
                chemical_name=forms[0].chemical_name,
                fugitive_air=fugitive,
                stack_air=stack,
            )

    # ---- load ----------------------------------------------------------

    async def load(self, records: Sequence[NormalizedRecord], ctx: RunContext) -> int:
        """Write everything except releases that were never quantified.

        `tri_release.fugitive_air_lb` and `stack_air_lb` are `NOT NULL DEFAULT 0`,
        so the table has nowhere to put an absent measurement and writing one
        would have to invent a zero. The absences are counted in the manifest
        instead; see `_pull_gaps`. This is the only stage that may make that
        decision, because it is the only one that knows what the table can hold.
        """
        storable = [
            record for record in records if not isinstance(record, TriRelease) or record.reported
        ]
        return await super().load(storable, ctx)

    # ---- gaps ----------------------------------------------------------

    def _pull_gaps(self, sites: Sequence[TriSite]) -> tuple[KnownGap, ...]:
        """What this particular pull has to publish about itself."""
        gaps: list[KnownGap] = []

        unmatched = [site for site in sites if site.owns_facility_row]
        if unmatched:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{len(unmatched)} of {len(sites)} TRI sites did not join an ECHO "
                        f"facility on the FRS registry id, in either the air feed or the "
                        f"hazardous-waste feed. They are loaded under their own "
                        f"facility rows rather than dropped, so their releases still reach "
                        f"E3. Most are not absent from ECHO but carry a different registry "
                        f"id there: International Paper's Mansfield Mill reports FRS "
                        f"110000450173 to TRI and appears in ECHO as 110071723914, 2.6 km "
                        f"away. The consequence is that such a site can appear twice in a "
                        f"hex drill-down, once per source. Matching on name or coordinate "
                        f"would be a methodology revision under section 17."
                    ),
                    affects=("E3",),
                )
            )

        # Counted from the form types alone. Converting quantities here would
        # raise on a bad unit inside `fetch`, where there is no record to reject.
        unquantified = sum(
            1
            for site in sites
            for forms in self._by_chemical(site).values()
            if not any(form.quantified for form in forms)
        )
        if unquantified:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{unquantified} facility-chemical filings for this year are Form A "
                        f"certifications, which carry no release quantity. They are held as "
                        f"absent and are not written as zero rows, so E3 omits them rather "
                        f"than crediting those facilities with releasing nothing. EPA's own "
                        f"Basic Data File renders them as 0."
                    ),
                    affects=("E3",),
                )
            )

        flagged: dict[str, int] = {}
        for site in sites:
            flagged[site.coordinate_status] = flagged.get(site.coordinate_status, 0) + 1
        excluded = sum(count for status, count in flagged.items() if status != "ok")
        if excluded:
            breakdown = ", ".join(f"{status} {count}" for status, count in sorted(flagged.items()))
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{excluded} of {len(sites)} sites were excluded from proximity "
                        f"indicators on positional accuracy (section 6): {breakdown}. They "
                        f"are retained so the count stays recoverable."
                    ),
                    affects=("E3",),
                )
            )
        if flagged.get("zip_mismatch"):
            # Section 6's ZIP rule is far harsher on TRI than on ECHO, and the
            # difference is the rule rather than the data. Published here because
            # E3 is computed from the sites that pass it.
            gaps.append(
                KnownGap(
                    scope="methodological",
                    detail=(
                        f"The section 6 ZIP check excludes {flagged['zip_mismatch']} of "
                        f"{len(sites)} TRI sites, a far larger share than the roughly one "
                        f"fifth it excludes from ECHO, so E3 is currently computed from a "
                        f"minority of Louisiana's TRI facilities. The cause is the threshold, "
                        f"not the coordinates: Louisiana's 2024 filers sit a median of 5.0 km "
                        f"from their reported ZIP centroid while the median Louisiana ZIP is "
                        f"about 6.2 km in radius, and only 137 of 391 lie beyond their own "
                        f"ZIP's radius. TRI coordinates are EPA's preferred coordinates and "
                        f"agree with ECHO's to within a kilometre or two where both exist. "
                        f"Read the flag as 'unverified location', not 'wrong location'. "
                        f"Testing against the ZIP polygon, or scaling the threshold by ZIP "
                        f"radius, would be a methodology revision under section 17."
                    ),
                    affects=("E3",),
                )
            )

        unchecked = sum(1 for site in sites if not site.zip_checked)
        if unchecked:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{unchecked} of {len(sites)} sites could not be ZIP-checked: no "
                        f"reported ZIP, or one absent from the {GAZETTEER_YEAR} gazetteer. "
                        f"They are marked 'ok' because the check could not run, which is not "
                        f"the same as passing it."
                    ),
                    affects=("E3",),
                )
            )
        return tuple(gaps)

    @staticmethod
    def _pull_notes(
        rows: Sequence[Mapping[str, Any]], sites: Sequence[TriSite], year: int, state: str
    ) -> tuple[str, ...]:
        grams = sum(1 for row in rows if _text(row, COL_UNIT).strip().lower() == GRAMS)
        notes = [
            f"{len(rows)} {state} filings for reporting year {year} over {len(sites)} sites",
            f"{sum(1 for s in sites if not s.owns_facility_row)} sites joined an ECHO facility",
        ]
        if grams:
            notes.append(f"{grams} filings reported in grams and were converted to pounds")
        return tuple(notes)

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="temporal",
                detail=(
                    "TRI runs about eighteen months behind: reporting year 2024 was the "
                    "newest available in September 2026. A facility that opened, closed or "
                    "changed its processes since the reporting year is described by the "
                    "year, not by today."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="population",
                detail=(
                    "TRI covers only facilities that exceed a reporting threshold in a "
                    "covered sector with ten or more full-time equivalent employees. "
                    "Smaller industrial sources, and mobile sources entirely, release "
                    "toxics that never appear here. E3 measures reported releases, not all "
                    "releases, and a hex with no TRI facility nearby is not a hex with no "
                    "toxic emissions nearby."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "TRI quantities are self-reported annual estimates, most of them "
                    "derived from emission factors and mass balance rather than measured. "
                    "They are accounting figures, which is why section 8.1 reads E3 as how "
                    "much toxic material is released nearby rather than as an exposure."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "On-site air only, by design. TRI also reports releases to water and "
                    "land and transfers off site; scoring those against an air burden "
                    "indicator would be wrong, so they are not stored at all rather than "
                    "stored and hopefully filtered later."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "E3 weights each chemical by its EPA RSEI inhalation toxicity weight. "
                    "This adapter loads releases only; chemical_toxicity_weight is still "
                    "empty and no backlog ticket currently fills it. Until it is loaded, "
                    "E3 cannot be computed, and TRI chemicals RSEI has no weight for are "
                    "excluded from E3 by design while remaining visible in the drill-down."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="temporal",
                detail=(
                    "Several EPA environmental justice datasets and tools were withdrawn "
                    "from public hosting during 2025. Upstream availability is treated as "
                    "unreliable: every artifact records its URL, retrieval date and "
                    "checksum, and a night when Envirofacts is unreachable continues on the "
                    "last good snapshot with the recency term degraded rather than skipping."
                ),
                affects=("E3",),
                since=date(2025, 1, 1),
            ),
        )
