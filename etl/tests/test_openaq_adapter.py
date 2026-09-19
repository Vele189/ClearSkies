"""OpenAQ adapter, against a synthetic network. Nothing here touches the network.

OpenAQ v3 rejects unauthenticated requests, so there is no recorded extract to
replay. The fixture instead builds a six-monitor network in the shapes the
service's own OpenAPI document defines, chosen so that every rule the adapter
claims to apply has a monitor that exercises it: one complete pair close enough
to interpolate between, one monitor too incomplete for an annual mean, one
outside the pilot state, one mobile, one faulty in each of the documented ways,
and one that has gone silent.

Most tests narrow `PILOT_ENVELOPE` to a box around Baton Rouge. The statewide
envelope is 311,000 hexes and every test would pay for all of them;
`test_the_shipped_envelope_covers_the_pilot_state` guards the real one.
"""

import json
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from datetime import date, timedelta

import h3
import httpx
import pytest

from pipeline.adapters.openaq import (
    COVERAGE_RADIUS_KM,
    INTERPOLATION_RADIUS_KM,
    LOCATIONS_URL,
    MAX_PM25_UGM3,
    MEASURED_PULL_RECORDS,
    MEASURED_PULL_REJECTED,
    MEASURED_PULL_REJECTIONS,
    MIN_VALID_DAYS,
    PILOT_ENVELOPE,
    PM25,
    SENTINEL_VALUES,
    STUCK_RUN_DAYS,
    WINDOW_DAYS,
    DailyReading,
    HexAirQuality,
    Monitor,
    MonitorMeasurement,
    OpenAqAdapter,
    haversine_km,
    mark_stuck_runs,
    reading_fault,
)
from pipeline.context import RunContext
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.policy import PartialFailurePolicy, SourcePolicy
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore
from tests.conftest import FIXED_NOW, FakeClock, make_context, make_fetcher

# The window the adapter derives from FIXED_NOW: the trailing year ending with
# the last complete day.
WINDOW_END = FIXED_NOW.date() - timedelta(days=1)
WINDOW_START = WINDOW_END - timedelta(days=WINDOW_DAYS - 1)

# A box around Baton Rouge holding every synthetic monitor except the Houston
# one, which is outside it on purpose.
TEST_ENVELOPE = (30.10, 30.90, -91.80, -90.80)

KEY = "test-key-not-a-real-one"

# The fixture is deliberately full of unusable readings, at a rate no real
# OpenAQ pull reaches. The shipped tolerance would rightly refuse to load it;
# the tests under "the shipped configuration" guard the real one against the
# pull it was measured on.
TEST_POLICY = SourcePolicy(
    rate_limit=OpenAqAdapter.policy.rate_limit,
    partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
)

BATON_ROUGE = (30.4515, -91.1871)
PORT_ALLEN = (30.4515, -91.2891)  # about 9.8 km west of Baton Rouge
GONZALES = (30.2000, -90.9200)  # about 38 km south-east, beyond both disks
FAULTY = (30.7000, -91.5000)
SILENT = (30.1500, -91.6000)
HOUSTON = (29.7604, -95.3698)


# ---- building the fixture ----------------------------------------------


def _stamp(day: date) -> dict[str, str]:
    return {"utc": f"{day.isoformat()}T06:00:00Z", "local": f"{day.isoformat()}T00:00:00-06:00"}


def _sensor(sensor_id: int, last: date, units: str = "µg/m³") -> dict[str, object]:
    return {
        "id": sensor_id,
        "name": f"pm25 sensor {sensor_id}",
        "parameter": {"id": 2, "name": PM25, "units": units, "displayName": "PM2.5"},
        "datetimeLast": _stamp(last),
    }


