"""OpenAQ: measured daily PM2.5, and an honest map of where nothing is measured.

Feeds E4 and the `c_monitor` confidence term (methodology sections 8.1 and 12).
This is the only measured indicator in the set and by far the sparsest: Louisiana
has on the order of two dozen regulatory PM2.5 monitors against roughly 150,000
hexes, so most of the state has no measurement and, by section 8.1, gets none.
Never zero, never the state median, never the reading from the next parish.

That rule is the reason this adapter emits a per-hex record at all. E4 could be
interpolated at scoring time from the monitor table, but then the distinction
between "measured 6.2 µg/m³" and "nobody has ever measured here" would be
reconstructed rather than recorded, and section 11 is emphatic that the two are
different facts. `HexAirQuality` carries both: a `Measurement` that knows whether
it was observed, and the distance to the nearest monitor that `c_monitor` is
computed from and the detail panel displays.

**Two radii, and they do different jobs.** Within `INTERPOLATION_RADIUS_KM` a hex
gets an E4 value by inverse-distance weighting. Out to `COVERAGE_RADIUS_KM` it
gets no value but a real distance, because `min(1, 10 km / d_nearest)` still
varies out there and a hex 60 km from the nearest monitor is genuinely less well
characterised than one 12 km away. Past that the term has reached the 0.05 floor
section 12 applies to every confidence component, so a stored distance could no
longer change a score, and no row is written. `fetch` counts the hexes that fall
off that edge and publishes the count, because a count that climbs between runs
is the monitor network thinning and that should be visible in the manifest
rather than inferred from a map that quietly lost its confidence.

**The API needs a key and the shapes were read, not guessed.** OpenAQ v3 rejects
unauthenticated requests, so the request and response shapes here come from the
service's own OpenAPI document at https://api.openaq.org/openapi.json, retrieved
2026-09-11. Two details that document settles and intuition gets wrong: the daily
endpoint takes `date_from` and `date_to` while its hourly siblings take
`datetime_from` and `datetime_to`, and a location's readings hang off its
*sensors*, not off the location, so one physical monitor with two PM2.5
instruments returns two series.

**One location can hold several PM2.5 sensors.** `monitor_measurement` is keyed
by monitor, parameter and day, so two instruments at one site would collide on
the natural key and fail the run. `fetch` picks one series per location, the one
reporting most recently, and records the others in a note. Averaging two
instruments would be a methodology choice section 8.1 does not make.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import ClassVar
from urllib.parse import urlencode

import h3

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.metadata import Artifact, KnownGap, SourceSpec
from pipeline.policy import RateLimit, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord

# Methodology section 5. Every point in this project lands on resolution 8.
HEX_RESOLUTION = 8

OPENAQ = "https://api.openaq.org/v3"
LOCATIONS_URL = f"{OPENAQ}/locations"
SENSOR_DAYS_URL = f"{OPENAQ}/sensors/{{sensor_id}}/days"
LOCATION_URL = "https://explore.openaq.org/locations/{location_id}"

# The credential `fetch` asks the context for. Supplied to the nightly job as a
# repository secret; see .env.example.
API_KEY_CREDENTIAL = "openaq_api_key"
API_KEY_HEADER = "X-API-Key"

# OpenAQ's canonical id for PM2.5. The query filters on it and every record is
# re-checked against the parameter name, so a changed id cannot quietly load
# ozone into an indicator that says PM2.5.
PM25_PARAMETER_ID = 2
PM25 = "pm25"

# The published unit for pm25. Anything else is rejected rather than converted:
# guessing at a unit is how a measured indicator silently gains a factor of a
# thousand.
PM25_UNITS = frozenset({"µg/m³", "ug/m3", "µg/m3"})

PAGE_SIZE = 1000
MAX_PAGES = 10

# E4 is an annual mean. A trailing window rather than the last complete calendar
# year, because a nightly pipeline that spends January reporting on the year
# before last is publishing history, not air quality.
WINDOW_DAYS = 365

# Section 8.1. Beyond this a hex receives no E4 value at all.
INTERPOLATION_RADIUS_KM = 25.0

# Section 12. c_monitor is min(1, 10 km / d_nearest) floored at 0.05, so at
# 200 km the term is already at its floor and a further metre cannot move a
# score. Hexes beyond this get no row; `fetch` counts them.
COVERAGE_RADIUS_KM = 200.0

# Section 8.1 says inverse-distance for E4 and says inverse-square for E3, in
# the same paragraph. The difference is deliberate, so the exponent is 1 and
# changing it is a methodology revision under section 17, not a tuning knob.
IDW_POWER = 1.0

# Prevents a singularity when a monitor sits inside the hex it is weighting.
# The same floor section 8.1 puts on E3.
MIN_DISTANCE_KM = 0.25

# ---- the screening rules, applied in validate --------------------------
#
# Section 6 asks for a documented rule for faulty readings rather than a
# hand-tuned filter. Each of these is a statement about what is physically or
# procedurally impossible, not about what looks unusual, and each rejection is
# counted, sampled into the manifest and weighed against the partial-failure
# tolerance like any other.

# EPA's completeness rule for a valid daily mean: 18 of 24 hours. OpenAQ
# publishes the ratio directly, which also covers feeds that do not report
# hourly.
MIN_DAY_COMPLETENESS_PCT = 75.0

# And for a valid annual mean: 75% of the days in the window. A monitor below
# this still anchors c_monitor, because it exists and is being read, but its
# mean does not enter the interpolation.
MIN_VALID_DAYS = 274

# The US AQI scale for 24-hour PM2.5 ends at 500.4 µg/m³. A daily mean above it
# is an instrument fault, not the worst air ever recorded in Louisiana.
MAX_PM25_UGM3 = 500.0

# Values several feeds still use to mean "no data", which arithmetic would
# happily average.
SENTINEL_VALUES = frozenset({-999.0, -9999.0, -99.0, -1.0})

# A daily mean identical to at least this many neighbouring days is a stuck
# instrument. Ambient PM2.5 varies with weather every day; a fortnight of the
# same number to the reported precision does not happen.
STUCK_RUN_DAYS = 14

# Crude envelope with roughly a 10 km buffer, the same shape and the same
# reasoning as the ECHO adapter's. The authoritative grid is the one CS-007
# builds from the state boundary; this box is wider, so a few cells here fall
# outside it and simply never join.
PILOT_ENVELOPE: dict[str, tuple[float, float, float, float]] = {
    # south, north, west, east
    "LA": (28.83, 33.10, -94.14, -88.73),
}

EARTH_RADIUS_KM = 6371.0088

# Centre-to-centre spacing of resolution 8 cells, deliberately below the true
# average of 0.92 km so a ring count derived from it over-covers its radius.
# The exact haversine test does the real cutoff; this only sizes the search.
CELL_SPACING_KM = 0.85


# ---- normalized records ------------------------------------------------


class Monitor(NormalizedRecord):
    """One OpenAQ location, on the hex grid."""

    table: ClassVar[str] = "monitor"

    monitor_id: str
    openaq_sensor_id: str
    name: str | None
    parameter: str
    latitude: float
    longitude: float
    h3: str
    is_regulatory: bool
    first_seen_on: date | None
    last_seen_on: date | None
    openaq_url: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.monitor_id,)


class MonitorMeasurement(NormalizedRecord):
    """One monitor's daily mean for one day."""

    table: ClassVar[str] = "monitor_measurement"

    monitor_id: str
    parameter: str
    measured_on: date
    value: float
    unit: str
    observation_count: int

    def natural_key(self) -> tuple[str, ...]:
        return (self.monitor_id, self.parameter, self.measured_on.isoformat())


