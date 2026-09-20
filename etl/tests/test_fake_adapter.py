"""The reference implementation, end to end, against its fixture."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import h3
import httpx

from pipeline.adapters.fake import (
    FIXTURE_URL,
    SAMPLE_CSV,
    FakeAirAdapter,
    StationReading,
    fixture_transport,
)
from pipeline.context import RunContext
from pipeline.http import build_client
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore
from tests.conftest import FIXED_NOW, FakeClock, make_context, make_fetcher

TABLE = StationReading.table


@asynccontextmanager
async def fake_context(
    sink: InMemorySink,
    *,
    transport: httpx.MockTransport | None = None,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
) -> AsyncIterator[RunContext]:
    policy = FakeAirAdapter.policy
    async with build_client(policy, transport=transport or fixture_transport()) as client:
        yield make_context(
            http=make_fetcher(
                client, source="fake", policy=policy, snapshots=snapshots, clock=clock
            ),
            sink=sink,
            policy=policy,
            source="fake",
        )


def readings(sink: InMemorySink) -> dict[str, StationReading]:
    return {row.station_id: row for row in sink.rows(TABLE) if isinstance(row, StationReading)}


async def test_the_reference_adapter_runs_all_four_stages(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    assert result.status == "partial"
    assert result.counts.fetched == 7
    assert result.counts.validated == 4
    assert result.counts.rejected == 3
    assert result.record_count == 4
    assert sink.count(TABLE) == 4


async def test_a_measured_zero_survives_the_pipeline(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        await run_adapter(FakeAirAdapter(), ctx)

    zero = readings(sink)["BR-02"]
    assert zero.pm25.observed
    assert zero.pm25.value == 0.0


async def test_a_silent_station_is_missing_and_not_zero(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        await run_adapter(FakeAirAdapter(), ctx)

    offline = readings(sink)["NOLA-03"]
    assert not offline.pm25.observed
    assert offline.pm25.value is None


async def test_points_land_on_the_resolution_eight_grid(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        await run_adapter(FakeAirAdapter(), ctx)

    cells = [row.h3 for row in readings(sink).values()]
    assert len(cells) == 4
    assert all(h3.get_resolution(cell) == 8 for cell in cells)


async def test_bad_rows_are_rejected_for_stated_reasons(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    assert result.rejection_reasons == {
        "outside the LA envelope": 1,
        "coordinates outside the world": 1,
        "negative concentration": 1,
    }
    assert {r.record_id for r in result.rejections} == {"HOU-05", "BAD-06", "NEG-07"}


async def test_the_manifest_carries_the_five_required_facts(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    assert result.source == "fake"
    assert result.vintage == "daily/2026-09-09"
    assert result.pulled_at == FIXED_NOW
    assert result.record_count == 4
    assert len(result.known_gaps) == 2

    gaps = " ".join(gap.detail for gap in result.known_gaps)
    assert "NOLA-03" in gaps
    assert "Fictional source" in gaps


async def test_the_artifact_is_checksummed(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    artifact = result.artifacts[0]
    assert artifact.url == FIXTURE_URL
    assert artifact.sha256 == hashlib.sha256(SAMPLE_CSV.encode()).hexdigest()
    assert not artifact.from_snapshot


async def test_the_provenance_row_is_ready_for_the_docs_table(sink: InMemorySink) -> None:
    async with fake_context(sink) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    row = result.provenance_row()
    assert row.startswith("| fake | daily/2026-09-09 |")
    assert "| 4 | partial |" in row


async def test_a_second_pull_updates_rather_than_duplicates(sink: InMemorySink) -> None:
    for _ in range(2):
        async with fake_context(sink) as ctx:
            await run_adapter(FakeAirAdapter(), ctx)

    assert sink.count(TABLE) == 4


async def test_a_changed_schema_fails_the_run_and_loads_nothing(sink: InMemorySink) -> None:
    without_values = "station_id,latitude,longitude,observed_on\nBR-01,30.4,-91.1,2026-09-09\n"
    async with fake_context(sink, transport=fixture_transport(without_values)) as ctx:
        result = await run_adapter(FakeAirAdapter(), ctx)

    assert result.status == "failed"
    assert result.vintage == "unavailable"
    assert sink.tables == {}
    assert "missing columns" in " ".join(result.notes)


async def test_an_unavailable_source_falls_back_to_the_last_snapshot(
    sink: InMemorySink,
) -> None:
    store = InMemorySnapshotStore()
    reachable = True

    def handler(request: httpx.Request) -> httpx.Response:
        if reachable:
            return httpx.Response(200, text=SAMPLE_CSV, headers={"Content-Type": "text/csv"})
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)

    async with fake_context(sink, transport=transport, snapshots=store) as ctx:
        first = await run_adapter(FakeAirAdapter(), ctx)
    assert first.status == "partial"

    reachable = False
    second_sink = InMemorySink()
    async with fake_context(
        second_sink, transport=transport, snapshots=store, clock=FakeClock()
    ) as ctx:
        second = await run_adapter(FakeAirAdapter(), ctx)

    # The night continues on last night's bytes, says so, and degrades recency.
    assert second.status == "stale"
    assert second.record_count == 4
    assert second.artifacts[0].from_snapshot
    assert "last good snapshot" in " ".join(second.notes)
    assert any("was unavailable" in gap.detail for gap in second.known_gaps)