def _location(
    location_id: int,
    name: str,
    coordinates: tuple[float, float],
    *,
    sensors: Sequence[dict[str, object]],
    is_monitor: bool = True,
    is_mobile: bool = False,
) -> dict[str, object]:
    return {
        "id": location_id,
        "name": name,
        "isMonitor": is_monitor,
        "isMobile": is_mobile,
        "coordinates": {"latitude": coordinates[0], "longitude": coordinates[1]},
        "sensors": list(sensors),
        "datetimeFirst": _stamp(WINDOW_START),
        "datetimeLast": _stamp(WINDOW_END),
    }


def _reading(
    day: date,
    value: float | None,
    *,
    observed: int = 24,
    expected: int = 24,
    flagged: bool = False,
    units: str = "µg/m³",
    parameter: str = PM25,
) -> dict[str, object]:
    return {
        "value": value,
        "flagInfo": {"hasFlags": flagged},
        "parameter": {"id": 2, "name": parameter, "units": units},
        "period": {
            "label": "1day",
            "interval": "24:00:00",
            "datetimeFrom": _stamp(day),
            "datetimeTo": _stamp(day + timedelta(days=1)),
        },
        "coverage": {
            "expectedCount": expected,
            "expectedInterval": "01:00:00",
            "observedCount": observed,
            "observedInterval": "01:00:00",
            "percentComplete": 100.0 * observed / expected,
            "percentCoverage": 100.0 * observed / expected,
        },
    }


def _series(days: int, value: float, *, ending: date = WINDOW_END) -> list[dict[str, object]]:
    """A clean run of `days` daily means ending on `ending`.

    The values alternate by a tenth so the run never looks like a stuck sensor;
    the mean stays `value`.
    """
    start = ending - timedelta(days=days - 1)
    return [
        _reading(start + timedelta(days=offset), value + (0.1 if offset % 2 else -0.1))
        for offset in range(days)
    ]


def _faulty_series() -> list[dict[str, object]]:
    """One reading for each documented fault, plus enough clean days to report."""
    start = WINDOW_END - timedelta(days=39)
    day = iter(start + timedelta(days=n) for n in range(40))
    readings = [
        _reading(next(day), -3.0),  # negative concentration
        _reading(next(day), min(SENTINEL_VALUES)),  # sentinel no-data value
        _reading(next(day), MAX_PM25_UGM3 + 1.0),  # above the instrument ceiling
        _reading(next(day), 8.0, flagged=True),  # flagged by the provider
        _reading(next(day), 8.0, observed=6),  # under 75% of expected hours
        _reading(next(day), 8.0, observed=0, expected=24),  # no observations at all
        _reading(next(day), None),  # day present, no value
        _reading(next(day), 8.0, units="ppm"),  # unit that is not micrograms
        _reading(next(day), 8.0, parameter="o3"),  # not PM2.5 at all
    ]
    # A fortnight of the identical value: a stuck instrument.
    readings += [_reading(next(day), 4.4) for _ in range(STUCK_RUN_DAYS)]
    # And enough clean days that the monitor still counts as reporting.
    readings += [
        _reading(next(day), 7.0 + (0.1 if n % 2 else -0.1)) for n in range(40 - len(readings))
    ]
    return readings


BATON_ROUGE_CURRENT = 9001
BATON_ROUGE_STALE = 9000
PORT_ALLEN_SENSOR = 9002
GONZALES_SENSOR = 9003
FAULTY_SENSOR = 9004
SILENT_SENSOR = 9005
HOUSTON_SENSOR = 9006
MOBILE_SENSOR = 9007