class HexAirQuality(NormalizedRecord):
    """What one hex knows about measured air quality, including nothing.

    A hex with no monitor within the interpolation radius carries
    `Measurement.absent()` and a real distance. That pair is the whole point of
    the record: the map can say "unmeasured, nearest sensor 46 km away" instead
    of colouring the hex as though it were clean.
    """

    table: ClassVar[str] = "hex_air_quality"

    h3: str
    parameter: str
    annual_mean: Measurement
    unit: str | None
    window_start: date
    window_end: date
    nearest_monitor_id: str
    nearest_monitor_km: float
    monitors_used: int
    day_count: int
    observation_count: int
    latest_measured_on: date | None

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3, self.parameter)


# ---- raw records -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonitorSite:
    """One OpenAQ location and the PM2.5 sensor this pull reads it through."""

    monitor_id: str
    sensor_id: str
    name: str | None
    latitude: float | None
    longitude: float | None
    unit: str
    is_regulatory: bool
    is_mobile: bool
    first_seen_on: date | None
    last_seen_on: date | None
    sensor_count: int


@dataclass(frozen=True, slots=True)
class DailyReading:
    """One daily mean, with everything the screening rules need to judge it."""

    measured_on: date | None
    value: float | None
    unit: str
    parameter: str
    observation_count: int
    completeness_pct: float | None
    flagged_upstream: bool
    in_stuck_run: bool


@dataclass(slots=True)
class Pooled:
    """One hex's running inverse-distance sum over the monitors that reach it."""

    weighted: float = 0.0
    weight: float = 0.0
    monitors: int = 0
    days: int = 0
    observations: int = 0
    latest: date | None = None

    def add(
        self, *, weight: float, mean: float, days: int, observations: int, latest: date | None
    ) -> None:
        self.weighted += weight * mean
        self.weight += weight
        self.monitors += 1
        self.days += days
        self.observations += observations
        if latest is not None and (self.latest is None or latest > self.latest):
            self.latest = latest

    def mean(self) -> float:
        return self.weighted / self.weight


