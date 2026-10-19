"""EPA SEMS: Superfund sites with an NPL status, the points behind F5.

Feeds F5, contaminated land proximity (methodology section 8.2, v0.4.0):

    F5(h) = sum_s  1 / max(d_{h,s}, 250 m)^2

over sites `s` within 10 km that are on the Final National Priorities List or
proposed for it. The decay is the one F1 to F4 use, applied in the scoring
query through `facility_decay_weight`, so this adapter only has to say where
each site is and what its NPL status is.

**The source is Envirofacts' copy of the SEMS site table.** EPA's Superfund
Enterprise Management System is the system of record for the NPL, and
Envirofacts publishes its site table as a filterable JSON service. One request
per state returns every site EPA tracks there, about 800 for Louisiana, of
which roughly 35 carry an NPL status. This adapter stores those 35, all five
statuses, because the hex panel needs to say why a nearby deleted site does not
count; which statuses count is section 8.2's decision, made in the scoring
query.

**SEMS is continuously updated, so the vintage is the day it was read.** There
is no release. A site moves from proposed to final, or is deleted, on the day
EPA publishes the Federal Register notice, so the honest vintage is the pull
date, and `c_recency` treats it as current, which it is.

**A site is a point, though many cover hundreds of acres.** EPA records one
primary coordinate per site. Section 8.2 says so, and `known_gaps` repeats it.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import h3

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.geo.assignment import HEX_RESOLUTION
from pipeline.metadata import KnownGap, SourceSpec
from pipeline.quality.checks import (
    Bounds,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
)
from pipeline.records import NormalizedRecord

SITE_URL = "https://data.epa.gov/efservice/SEMS.ENVIROFACTS_SITE/fk_ref_state_code/equals/{state}/JSON"

#: SEMS's NPL status codes, all of which are stored. `N`, not on the NPL, is
#: the other ~95% of the table and is not.
NPL_STATUSES: dict[str, str] = {
    "F": "Currently on the Final NPL",
    "P": "Proposed for NPL",
    "D": "Deleted from the Final NPL",
    "R": "Removed from Proposed NPL",
    "A": "Site is Part of NPL Site",
}

#: The statuses section 8.2 counts in F5. Kept here as well as in the scoring
#: query so the adapter's notes can say how many sites F5 will see.
COUNTED_STATUSES = frozenset({"F", "P"})

#: A loose box around each state, to catch a coordinate with its sign dropped
#: or its digits transposed rather than to check a boundary. The grid does the
#: real geography at scoring time.
STATE_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    # south, north, west, east
    "LA": (28.8, 33.1, -94.1, -88.7),
}


class CleanupSite(NormalizedRecord):
    """One Superfund site with an NPL status."""

    table: ClassVar[str] = "cleanup_site"

    site_id: str
    epa_id: str | None
    name: str
    city: str | None
    county_fips: str | None
    state: str
    npl_status_code: str
    npl_status_name: str
    is_federal: bool
    latitude: float
    longitude: float
    h3: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.site_id,)


@dataclass(frozen=True, slots=True)
class SemsSite:
    """One row of the Envirofacts response, as read."""

    site_id: str
    epa_id: str | None
    name: str
    city: str | None
    county_fips: str | None
    state: str
    npl_status_code: str
    npl_status_name: str
    federal_facility_ind: str | None
    latitude: float | None
    longitude: float | None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coordinate(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return float("nan")


def parse_sites(payload: Any, url: str) -> tuple[SemsSite, ...]:
    """The rows of one state's response that carry an NPL status."""
    if not isinstance(payload, list):
        # Envirofacts answers a malformed query with `{"error": ...}` and a 200.
        raise PermanentSourceError(f"{url}: expected a list of sites, got {str(payload)[:200]}")
    sites = []
    for row in payload:
        code = _text(row.get("npl_status_code"))
        if code is None or code == "N":
            continue
        sites.append(
            SemsSite(
                site_id=_text(row.get("site_id")) or "",
                epa_id=_text(row.get("epa_id")),
                name=_text(row.get("name")) or "",
                city=_text(row.get("city_name")),
                county_fips=_text(row.get("fips_code")),
                state=_text(row.get("fk_ref_state_code")) or "",
                npl_status_code=code,
                npl_status_name=_text(row.get("npl_status_name")) or "",
                federal_facility_ind=_text(row.get("federal_facility_ind")),
                latitude=_coordinate(row.get("primary_latitude_decimal_val")),
                longitude=_coordinate(row.get("primary_longitude_decimal_val")),
            )
        )
    return tuple(sites)