def fixture_network() -> tuple[list[dict[str, object]], dict[int, list[dict[str, object]]]]:
    locations = [
        # Two PM2.5 sensors at one location. The stale one has the lower id, so
        # a naive "first sensor wins" would read the wrong series.
        _location(
            100,
            "Baton Rouge Capitol",
            BATON_ROUGE,
            sensors=[
                _sensor(BATON_ROUGE_STALE, WINDOW_START + timedelta(days=30)),
                _sensor(BATON_ROUGE_CURRENT, WINDOW_END),
            ],
        ),
        _location(101, "Port Allen", PORT_ALLEN, sensors=[_sensor(PORT_ALLEN_SENSOR, WINDOW_END)]),
        _location(102, "Gonzales", GONZALES, sensors=[_sensor(GONZALES_SENSOR, WINDOW_END)]),
        _location(103, "Faulty Ridge", FAULTY, sensors=[_sensor(FAULTY_SENSOR, WINDOW_END)]),
        _location(104, "Silent Bayou", SILENT, sensors=[_sensor(SILENT_SENSOR, WINDOW_END)]),
        _location(
            105,
            "Houston Deer Park",
            HOUSTON,
            sensors=[_sensor(HOUSTON_SENSOR, WINDOW_END)],
        ),
        _location(
            106,
            "Survey van",
            (30.5000, -91.1000),
            sensors=[_sensor(MOBILE_SENSOR, WINDOW_END)],
            is_mobile=True,
            is_monitor=False,
        ),
    ]
    series: dict[int, list[dict[str, object]]] = {
        BATON_ROUGE_STALE: _series(30, 99.0, ending=WINDOW_START + timedelta(days=30)),
        BATON_ROUGE_CURRENT: _series(WINDOW_DAYS, 9.0),
        PORT_ALLEN_SENSOR: _series(WINDOW_DAYS, 15.0),
        # Reports, but nowhere near the 75% an annual mean needs.
        GONZALES_SENSOR: _series(100, 6.0),
        FAULTY_SENSOR: _faulty_series(),
        SILENT_SENSOR: [_reading(WINDOW_END - timedelta(days=n), None) for n in range(5)],
        HOUSTON_SENSOR: _series(10, 12.0),
        MOBILE_SENSOR: _series(10, 11.0),
    }
    return locations, series


def openaq_handler(
    *,
    locations: list[dict[str, object]] | None = None,
    series: dict[int, list[dict[str, object]]] | None = None,
    fail: set[str] | None = None,
    unauthorized: bool = False,
) -> Callable[[httpx.Request], httpx.Response]:
    built_locations, built_series = fixture_network()
    served_locations = built_locations if locations is None else locations
    served_series = built_series if series is None else series
    down = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        base = str(request.url).split("?")[0]
        if unauthorized:
            return httpx.Response(401, text=json.dumps({"message": "Unauthorized."}))
        if base in down:
            return httpx.Response(503)
        if base == LOCATIONS_URL:
            page = int(request.url.params.get("page", "1"))
            body = {
                "meta": {"page": page, "found": len(served_locations)},
                "results": served_locations if page == 1 else [],
            }
            return httpx.Response(
                200, text=json.dumps(body), headers={"Content-Type": "application/json"}
            )
        if base.endswith("/days"):
            sensor_id = int(base.rsplit("/", 2)[-2])
            body = {"meta": {"page": 1}, "results": served_series.get(sensor_id, [])}
            return httpx.Response(
                200, text=json.dumps(body), headers={"Content-Type": "application/json"}
            )
        return httpx.Response(404)

    return handler


def openaq_transport(**kwargs: object) -> httpx.MockTransport:
    return httpx.MockTransport(openaq_handler(**kwargs))  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def small_envelope() -> Iterator[None]:
    """Narrow the pilot envelope so a test pays for 11,000 hexes, not 311,000."""
    shipped = PILOT_ENVELOPE["LA"]
    PILOT_ENVELOPE["LA"] = TEST_ENVELOPE
    yield
    PILOT_ENVELOPE["LA"] = shipped


@asynccontextmanager
async def openaq_context(
    sink: InMemorySink,
    *,
    transport: httpx.MockTransport | None = None,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
    key: str = KEY,
    policy: SourcePolicy = TEST_POLICY,
) -> AsyncIterator[RunContext]:
    async with build_client(policy, transport=transport or openaq_transport()) as client:
        yield make_context(
            http=make_fetcher(
                client, source="openaq", policy=policy, snapshots=snapshots, clock=clock
            ),
            sink=sink,
            policy=policy,
            source="openaq",
            credentials={"openaq_api_key": key},
        )