@dataclass(frozen=True, slots=True)
class HexCoverage:
    """One hex's view of the monitor network. Computed in `fetch`, see `_assign`."""

    h3: str
    nearest_monitor_id: str
    nearest_km: float
    value: float | None
    monitors_used: int
    day_count: int
    observation_count: int
    latest_measured_on: date | None


@dataclass(frozen=True, slots=True)
class OpenAqRecord:
    """One raw record: a monitor, or one of its daily readings.

    Splitting the two is what lets a single bad reading be rejected and counted
    on its own, which is what section 6 asks for, while the monitor row is
    emitted exactly once and does not repeat its natural key.

    The monitor record also carries the hexes whose nearest monitor it is. Hex
    coverage is an aggregate over the whole network and cannot be derived from
    one raw record, so `fetch` computes the assignment and hands each hex to its
    owner; because every hex has exactly one nearest monitor, no key repeats.
    """

    site: MonitorSite
    reading: DailyReading | None = None
    hexes: tuple[HexCoverage, ...] = ()

    @property
    def is_monitor(self) -> bool:
        return self.reading is None


@dataclass(frozen=True, slots=True)
class MonitorWindow:
    """A monitor's readings for the window, after screening. Internal to `fetch`."""

    site: MonitorSite
    readings: tuple[DailyReading, ...]
    usable: tuple[DailyReading, ...]

    @property
    def reports(self) -> bool:
        """Has this monitor produced any usable reading in the window?

        Distance to a monitor that has gone silent is not evidence that a hex is
        well characterised, so only reporting monitors anchor `c_monitor`.
        """
        return len(self.usable) > 0

    @property
    def interpolates(self) -> bool:
        """Is this monitor's annual mean complete enough to enter E4?"""
        return len(self.usable) >= MIN_VALID_DAYS

    @property
    def annual_mean(self) -> float:
        return sum(r.value or 0.0 for r in self.usable) / len(self.usable)

    @property
    def observations(self) -> int:
        return sum(r.observation_count for r in self.usable)

    @property
    def latest(self) -> date | None:
        days = [r.measured_on for r in self.usable if r.measured_on is not None]
        return max(days) if days else None


# ---- the screening rules, as pure predicates ---------------------------
#
# Shared by `fetch` and `validate` on purpose. `fetch` needs them to know which
# readings may enter an annual mean before any record has been validated;
# `validate` applies the same predicates so every drop is counted. One function
# each, so the two can never disagree about what a bad reading is.


def site_fault(site: MonitorSite, pilot_state: str) -> tuple[str, str] | None:
    """Why this monitor cannot be used, as (reason, field). None if it can be."""
    if not site.monitor_id:
        return ("missing OpenAQ location id", "id")
    if not site.sensor_id:
        return ("no PM2.5 sensor at this location", "sensors")
    if site.latitude is None or site.longitude is None:
        return ("monitor has no coordinates", "coordinates")
    if not (-90.0 <= site.latitude <= 90.0 and -180.0 <= site.longitude <= 180.0):
        return ("coordinates outside the world", "coordinates")
    if site.is_mobile:
        # A mobile location's coordinates are wherever it last was. Pinning a
        # year of readings to that hex would attribute them to a neighbourhood
        # the instrument may have spent a fortnight in.
        return ("mobile monitor, not a fixed station", "isMobile")
    south, north, west, east = PILOT_ENVELOPE[pilot_state]
    if not (south <= site.latitude <= north and west <= site.longitude <= east):
        return (f"outside the {pilot_state} envelope", "coordinates")
    if site.unit not in PM25_UNITS:
        return (f"unrecognised unit {site.unit!r}", "units")
    return None


def reading_fault(reading: DailyReading, window: tuple[date, date]) -> tuple[str, str] | None:
    """Why this daily mean cannot be used, as (reason, field). None if it can be.

    The documented rule the ticket asks for, in one place. Every clause rejects
    something impossible rather than something merely unusual: a high day during
    a wildfire smoke episode is exactly the observation E4 exists to capture and
    must survive all of this.
    """
    if reading.parameter != PM25:
        return (f"parameter {reading.parameter!r} is not pm25", "parameter")
    if reading.measured_on is None:
        return ("unparseable measurement date", "period")
    if not (window[0] <= reading.measured_on <= window[1]):
        return ("reading outside the reporting window", "period")
    if reading.unit not in PM25_UNITS:
        return (f"unrecognised unit {reading.unit!r}", "units")
    if reading.value is None:
        # The day exists in the feed but carries no mean. An absence, and it is
        # stored as one by not being stored at all; `monitor_measurement.value`
        # is NOT NULL precisely so a missing day cannot become a zero.
        return ("no value reported for the day", "value")
    if reading.value in SENTINEL_VALUES:
        return ("sentinel no-data value", "value")
    if reading.value < 0.0:
        return ("negative concentration", "value")
    if reading.value > MAX_PM25_UGM3:
        return (f"above the {MAX_PM25_UGM3:.0f} µg/m³ instrument ceiling", "value")
    if reading.flagged_upstream:
        return ("flagged by the data provider", "flagInfo")
    if reading.completeness_pct is not None and reading.completeness_pct < MIN_DAY_COMPLETENESS_PCT:
        return (
            f"day built from under {MIN_DAY_COMPLETENESS_PCT:.0f}% of expected observations",
            "coverage",
        )
    if reading.observation_count <= 0:
        return ("no observations behind the daily mean", "coverage")
    if reading.in_stuck_run:
        return (f"identical value for {STUCK_RUN_DAYS} or more days, stuck sensor", "value")
    return None


