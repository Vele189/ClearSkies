"""Reference implementation, against a source that does not exist.

This adapter is the worked example the README refers to. It ingests a small CSV
of imaginary air quality stations, and it is deliberately the shortest thing that
still exercises every part of the contract:

- `fetch` goes through `ctx.http`, so it inherits the retry policy, the rate
  limit, the checksum, and the snapshot that a stale night falls back to,
- `validate` rejects three kinds of bad row, including one that is bad in a way
  only the pilot geography can tell you about,
- `normalize` puts a point on the H3 grid and, crucially, distinguishes a
  measured zero from a station that reported nothing,
- `load` is inherited unchanged, which is the point of having a default.

Nothing here talks to a real network. The fixture is served through an httpx
mock transport, so the tests and `python -m pipeline run fake` both work with no
internet and no credentials.
"""

import csv
import io
from collections.abc import Iterator
from datetime import date
from typing import ClassVar

import h3
import httpx

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.metadata import KnownGap, SourceSpec
from pipeline.policy import PartialFailurePolicy, RateLimit, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord

# Methodology section 5. Every point in this project lands on resolution 8.
HEX_RESOLUTION = 8

FIXTURE_URL = "https://fixtures.clearskies.invalid/fake-air/readings.csv"

REQUIRED_COLUMNS = frozenset({"station_id", "latitude", "longitude", "observed_on", "pm25_ugm3"})

# Crude Louisiana envelope. A real adapter uses the state boundary geometry; a
# bounding box is enough to show where a pilot-state check belongs.
PILOT_BBOX: dict[str, tuple[float, float, float, float]] = {
    # south, north, west, east
    "LA": (28.8, 33.1, -94.1, -88.7),
}

SAMPLE_CSV = """station_id,latitude,longitude,observed_on,pm25_ugm3,note
BR-01,30.4515,-91.1871,2026-09-09,12.4,
BR-02,30.2241,-92.0198,2026-09-09,0.0,calibrated zero
NOLA-03,29.9511,-90.0715,2026-09-09,,sensor offline
LKC-04,30.2266,-93.2174,2026-09-09,8.1,
HOU-05,29.7604,-95.3698,2026-09-09,7.0,outside the pilot state
BAD-06,91.5000,-90.0000,2026-09-09,7.2,impossible latitude
NEG-07,30.0000,-90.5000,2026-09-09,-3.0,negative concentration
"""


class StationReading(NormalizedRecord):
    """One station's reading for one day, placed on the hex grid."""

    table: ClassVar[str] = "fake_station_readings"

    station_id: str
    h3: str
    observed_on: date
    pm25: Measurement

    def natural_key(self) -> tuple[str, ...]:
        # Station and day, not the hex: two stations can share a hexagon, and a
        # station can move between hexagons without becoming a different station.
        return (self.station_id, self.observed_on.isoformat())