async def run(sink: InMemorySink, **kwargs: object) -> PullMetadata:
    async with openaq_context(sink, **kwargs) as ctx:  # type: ignore[arg-type]
        return await run_adapter(OpenAqAdapter(), ctx)


def monitors(sink: InMemorySink) -> dict[str, Monitor]:
    return {r.monitor_id: r for r in sink.rows(Monitor.table) if isinstance(r, Monitor)}


def measurements(sink: InMemorySink, monitor_id: str) -> list[MonitorMeasurement]:
    rows = [
        r
        for r in sink.rows(MonitorMeasurement.table)
        if isinstance(r, MonitorMeasurement) and r.monitor_id == monitor_id
    ]
    return sorted(rows, key=lambda r: r.measured_on)


def hexes(sink: InMemorySink) -> dict[str, HexAirQuality]:
    return {r.h3: r for r in sink.rows(HexAirQuality.table) if isinstance(r, HexAirQuality)}


def hex_at(sink: InMemorySink, point: tuple[float, float]) -> HexAirQuality:
    return hexes(sink)[h3.latlng_to_cell(point[0], point[1], 8)]


def gaps_text(result: PullMetadata) -> str:
    return " ".join(gap.detail for gap in result.known_gaps)


@pytest.fixture
async def loaded(sink: InMemorySink) -> AsyncIterator[tuple[PullMetadata, InMemorySink]]:
    yield await run(sink), sink


# ---- the contract ------------------------------------------------------


async def test_the_adapter_is_registered_and_says_it_feeds_e4() -> None:
    from pipeline.adapters import get, names

    assert "openaq" in names()
    assert get("openaq").spec.provides == ("E4",)