def mark_stuck_runs(readings: Sequence[DailyReading]) -> tuple[DailyReading, ...]:
    """Flag every reading inside a run of identical values on consecutive days.

    Consecutive by calendar date, not by position, so a gap in the record breaks
    a run rather than joining the days either side of it.
    """
    ordered = sorted(readings, key=lambda r: r.measured_on or date.min)
    flagged = list(ordered)
    start = 0
    for index in range(1, len(ordered) + 1):
        ended = index == len(ordered)
        if not ended:
            previous, current = ordered[index - 1], ordered[index]
            same = (
                previous.value is not None
                and current.value == previous.value
                and previous.measured_on is not None
                and current.measured_on == previous.measured_on + timedelta(days=1)
            )
            if same:
                continue
        if index - start >= STUCK_RUN_DAYS:
            for position in range(start, index):
                flagged[position] = replace(flagged[position], in_stuck_run=True)
        start = index
    return tuple(flagged)


# ---- geometry ----------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_lat1, r_lat2 = radians(lat1), radians(lat2)
    d_lat = r_lat2 - r_lat1
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def envelope_cells(pilot_state: str) -> list[str]:
    """Every resolution 8 cell in the pilot envelope, once."""
    south, north, west, east = PILOT_ENVELOPE[pilot_state]
    box = h3.LatLngPoly([(south, west), (north, west), (north, east), (south, east)])
    return list(h3.polygon_to_cells(box, HEX_RESOLUTION))


def idw_weight(distance_km: float) -> float:
    return 1.0 / float(max(distance_km, MIN_DISTANCE_KM) ** IDW_POWER)


# ---- parsing -----------------------------------------------------------


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    return int(value) if isinstance(value, int | float) else 0


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _day(value: object, clock: str = "utc") -> date | None:
    """A `DatetimeObject` as a calendar day.

    A daily mean is a local-calendar-day construct, so a reading's date is read
    from the `local` side; a location's first and last activity is a instant, so
    those are read from `utc`.
    """
    stamp = _text(_mapping(value).get(clock))
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _url(base: str, params: Mapping[str, str]) -> str:
    """A fully-formed URL rather than a base plus params.

    `HttpFetcher` keys its snapshot store and its artifacts by the URL it is
    given, so two pages passed as params would overwrite each other's snapshot
    and a stale night would serve the same page for every request. Putting the
    query in the URL also makes the manifest show exactly which queries ran.
    """
    return f"{base}?{urlencode(sorted(params.items()))}"