@register
class FakeAirAdapter(SourceAdapter[dict[str, str]]):
    """A four-stage adapter in about eighty lines."""

    spec = SourceSpec(
        name="fake",
        title="Fake air quality stations (reference implementation)",
        homepage=FIXTURE_URL,
        cadence="daily",
        native_geography="point (station lat/lon)",
        provides=("E4",),
        licence="none; this source is fictional",
    )

    # Two deliberate departures from the default, both for reasons a real source
    # would not have. The fixture is local, so there is nothing to be polite to;
    # and it carries three bad rows out of seven, which the default one-percent
    # tolerance would rightly refuse to load.
    policy: ClassVar[SourcePolicy] = SourcePolicy(
        rate_limit=RateLimit.unlimited(),
        partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
    )

    async def fetch(self, ctx: RunContext) -> FetchResult[dict[str, str]]:
        download = await ctx.http.get(FIXTURE_URL)
        rows = list(csv.DictReader(io.StringIO(download.text())))
        if not rows:
            raise PermanentSourceError(f"{FIXTURE_URL}: no rows")

        missing = REQUIRED_COLUMNS - set(rows[0])
        if missing:
            # A changed schema is permanent, not transient: retrying will not
            # bring the column back, and guessing at a replacement would be worse.
            raise PermanentSourceError(f"{FIXTURE_URL}: missing columns {sorted(missing)}")

        days = sorted(row["observed_on"] for row in rows if row.get("observed_on"))
        silent = [row["station_id"] for row in rows if not (row.get("pm25_ugm3") or "").strip()]

        gaps = []
        if silent:
            gaps.append(
                KnownGap(
                    scope="attribute",
                    detail=(
                        f"{len(silent)} of {len(rows)} stations reported no PM2.5 "
                        f"for {days[-1]}: {', '.join(silent)}"
                    ),
                    affects=("E4",),
                    since=date.fromisoformat(days[-1]),
                )
            )

        return FetchResult(
            records=rows,
            # The upstream release, not the download time. See FetchResult.
            vintage=f"daily/{days[-1]}",
            artifacts=[download.artifact],
            known_gaps=gaps,
        )

    def validate(self, record: dict[str, str], ctx: RunContext) -> None:
        station = (record.get("station_id") or "").strip()
        if not station:
            raise RecordRejected("missing station id", field="station_id")

        try:
            lat = float(record["latitude"])
            lon = float(record["longitude"])
        except (KeyError, ValueError):
            raise RecordRejected(
                "unparseable coordinates", field="latitude", record_id=station
            ) from None

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise RecordRejected(
                "coordinates outside the world", field="latitude", record_id=station
            )

        south, north, west, east = PILOT_BBOX[ctx.pilot_state]
        if not (south <= lat <= north and west <= lon <= east):
            # Methodology section 6: a self-reported coordinate in the wrong
            # state must not attribute a facility's releases to a neighbourhood
            # it is nowhere near.
            raise RecordRejected(
                f"outside the {ctx.pilot_state} envelope", field="latitude", record_id=station
            )

        try:
            date.fromisoformat(record["observed_on"])
        except (KeyError, ValueError):
            raise RecordRejected(
                "unparseable observation date", field="observed_on", record_id=station
            ) from None

        raw = (record.get("pm25_ugm3") or "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError:
                raise RecordRejected(
                    "unparseable concentration", field="pm25_ugm3", record_id=station
                ) from None
            if value < 0:
                raise RecordRejected("negative concentration", field="pm25_ugm3", record_id=station)

    def normalize(self, record: dict[str, str], ctx: RunContext) -> Iterator[StationReading]:
        # Re-parsing what validate already parsed is the price of keeping the
        # gate pure. It is one float per row and it keeps the two stages
        # independently readable.
        lat = float(record["latitude"])
        lon = float(record["longitude"])
        cell = str(h3.latlng_to_cell(lat, lon, HEX_RESOLUTION))

        raw = (record.get("pm25_ugm3") or "").strip()
        # The whole reason `Measurement` exists. An empty cell is a station that
        # reported nothing, which is not the same fact as a station that reported
        # zero, and imputing one to the other is the error this project is about.
        reading = Measurement.of(float(raw)) if raw else Measurement.absent()

        yield StationReading(
            station_id=record["station_id"].strip(),
            h3=cell,
            observed_on=date.fromisoformat(record["observed_on"]),
            pm25=reading,
        )

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="geographic",
                detail=(
                    "Fictional source. Seven stations covering a handful of "
                    "Louisiana hexagons; it exists to exercise the interface."
                ),
                affects=("E4",),
            ),
        )


def fixture_transport(csv_text: str = SAMPLE_CSV) -> httpx.MockTransport:
    """Serves the sample CSV, so the reference adapter runs with no network."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) != FIXTURE_URL:
            return httpx.Response(404)
        return httpx.Response(200, text=csv_text, headers={"Content-Type": "text/csv"})

    return httpx.MockTransport(handler)