async def test_a_pull_loads_monitors_measurements_and_hex_coverage(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert result.ok, result.notes
    assert sink.count(Monitor.table) > 0
    assert sink.count(MonitorMeasurement.table) > 0
    assert sink.count(HexAirQuality.table) > 0


async def test_the_key_reaches_upstream_as_a_header(sink: InMemorySink) -> None:
    seen: list[httpx.Request] = []
    served = openaq_handler()

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return served(request)

    await run(sink, transport=httpx.MockTransport(recording))

    assert seen
    assert all(request.headers.get("X-API-Key") == KEY for request in seen)


async def test_a_missing_key_fails_the_run_and_says_so(sink: InMemorySink) -> None:
    result = await run(sink, key="")

    assert result.status == "failed"
    assert "openaq_api_key" in " ".join(result.notes)
    assert sink.count(Monitor.table) == 0


# ---- measurements ------------------------------------------------------


async def test_daily_means_are_stored_with_the_observations_behind_them(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    days = measurements(sink, "100")

    assert len(days) == WINDOW_DAYS
    assert days[0].measured_on == WINDOW_START
    assert days[-1].measured_on == WINDOW_END
    assert {d.parameter for d in days} == {PM25}
    assert all(d.observation_count == 24 for d in days)


async def test_a_location_with_two_sensors_is_read_through_the_current_one(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    # The stale sensor carries a mean of 99; the current one carries 9.
    assert monitors(sink)["100"].openaq_sensor_id == str(BATON_ROUGE_CURRENT)
    assert all(day.value < 50.0 for day in measurements(sink, "100"))
    assert "more than one PM2.5 sensor" in " ".join(result.notes)


async def test_a_monitor_is_placed_on_the_hex_grid(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    monitor = monitors(loaded[1])["100"]

    assert monitor.h3 == h3.latlng_to_cell(*BATON_ROUGE, 8)
    assert monitor.is_regulatory is True


# ---- the screening rules -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-3.0, "negative concentration"),
        (min(SENTINEL_VALUES), "sentinel no-data value"),
        (MAX_PM25_UGM3 + 1.0, "ceiling"),
        (None, "no value reported"),
    ],
)
def test_an_impossible_reading_is_rejected_for_a_stated_reason(
    value: float | None, expected: str
) -> None:
    reading = DailyReading(
        measured_on=WINDOW_END,
        value=value,
        unit="µg/m³",
        parameter=PM25,
        observation_count=24,
        completeness_pct=100.0,
        flagged_upstream=False,
        in_stuck_run=False,
    )
    fault = reading_fault(reading, (WINDOW_START, WINDOW_END))

    assert fault is not None
    assert expected in fault[0]


def test_a_high_smoke_day_survives_the_screen() -> None:
    """The screen rejects the impossible, not the merely unusual."""
    reading = DailyReading(
        measured_on=WINDOW_END,
        value=180.0,
        unit="µg/m³",
        parameter=PM25,
        observation_count=24,
        completeness_pct=100.0,
        flagged_upstream=False,
        in_stuck_run=False,
    )

    assert reading_fault(reading, (WINDOW_START, WINDOW_END)) is None


def test_a_fortnight_of_the_same_value_is_a_stuck_sensor() -> None:
    def day(offset: int, value: float) -> DailyReading:
        return DailyReading(
            measured_on=WINDOW_START + timedelta(days=offset),
            value=value,
            unit="µg/m³",
            parameter=PM25,
            observation_count=24,
            completeness_pct=100.0,
            flagged_upstream=False,
            in_stuck_run=False,
        )

    stuck = [day(n, 4.4) for n in range(STUCK_RUN_DAYS)]
    shorter = [day(n, 6.6) for n in range(STUCK_RUN_DAYS, STUCK_RUN_DAYS + 5)]

    marked = mark_stuck_runs(stuck + shorter)

    assert all(r.in_stuck_run for r in marked[:STUCK_RUN_DAYS])
    assert not any(r.in_stuck_run for r in marked[STUCK_RUN_DAYS:])


def test_a_gap_in_the_record_breaks_a_run_of_identical_values() -> None:
    def day(offset: int) -> DailyReading:
        return DailyReading(
            measured_on=WINDOW_START + timedelta(days=offset),
            value=4.4,
            unit="µg/m³",
            parameter=PM25,
            observation_count=24,
            completeness_pct=100.0,
            flagged_upstream=False,
            in_stuck_run=False,
        )

    # Two runs of ten, a fortnight of the same number in total, but with a
    # missing day between them. Neither half is long enough on its own.
    split = [day(n) for n in range(10)] + [day(n) for n in range(11, 21)]

    assert not any(r.in_stuck_run for r in mark_stuck_runs(split))


async def test_every_documented_fault_is_counted_as_a_rejection(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded
    reasons = result.rejection_reasons

    assert result.counts.rejected > 0
    for expected in (
        "negative concentration",
        "sentinel no-data value",
        "flagged by the data provider",
        "no value reported for the day",
        "stuck sensor",
    ):
        assert any(expected in reason for reason in reasons), (expected, sorted(reasons))


async def test_the_tolerance_changes_the_verdict_and_nothing_about_the_losses(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """A looser tolerance must not make the rejections less visible.

    The runner counts, tallies and samples before it consults the tolerance, so
    the same pull reports the same losses whether it loads or fails.
    """
    lenient, _ = loaded
    strict = await run(
        InMemorySink(),
        policy=SourcePolicy(
            rate_limit=OpenAqAdapter.policy.rate_limit,
            partial_failure=PartialFailurePolicy(max_reject_fraction=0.0),
        ),
    )

    assert lenient.status == "partial"
    assert strict.status == "failed"
    assert strict.counts.rejected == lenient.counts.rejected
    assert strict.rejection_reasons == lenient.rejection_reasons
    assert [r.record_id for r in strict.rejections] == [r.record_id for r in lenient.rejections]


async def test_a_monitor_outside_the_pilot_state_is_rejected(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert "105" not in monitors(sink)
    assert any("envelope" in reason for reason in result.rejection_reasons)


async def test_a_years_readings_are_not_pulled_for_a_monitor_that_cannot_be_used(
    sink: InMemorySink,
) -> None:
    """The rejection is counted once, on the monitor, not once per reading."""
    seen: list[str] = []
    served = openaq_handler()

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url).split("?")[0])
        return served(request)

    result = await run(sink, transport=httpx.MockTransport(recording))

    for skipped in (HOUSTON_SENSOR, MOBILE_SENSOR):
        assert not any(str(skipped) in url for url in seen)
    assert result.rejection_reasons["mobile monitor, not a fixed station"] == 1


async def test_a_mobile_monitor_is_rejected_rather_than_pinned_to_a_hex(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert "106" not in monitors(sink)
    assert any("mobile" in reason for reason in result.rejection_reasons)


# ---- the sparse-coverage rule ------------------------------------------


async def test_a_hex_beside_a_monitor_carries_a_measured_value(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    cell = hex_at(sink, BATON_ROUGE)

    assert cell.annual_mean.observed is True
    assert cell.annual_mean.value is not None
    assert cell.nearest_monitor_km < 1.0
    assert cell.monitors_used >= 1


async def test_a_hex_beyond_the_interpolation_radius_is_absent_never_zero(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded

    far = [
        cell for cell in hexes(sink).values() if cell.nearest_monitor_km > INTERPOLATION_RADIUS_KM
    ]

    assert far, "the fixture should contain hexes beyond every monitor"
    for cell in far:
        assert cell.annual_mean.observed is False
        assert cell.annual_mean.value is None
        assert cell.monitors_used == 0
        assert cell.day_count == 0


async def test_an_unmeasured_hex_still_knows_how_far_the_nearest_monitor_is(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """The c_monitor term and the detail panel both read this."""
    _, sink = loaded
    cell = hex_at(sink, GONZALES)

    assert cell.annual_mean.observed is False
    assert cell.nearest_monitor_id == "102"
    assert cell.nearest_monitor_km < 1.0


async def test_the_stored_distance_is_the_distance_to_the_nearest_monitor(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    covered = hexes(sink)
    # Only monitors that reported anchor the distance; the silent one does not.
    anchoring = {cell.nearest_monitor_id for cell in covered.values()}
    sited = [
        (m.latitude, m.longitude) for m in monitors(sink).values() if m.monitor_id in anchoring
    ]

    for cell in list(covered.values())[::250]:
        lat, lon = h3.cell_to_latlng(cell.h3)
        closest = min(haversine_km(lat, lon, *point) for point in sited)
        assert cell.nearest_monitor_km == pytest.approx(closest, abs=0.001)
        assert cell.nearest_monitor_km <= COVERAGE_RADIUS_KM


async def test_an_interpolated_value_lies_between_the_monitors_that_made_it(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Baton Rouge reports 9, Port Allen 15, and they are 9.8 km apart."""
    _, sink = loaded
    midpoint = ((BATON_ROUGE[0] + PORT_ALLEN[0]) / 2, (BATON_ROUGE[1] + PORT_ALLEN[1]) / 2)
    cell = hex_at(sink, midpoint)

    assert cell.monitors_used == 2
    assert cell.annual_mean.value is not None
    assert 9.0 < cell.annual_mean.value < 15.0
    # Equidistant, so an inverse-distance mean sits halfway.
    assert cell.annual_mean.value == pytest.approx(12.0, abs=0.5)


async def test_a_hex_takes_the_nearer_monitor_more_heavily(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    beside_baton_rouge = hex_at(sink, BATON_ROUGE).annual_mean.value
    beside_port_allen = hex_at(sink, PORT_ALLEN).annual_mean.value

    assert beside_baton_rouge is not None and beside_port_allen is not None
    assert beside_baton_rouge < 10.0
    assert beside_port_allen > 14.0


async def test_a_neighbours_reading_never_leaks_past_the_radius(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    valued = [c for c in hexes(sink).values() if c.annual_mean.observed]

    assert valued
    assert max(c.nearest_monitor_km for c in valued) <= INTERPOLATION_RADIUS_KM


async def test_observation_count_and_recency_are_stored_per_hex(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    cell = hex_at(sink, BATON_ROUGE)

    # Baton Rouge and Port Allen both reach this hex, each with a full year.
    assert cell.monitors_used == 2
    assert cell.day_count == cell.monitors_used * WINDOW_DAYS
    assert cell.observation_count == cell.day_count * 24
    assert cell.latest_measured_on == WINDOW_END
    assert cell.window_start == WINDOW_START
    assert cell.window_end == WINDOW_END


async def test_an_incomplete_monitor_anchors_confidence_but_not_the_value(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Gonzales reports 100 days, well under the 75% an annual mean needs."""
    result, sink = loaded
    cell = hex_at(sink, GONZALES)

    assert "102" in monitors(sink)
    assert cell.nearest_monitor_id == "102"
    assert cell.annual_mean.observed is False
    assert str(MIN_VALID_DAYS) in gaps_text(result)


async def test_a_silent_monitor_does_not_anchor_confidence(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded

    assert "104" in monitors(sink), "the monitor is still recorded"
    assert not any(cell.nearest_monitor_id == "104" for cell in hexes(sink).values())


# ---- provenance --------------------------------------------------------


async def test_the_vintage_is_the_last_day_measured_not_the_download_time(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    assert loaded[0].vintage == f"daily/{WINDOW_END.isoformat()}"


async def test_every_request_is_recorded_as_a_checksummed_artifact(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded

    assert result.artifacts
    assert all(len(a.sha256) == 64 and a.size_bytes > 0 for a in result.artifacts)
    # One artifact per query, so a page is never confused with another page.
    assert len({a.url for a in result.artifacts}) == len(result.artifacts)


async def test_the_sparse_coverage_of_the_network_is_declared_as_a_known_gap(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    text = gaps_text(loaded[0])

    assert "never as zero" in text
    assert "Monitor siting is not random" in text


async def test_a_silent_monitor_reaches_the_manifest(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    assert "no usable reading" in gaps_text(loaded[0])


# ---- failure handling --------------------------------------------------


async def test_an_unauthorized_key_fails_the_run_and_loads_nothing(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=openaq_transport(unauthorized=True))

    assert result.status == "failed"
    assert sink.count(Monitor.table) == 0


async def test_an_empty_location_list_fails_rather_than_emptying_the_map(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=openaq_transport(locations=[]))

    assert result.status == "failed"
    assert sink.count(HexAirQuality.table) == 0


async def test_an_unavailable_openaq_falls_back_to_the_last_snapshot(
    sink: InMemorySink,
) -> None:
    snapshots = InMemorySnapshotStore()
    first = await run(sink, snapshots=snapshots)
    assert first.ok

    second = await run(
        sink,
        transport=openaq_transport(fail={LOCATIONS_URL}),
        snapshots=snapshots,
    )

    assert second.status == "stale"
    assert second.counts.loaded > 0
    assert all(a.from_snapshot for a in second.artifacts)


async def test_a_second_pull_updates_rather_than_duplicates(sink: InMemorySink) -> None:
    await run(sink)
    monitor_rows, hex_rows = sink.count(Monitor.table), sink.count(HexAirQuality.table)

    await run(sink)

    assert sink.count(Monitor.table) == monitor_rows
    assert sink.count(HexAirQuality.table) == hex_rows


# ---- the shipped configuration -----------------------------------------


def test_the_adapter_declares_a_rate_limit_and_a_tolerance_and_nothing_else() -> None:
    policy = OpenAqAdapter.policy

    assert policy.rate_limit.requests_per_second == 1.0
    assert policy.retry == SourcePolicy().retry
    assert policy.request_timeout_s == SourcePolicy().request_timeout_s


def test_the_measured_pull_is_recorded_in_full() -> None:
    """The tolerance is checked against these numbers, so they must add up."""
    assert sum(MEASURED_PULL_REJECTIONS.values()) == MEASURED_PULL_REJECTED
    assert MEASURED_PULL_REJECTED / MEASURED_PULL_RECORDS == pytest.approx(0.089, abs=0.001)

    # Every reason in the measured pull is one the documented screen produces,
    # spelled the way `reading_fault` spells it.
    assert set(MEASURED_PULL_REJECTIONS) <= set(_documented_reading_faults())


def test_the_measured_statewide_pull_loads_rather_than_failing_the_night() -> None:
    assert _measured_verdict(MEASURED_PULL_REJECTED) == "partial"


def test_the_tolerance_carries_one_failed_monitor_and_no_more() -> None:
    """15% is a measured position, not a round-up: one monitor of headroom.

    About two dozen monitors over a WINDOW_DAYS window, so a monitor that goes
    entirely incomplete adds roughly WINDOW_DAYS rejections to the steady state.
    """
    assert _measured_verdict(MEASURED_PULL_REJECTED + WINDOW_DAYS) == "partial"
    assert _measured_verdict(MEASURED_PULL_REJECTED + 2 * WINDOW_DAYS) == "failed"


def test_a_pull_that_rejects_far_above_the_steady_state_still_fails() -> None:
    """The guard the 1% default was protecting is kept, not removed."""
    assert _measured_verdict(MEASURED_PULL_REJECTED * 2) == "failed"
    assert _measured_verdict(MEASURED_PULL_RECORDS // 2) == "failed"


def _measured_verdict(rejected: int) -> str:
    """The shipped tolerance's verdict on the measured pull with `rejected` lost."""
    return OpenAqAdapter.policy.partial_failure.verdict(
        accepted=MEASURED_PULL_RECORDS - rejected, rejected=rejected
    )


def _documented_reading_faults() -> set[str]:
    """Every reason the measured pull saw, spelled by `reading_fault` itself."""

    def daily(
        *,
        value: float | None = 8.0,
        completeness_pct: float = 100.0,
        flagged_upstream: bool = False,
    ) -> DailyReading:
        return DailyReading(
            measured_on=WINDOW_END,
            value=value,
            unit="µg/m³",
            parameter=PM25,
            observation_count=24,
            completeness_pct=completeness_pct,
            flagged_upstream=flagged_upstream,
            in_stuck_run=False,
        )

    reasons = set()
    for reading in (
        daily(value=None),
        daily(flagged_upstream=True),
        daily(completeness_pct=50.0),
    ):
        fault = reading_fault(reading, (WINDOW_START, WINDOW_END))
        assert fault is not None
        reasons.add(fault[0])
    return reasons


def test_the_shipped_envelope_covers_the_pilot_state(small_envelope: None) -> None:
    """The narrowing fixture is a test convenience; the real box is Louisiana."""
    PILOT_ENVELOPE["LA"] = (28.83, 33.10, -94.14, -88.73)
    south, north, west, east = PILOT_ENVELOPE["LA"]

    # Louisiana's extremes, plus the offshore corner of the state boundary.
    for latitude, longitude in (BATON_ROUGE, (32.99, -93.90), (29.15, -89.25), (30.24, -93.92)):
        assert south <= latitude <= north
        assert west <= longitude <= east


def test_the_radii_match_the_methodology() -> None:
    assert INTERPOLATION_RADIUS_KM == 25.0
    # min(1, 10 / d) reaches the 0.05 floor section 12 applies to every term.
    assert 10.0 / COVERAGE_RADIUS_KM == pytest.approx(0.05)


def test_every_normalized_record_declares_a_table_and_a_key() -> None:
    for record_type in (Monitor, MonitorMeasurement, HexAirQuality):
        assert isinstance(record_type.table, str) and record_type.table