@register
class OpenAqAdapter(SourceAdapter[OpenAqRecord]):
    """Measured daily PM2.5, per-hex interpolation, and per-hex monitor distance."""

    spec = SourceSpec(
        name="openaq",
        title="OpenAQ measured air quality (PM2.5)",
        homepage="https://docs.openaq.org/",
        cadence="daily",
        native_geography="point (monitor lat/lon)",
        provides=("E4",),
        licence="per-provider; OpenAQ aggregates, see the licence on each location",
    )

    # OpenAQ publishes a rate limit of 60 requests per minute for a free key,
    # and returns 429 above it. One per second sits inside that with room for
    # the burst the location pages need. Everything else about failure handling
    # is the runner's.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit(requests_per_second=1.0, burst=5),
    )

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[OpenAqRecord]:
        key = ctx.credential(API_KEY_CREDENTIAL)
        headers = {API_KEY_HEADER: key}
        window = self._window(ctx)
        artifacts = []
        notes = []

        locations, location_artifacts, multi_sensor = await self._locations(ctx, headers)
        artifacts.extend(location_artifacts)
        if not locations:
            raise PermanentSourceError(
                f"{LOCATIONS_URL}: no PM2.5 locations in the {ctx.pilot_state} envelope"
            )

        windows: list[MonitorWindow] = []
        for site in locations:
            if site_fault(site, ctx.pilot_state) is not None:
                # A year of readings from a monitor that cannot be used is a
                # request nobody needs. The monitor record still goes through
                # `validate`, so the rejection is counted once, on the thing
                # that is actually wrong.
                windows.append(MonitorWindow(site=site, readings=(), usable=()))
                continue
            readings, artifact = await self._readings(ctx, site, window, headers)
            artifacts.append(artifact)
            usable = tuple(r for r in readings if reading_fault(r, window) is None)
            windows.append(MonitorWindow(site=site, readings=readings, usable=usable))

        coverage, unreached = self._assign(windows, ctx.pilot_state)
        eligible = [w for w in windows if site_fault(w.site, ctx.pilot_state) is None]

        records: list[OpenAqRecord] = []
        for entry in windows:
            records.append(
                OpenAqRecord(site=entry.site, hexes=coverage.get(entry.site.monitor_id, ()))
            )
            records.extend(OpenAqRecord(site=entry.site, reading=r) for r in entry.readings)

        reporting = [w for w in eligible if w.reports]
        interpolating = [w for w in eligible if w.interpolates]
        notes.append(
            f"{len(locations)} PM2.5 locations, {len(eligible)} usable, "
            f"{len(reporting)} reporting in the window, "
            f"{len(interpolating)} complete enough for the annual mean"
        )
        notes.append(
            f"window {window[0].isoformat()} to {window[1].isoformat()}, "
            f"{sum(len(w.readings) for w in windows)} daily records"
        )
        valued = sum(1 for hexes in coverage.values() for h in hexes if h.value is not None)
        notes.append(
            f"{sum(len(h) for h in coverage.values())} hexes carry a monitor distance, "
            f"{valued} of them an E4 value"
        )
        if multi_sensor:
            notes.append(
                f"{len(multi_sensor)} locations hold more than one PM2.5 sensor; the most "
                f"recently reporting one was read: {', '.join(sorted(multi_sensor))}"
            )

        return FetchResult(
            records=tuple(records),
            # The last day the data describes, not the night it was downloaded.
            # Section 12 computes recency from this.
            vintage=f"daily/{window[1].isoformat()}",
            artifacts=artifacts,
            known_gaps=self._pull_gaps(eligible, unreached, window),
            notes=notes,
        )

    @staticmethod
    def _window(ctx: RunContext) -> tuple[date, date]:
        """The trailing year ending with the last complete day."""
        end = ctx.now.date() - timedelta(days=1)
        return (end - timedelta(days=WINDOW_DAYS - 1), end)

    async def _locations(
        self, ctx: RunContext, headers: Mapping[str, str]
    ) -> tuple[list[MonitorSite], list[Artifact], list[str]]:
        """Every PM2.5 location in the pilot envelope, one sensor each."""
        south, north, west, east = PILOT_ENVELOPE[ctx.pilot_state]
        artifacts = []
        sites: list[MonitorSite] = []
        multi_sensor: list[str] = []

        for page in range(1, MAX_PAGES + 1):
            url = _url(
                LOCATIONS_URL,
                {
                    "bbox": f"{west},{south},{east},{north}",
                    "parameters_id": str(PM25_PARAMETER_ID),
                    "limit": str(PAGE_SIZE),
                    "page": str(page),
                },
            )
            download = await ctx.http.get(url, headers=headers)
            artifacts.append(download.artifact)
            batch = self._results(download.content, url)
            for entry in batch:
                site = self._site(_mapping(entry))
                if site is None:
                    continue
                if site.sensor_count > 1:
                    multi_sensor.append(site.monitor_id)
                sites.append(site)
            if len(batch) < PAGE_SIZE:
                break

        sites.sort(key=lambda s: s.monitor_id)
        return sites, artifacts, multi_sensor

    @staticmethod
    def _results(payload: bytes, url: str) -> list[object]:
        try:
            document = json.loads(payload)
        except ValueError as exc:
            raise PermanentSourceError(f"{url}: response was not JSON ({exc})") from None
        if not isinstance(document, dict):
            raise PermanentSourceError(f"{url}: response was not an object")
        results = document.get("results")
        if not isinstance(results, list):
            # v3 answers every successful query with a results array. Its
            # absence is a reshaped API, not an empty state.
            raise PermanentSourceError(f"{url}: no results array")
        return results

    @staticmethod
    def _site(entry: Mapping[str, object]) -> MonitorSite | None:
        """One location, reduced to the PM2.5 sensor this pull will read.

        Returns None only for a location with no PM2.5 sensor at all, which the
        query should already have excluded; a location that is unusable for any
        other reason is kept so `validate` can reject it and the loss is counted.
        """
        location_id = _count(entry.get("id"))
        if not location_id:
            return None

        sensors = entry.get("sensors")
        candidates = [
            sensor
            for sensor in (sensors if isinstance(sensors, list) else [])
            if isinstance(sensor, dict)
            and _text(_mapping(sensor.get("parameter")).get("name")) == PM25
        ]
        if not candidates:
            return None
        # Most recently reporting wins, lowest sensor id breaks a tie, so the
        # choice is the same on every run. See the module docstring.
        chosen = min(
            candidates,
            key=lambda s: (
                -(_day(s.get("datetimeLast")) or date.min).toordinal(),
                _count(s.get("id")),
            ),
        )

        coordinates = _mapping(entry.get("coordinates"))
        return MonitorSite(
            monitor_id=str(location_id),
            sensor_id=str(_count(chosen.get("id"))),
            name=_text(entry.get("name")) or None,
            latitude=_number(coordinates.get("latitude")),
            longitude=_number(coordinates.get("longitude")),
            unit=_text(_mapping(chosen.get("parameter")).get("units")),
            # OpenAQ's own distinction between a reference-grade monitor and a
            # low-cost sensor. The schema keeps both but E4 says which it used.
            is_regulatory=bool(entry.get("isMonitor")),
            is_mobile=bool(entry.get("isMobile")),
            first_seen_on=_day(entry.get("datetimeFirst")),
            last_seen_on=_day(entry.get("datetimeLast")),
            sensor_count=len(candidates),
        )

    async def _readings(
        self,
        ctx: RunContext,
        site: MonitorSite,
        window: tuple[date, date],
        headers: Mapping[str, str],
    ) -> tuple[tuple[DailyReading, ...], Artifact]:
        """One sensor's daily means for the window. One page covers a year."""
        url = _url(
            SENSOR_DAYS_URL.format(sensor_id=site.sensor_id),
            {
                "date_from": window[0].isoformat(),
                "date_to": window[1].isoformat(),
                "limit": str(WINDOW_DAYS + 1),
                "page": "1",
            },
        )
        download = await ctx.http.get(url, headers=headers)
        readings = [
            self._reading(_mapping(entry)) for entry in self._results(download.content, url)
        ]
        return mark_stuck_runs(readings), download.artifact

    @staticmethod
    def _reading(entry: Mapping[str, object]) -> DailyReading:
        parameter = _mapping(entry.get("parameter"))
        coverage = _mapping(entry.get("coverage"))
        period = _mapping(entry.get("period"))
        return DailyReading(
            # The day the mean describes is the start of its period, not the
            # instant the period closed.
            measured_on=_day(period.get("datetimeFrom")),
            value=_number(entry.get("value")),
            unit=_text(parameter.get("units")),
            parameter=_text(parameter.get("name")),
            observation_count=_count(coverage.get("observedCount")),
            completeness_pct=_number(coverage.get("percentComplete")),
            flagged_upstream=bool(_mapping(entry.get("flagInfo")).get("hasFlags")),
            in_stuck_run=False,
        )

    # ---- coverage ------------------------------------------------------

    def _assign(
        self, windows: Sequence[MonitorWindow], pilot_state: str
    ) -> tuple[dict[str, tuple[HexCoverage, ...]], int]:
        """Give every hex in the envelope its nearest monitor, and E4 where it has one.

        Runs in `fetch` rather than `normalize` for the reason ECHO's coordinate
        check does: a hex's nearest monitor depends on the whole network, so it
        cannot be derived from one raw record, and the counts it produces have to
        reach the manifest before the first record is normalized. It screens
        monitors with the same `site_fault` predicate `validate` uses, so a
        monitor that will be rejected never owns a hex.

        Returns the assignment keyed by monitor, and the number of envelope
        hexes that had no monitor within `COVERAGE_RADIUS_KM`.
        """
        usable = [w for w in windows if site_fault(w.site, pilot_state) is None]
        anchors = [w for w in usable if w.reports]
        sources = [w for w in usable if w.interpolates]

        cells = envelope_cells(pilot_state)
        if not anchors:
            return ({}, len(cells))

        assigned: dict[str, list[HexCoverage]] = {}
        interpolated = self._interpolate(sources)
        unreached = 0

        # A local equirectangular projection over a hundred thousand cells, to
        # narrow a couple of dozen monitors to the handful that could be the
        # nearest. It decides nothing on its own: every candidate it keeps is
        # then measured with the haversine, and the winner and the stored
        # distance both come from that. The slack is far wider than the
        # projection's error over a single state, so a near-tie cannot be
        # resolved by the approximation.
        south, north, _, _ = PILOT_ENVELOPE[pilot_state]
        kx, ky = 111.32 * cos(radians((south + north) / 2)), 110.57
        points = [
            (w.site.longitude * kx, w.site.latitude * ky, w.site)
            for w in anchors
            if w.site.latitude is not None and w.site.longitude is not None
        ]
        slack = 1.05**2

        for cell in cells:
            lat, lon = h3.cell_to_latlng(cell)
            x, y = lon * kx, lat * ky
            planar = [((x - px) ** 2 + (y - py) ** 2, site) for px, py, site in points]
            closest = min(squared for squared, _ in planar)
            measured = [
                (haversine_km(lat, lon, site.latitude or 0.0, site.longitude or 0.0), site)
                for squared, site in planar
                if squared <= closest * slack
            ]
            # Lowest distance wins; the monitor id breaks an exact tie, so two
            # equidistant monitors resolve the same way on every run.
            distance, winner = min(measured, key=lambda m: (m[0], m[1].monitor_id))
            if distance > COVERAGE_RADIUS_KM:
                unreached += 1
                continue

            pooled = interpolated.get(cell)
            assigned.setdefault(winner.monitor_id, []).append(
                HexCoverage(
                    h3=cell,
                    nearest_monitor_id=winner.monitor_id,
                    nearest_km=distance,
                    value=pooled.mean() if pooled is not None else None,
                    monitors_used=pooled.monitors if pooled is not None else 0,
                    day_count=pooled.days if pooled is not None else 0,
                    observation_count=pooled.observations if pooled is not None else 0,
                    latest_measured_on=pooled.latest if pooled is not None else None,
                )
            )

        return ({k: tuple(v) for k, v in assigned.items()}, unreached)

    @staticmethod
    def _interpolate(sources: Sequence[MonitorWindow]) -> dict[str, "Pooled"]:
        """E4 for the hexes that have one, by inverse-distance weighting.

        Only the cells within `INTERPOLATION_RADIUS_KM` of a monitor are visited,
        a few thousand per monitor rather than the whole envelope. Hexes this
        never touches are exactly the hexes section 8.1 says get no value.
        """
        rings = int(INTERPOLATION_RADIUS_KM / CELL_SPACING_KM) + 1
        pooled: dict[str, Pooled] = {}

        for source in sources:
            latitude, longitude = source.site.latitude, source.site.longitude
            if latitude is None or longitude is None:
                continue
            mean, observations = source.annual_mean, source.observations
            days, latest = len(source.usable), source.latest
            origin = h3.latlng_to_cell(latitude, longitude, HEX_RESOLUTION)
            for cell in h3.grid_disk(origin, rings):
                lat, lon = h3.cell_to_latlng(cell)
                distance = haversine_km(lat, lon, latitude, longitude)
                if distance > INTERPOLATION_RADIUS_KM:
                    continue
                pooled.setdefault(cell, Pooled()).add(
                    weight=idw_weight(distance),
                    mean=mean,
                    days=days,
                    observations=observations,
                    latest=latest,
                )

        return {cell: entry for cell, entry in pooled.items() if entry.weight > 0.0}

    # ---- validate ------------------------------------------------------

    def validate(self, record: OpenAqRecord, ctx: RunContext) -> None:
        fault = site_fault(record.site, ctx.pilot_state)
        if fault is not None:
            raise RecordRejected(fault[0], field=fault[1], record_id=record.site.monitor_id)
        if record.reading is None:
            return

        reading_id = f"{record.site.monitor_id}:{record.reading.measured_on}"
        fault = reading_fault(record.reading, self._window(ctx))
        if fault is not None:
            raise RecordRejected(fault[0], field=fault[1], record_id=reading_id)

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: OpenAqRecord, ctx: RunContext) -> Iterator[NormalizedRecord]:
        if record.reading is not None:
            yield self._measurement(record.site, record.reading)
            return
        yield self._monitor(record.site)
        yield from self._hexes(record.hexes, record.site, self._window(ctx))

    @staticmethod
    def _monitor(site: MonitorSite) -> Monitor:
        # site_fault has already established both coordinates are present.
        latitude, longitude = site.latitude or 0.0, site.longitude or 0.0
        return Monitor(
            monitor_id=site.monitor_id,
            openaq_sensor_id=site.sensor_id,
            name=site.name,
            parameter=PM25,
            latitude=latitude,
            longitude=longitude,
            h3=str(h3.latlng_to_cell(latitude, longitude, HEX_RESOLUTION)),
            is_regulatory=site.is_regulatory,
            first_seen_on=site.first_seen_on,
            last_seen_on=site.last_seen_on,
            openaq_url=LOCATION_URL.format(location_id=site.monitor_id),
        )

    @staticmethod
    def _measurement(site: MonitorSite, reading: DailyReading) -> MonitorMeasurement:
        # reading_fault has already established the date, the value and the unit.
        return MonitorMeasurement(
            monitor_id=site.monitor_id,
            parameter=PM25,
            measured_on=reading.measured_on or date.min,
            value=reading.value or 0.0,
            unit=reading.unit,
            observation_count=reading.observation_count,
        )

    @staticmethod
    def _hexes(
        hexes: Sequence[HexCoverage], site: MonitorSite, window: tuple[date, date]
    ) -> Iterator[HexAirQuality]:
        for cell in hexes:
            # The rule the whole adapter exists for. A hex with no monitor
            # within the interpolation radius is absent, not zero and not its
            # neighbour's reading, and it still carries the distance that
            # c_monitor and the detail panel are computed from.
            value = Measurement.of(cell.value) if cell.value is not None else Measurement.absent()
            yield HexAirQuality(
                h3=cell.h3,
                parameter=PM25,
                annual_mean=value,
                unit=site.unit if cell.value is not None else None,
                window_start=window[0],
                window_end=window[1],
                nearest_monitor_id=cell.nearest_monitor_id,
                nearest_monitor_km=cell.nearest_km,
                monitors_used=cell.monitors_used,
                day_count=cell.day_count,
                observation_count=cell.observation_count,
                latest_measured_on=cell.latest_measured_on,
            )

    # ---- gaps ----------------------------------------------------------

    @staticmethod
    def _pull_gaps(
        windows: Sequence[MonitorWindow], unreached: int, window: tuple[date, date]
    ) -> tuple[KnownGap, ...]:
        """What this pull found out about its own coverage.

        `windows` is the usable monitors only. A monitor rejected for being
        mobile or out of state is not a monitor that has gone quiet, and
        counting it as one would misdescribe the network.
        """
        gaps: list[KnownGap] = []
        silent = [w.site.monitor_id for w in windows if not w.reports]
        incomplete = [w.site.monitor_id for w in windows if w.reports and not w.interpolates]

        if silent:
            gaps.append(
                KnownGap(
                    scope="temporal",
                    detail=(
                        f"{len(silent)} of {len(windows)} PM2.5 locations produced no usable "
                        f"reading between {window[0].isoformat()} and {window[1].isoformat()}: "
                        f"{', '.join(sorted(silent))}. They do not anchor c_monitor, because "
                        f"distance to a monitor that has gone silent is not evidence that a "
                        f"hex is well characterised."
                    ),
                    affects=("E4",),
                    since=window[0],
                )
            )
        if incomplete:
            gaps.append(
                KnownGap(
                    scope="temporal",
                    detail=(
                        f"{len(incomplete)} of {len(windows)} PM2.5 locations reported fewer "
                        f"than {MIN_VALID_DAYS} usable days of the {WINDOW_DAYS}-day window, "
                        f"below the 75% completeness EPA requires of an annual mean: "
                        f"{', '.join(sorted(incomplete))}. They anchor c_monitor but their "
                        f"mean does not enter E4."
                    ),
                    affects=("E4",),
                )
            )
        if unreached:
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{unreached} hexes in the pilot envelope have no reporting PM2.5 "
                        f"monitor within {COVERAGE_RADIUS_KM:.0f} km and carry no row at all; "
                        f"c_monitor takes its 0.05 floor there. The envelope is a bounding box "
                        f"wider than the state, so a count of a few thousand is the offshore "
                        f"and out-of-state overhang and describes cells the pilot grid does "
                        f"not contain. A count that climbs between runs is the monitor network "
                        f"thinning, and is the thing this number exists to make visible."
                    ),
                    affects=("E4",),
                )
            )
        return tuple(gaps)

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="geographic",
                detail=(
                    "Louisiana holds on the order of two dozen PM2.5 monitors against "
                    "roughly 150,000 hexes. E4 is present for a minority of them and, per "
                    "methodology section 11, the Exposures group is usually carried by E1 "
                    "through E3. A hex beyond 25 km of a monitor is recorded as unmeasured, "
                    "never as zero and never as the state median: an unmonitored parish "
                    "must not be rewarded for having no sensor."
                ),
                affects=("E4",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "Inverse-distance weighting over a 25 km radius is an interpolation, "
                    "not a dispersion model. It ignores wind, terrain and the fact that "
                    "PM2.5 near an industrial corridor is not well described by a monitor "
                    "sited 20 km away in a different airshed. The hexes it fills are "
                    "exactly the hexes where a reader is most entitled to check the "
                    "distance, which is why that distance is stored and displayed."
                ),
                affects=("E4",),
            ),
            KnownGap(
                scope="population",
                detail=(
                    "Monitor siting is not random. Regulatory PM2.5 monitors are placed "
                    "where the Clean Air Act requires them, which favours population "
                    "centres and known problem areas, so the parts of Louisiana E4 covers "
                    "are systematically unlike the parts it does not. Reading a missing E4 "
                    "as good air would invert the relationship this project measures."
                ),
                affects=("E4",),
            ),
            KnownGap(
                scope="attribute",
                detail=(
                    "OpenAQ aggregates reference-grade regulatory monitors and low-cost "
                    "sensors. Both are held; monitor.is_regulatory says which, and a "
                    "low-cost sensor is not interchangeable with a federal equivalent "
                    "method instrument at the same coordinates."
                ),
                affects=("E4",),
            ),
        )