@register
class EpaSemsAdapter(SourceAdapter[SemsSite]):
    """Superfund sites with an NPL status for the pilot state."""

    spec = SourceSpec(
        name="epa_sems",
        title="EPA Superfund Enterprise Management System (SEMS), NPL sites",
        homepage="https://www.epa.gov/superfund/search-superfund-sites-where-you-live",
        cadence="continuous; status changes on Federal Register publication",
        native_geography="point (one primary coordinate per site)",
        provides=("F5",),
    )

    # The default policy stands: one request a night to Envirofacts.

    expectations: ClassVar[SourceExpectations | None] = SourceExpectations(
        source="epa_sems",
        tables=(
            TableExpectations(
                table="cleanup_site",
                # Louisiana had 35 sites with an NPL status on 2026-10-19. The
                # list moves by a site or two a year, so the bounds catch a
                # filter that stopped matching or one that let `N` sites in.
                rows=RowCount(15, 80, note="35 Louisiana sites with an NPL status, 2026-10-19."),
                null_rates=(
                    NullRate("site_id", 0.0),
                    NullRate("name", 0.0),
                    NullRate("npl_status_code", 0.0),
                    NullRate("h3", 0.0),
                ),
                bounds=(
                    Bounds("latitude", low=28.8, high=33.1, note="Louisiana, loosely."),
                    Bounds("longitude", low=-94.1, high=-88.7, note="Louisiana, loosely."),
                ),
            ),
        ),
    )

    def __init__(self) -> None:
        self._pulled_on = ""

    async def fetch(self, ctx: RunContext) -> FetchResult[SemsSite]:
        state = ctx.pilot_state
        if state not in STATE_BOUNDS:
            raise PermanentSourceError(f"no coordinate bounds known for pilot state {state!r}")
        url = SITE_URL.format(state=state)
        download = await ctx.http.get(url)
        try:
            payload = json.loads(download.content)
        except ValueError as exc:
            raise PermanentSourceError(f"{url}: not JSON ({exc})") from None
        sites = parse_sites(payload, url)

        pulled_on = ctx.now.date().isoformat()
        counted = sum(1 for s in sites if s.npl_status_code in COUNTED_STATUSES)
        return FetchResult(
            records=sites,
            # No release exists; see the module docstring. The date makes
            # `_vintage_end` the pull date.
            vintage=f"sems/{pulled_on}",
            artifacts=[download.artifact],
            notes=(
                f"{len(sites)} {state} sites with an NPL status, "
                f"{counted} final or proposed and counted by F5",
            ),
        )

    def validate(self, record: SemsSite, ctx: RunContext) -> None:
        if not record.site_id:
            raise RecordRejected("missing site id", field="site_id")
        if record.npl_status_code not in NPL_STATUSES:
            raise RecordRejected(
                f"unknown NPL status {record.npl_status_code!r}",
                field="npl_status_code",
                record_id=record.site_id,
            )
        if record.state != ctx.pilot_state:
            raise RecordRejected(
                f"site is in {record.state!r}, not the pilot state",
                field="fk_ref_state_code",
                record_id=record.site_id,
            )
        if record.latitude is None or record.longitude is None:
            # Never a point at the origin, and never dropped quietly: a missing
            # coordinate is a rejection the runner counts against tolerance.
            raise RecordRejected("no coordinates", field="latitude", record_id=record.site_id)
        south, north, west, east = STATE_BOUNDS[ctx.pilot_state]
        if not (south <= record.latitude <= north and west <= record.longitude <= east):
            raise RecordRejected(
                f"coordinates {record.latitude}, {record.longitude} outside the pilot state",
                field="latitude",
                record_id=record.site_id,
            )

    def normalize(self, record: SemsSite, ctx: RunContext) -> Iterator[NormalizedRecord]:
        assert record.latitude is not None and record.longitude is not None  # validated
        yield CleanupSite(
            site_id=record.site_id,
            epa_id=record.epa_id,
            name=record.name,
            city=record.city,
            county_fips=record.county_fips,
            state=record.state,
            npl_status_code=record.npl_status_code,
            npl_status_name=record.npl_status_name or NPL_STATUSES[record.npl_status_code],
            is_federal=record.federal_facility_ind == "Y",
            latitude=record.latitude,
            longitude=record.longitude,
            h3=str(h3.latlng_to_cell(record.latitude, record.longitude, HEX_RESOLUTION)),
        )

    def known_gaps(self, ctx: RunContext) -> Sequence[KnownGap]:
        return (
            KnownGap(
                scope="methodological",
                detail=(
                    "A Superfund site is stored as EPA's single primary coordinate, although "
                    "many cover hundreds of acres. F5 decays from that point, so a large "
                    "site's far edge is treated as farther away than it is."
                ),
                affects=("F5",),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "Only sites with an NPL status are loaded, and F5 counts final and "
                    "proposed ones. Non-NPL Superfund sites, state cleanup sites and "
                    "brownfields are not represented, so soil and groundwater burden is "
                    "still understated (methodology section 16)."
                ),
                affects=("F5",),
            ),
        )
