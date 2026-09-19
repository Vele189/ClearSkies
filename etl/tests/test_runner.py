"""The behaviour every adapter inherits, tested once."""

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import ClassVar

import httpx

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.context import RunContext
from pipeline.errors import RecordRejected, SinkError
from pipeline.http import build_client
from pipeline.metadata import SourceSpec
from pipeline.policy import DEFAULT_POLICY, PartialFailurePolicy, SourcePolicy
from pipeline.records import NormalizedRecord
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from tests.conftest import make_context, make_fetcher


@dataclass(frozen=True, slots=True)
class Row:
    id: str
    ok: bool = True


class StubRecord(NormalizedRecord):
    table: ClassVar[str] = "stub_rows"
    id: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.id,)


class StubAdapter(SourceAdapter[Row]):
    """Not registered: it exists to drive the runner, not to ingest anything."""

    spec = SourceSpec(
        name="stub",
        title="Stub source",
        homepage="https://stub.invalid",
        cadence="never",
        native_geography="none",
    )

    def __init__(self, rows: Sequence[Row], *, vintage: str = "v1") -> None:
        self.rows = rows
        self.vintage = vintage

    async def fetch(self, ctx: RunContext) -> FetchResult[Row]:
        return FetchResult(records=self.rows, vintage=self.vintage)

    def validate(self, record: Row, ctx: RunContext) -> None:
        if not record.ok:
            raise RecordRejected("row marked bad", field="ok", record_id=record.id)

    def normalize(self, record: Row, ctx: RunContext) -> Iterator[StubRecord]:
        yield StubRecord(id=record.id)


class CollidingAdapter(StubAdapter):
    def normalize(self, record: Row, ctx: RunContext) -> Iterator[StubRecord]:
        yield StubRecord(id="always-the-same")


class FailingLoadAdapter(StubAdapter):
    async def load(self, records: Sequence[NormalizedRecord], ctx: RunContext) -> int:
        raise SinkError("the database went away mid-write")


@asynccontextmanager
async def stub_context(
    sink: InMemorySink,
    *,
    policy: SourcePolicy = DEFAULT_POLICY,
    dry_run: bool = False,
) -> AsyncIterator[RunContext]:
    # The stub never makes a request; the transport is here so the context is
    # complete and any accidental request fails loudly.
    transport = httpx.MockTransport(lambda request: httpx.Response(599))
    async with build_client(transport=transport) as client:
        yield make_context(
            http=make_fetcher(client, source="stub", policy=policy),
            sink=sink,
            policy=policy,
            source="stub",
            dry_run=dry_run,
        )


async def test_a_clean_pull_loads_and_commits(sink: InMemorySink) -> None:
    adapter = StubAdapter([Row("a"), Row("b"), Row("c")])
    async with stub_context(sink) as ctx:
        result = await run_adapter(adapter, ctx)

    assert result.status == "ok"
    assert result.record_count == 3
    assert result.counts.fetched == 3
    assert result.counts.rejected == 0
    assert sink.count("stub_rows") == 3
    # The manifest is committed with the data, in the same transaction.
    assert [m.vintage for m in sink.manifests] == ["v1"]


async def test_a_few_rejects_are_tolerated_and_recorded(sink: InMemorySink) -> None:
    rows = [Row(f"r{n}") for n in range(99)] + [Row("bad", ok=False)]
    async with stub_context(sink) as ctx:
        result = await run_adapter(StubAdapter(rows), ctx)

    assert result.status == "partial"
    assert result.record_count == 99
    assert result.rejection_reasons == {"row marked bad": 1}
    assert result.rejections[0].record_id == "bad"


async def test_too_many_rejects_loads_nothing(sink: InMemorySink) -> None:
    # Coverage loss must show up as a failed run, not as a smaller map.
    rows = [Row("a"), Row("b"), Row("x", ok=False)]
    async with stub_context(sink) as ctx:
        result = await run_adapter(StubAdapter(rows), ctx)

    assert result.status == "failed"
    assert result.record_count == 0
    assert sink.tables == {}
    assert sink.manifests == []
    assert "above the configured tolerance" in " ".join(result.notes)


async def test_an_empty_pull_fails(sink: InMemorySink) -> None:
    async with stub_context(sink) as ctx:
        result = await run_adapter(StubAdapter([]), ctx)

    assert result.status == "failed"
    assert sink.tables == {}


async def test_an_adapter_may_widen_its_own_tolerance(sink: InMemorySink) -> None:
    lenient = SourcePolicy(partial_failure=PartialFailurePolicy(max_reject_fraction=0.5))
    rows = [Row("a"), Row("b"), Row("x", ok=False)]
    async with stub_context(sink, policy=lenient) as ctx:
        result = await run_adapter(StubAdapter(rows), ctx)

    assert result.status == "partial"
    assert sink.count("stub_rows") == 2


async def test_duplicate_natural_keys_fail_the_run(sink: InMemorySink) -> None:
    async with stub_context(sink) as ctx:
        result = await run_adapter(CollidingAdapter([Row("a"), Row("b")]), ctx)

    assert result.status == "failed"
    assert "duplicate natural keys" in " ".join(result.notes)
    assert sink.tables == {}


async def test_a_write_failure_rolls_back(sink: InMemorySink) -> None:
    async with stub_context(sink) as ctx:
        result = await run_adapter(FailingLoadAdapter([Row("a")]), ctx)

    assert result.status == "failed"
    assert result.record_count == 0
    assert sink.tables == {}
    assert sink.manifests == []
    assert "rolled back" in " ".join(result.notes)


async def test_dry_run_normalizes_but_writes_nothing(sink: InMemorySink) -> None:
    async with stub_context(sink, dry_run=True) as ctx:
        result = await run_adapter(StubAdapter([Row("a"), Row("b")]), ctx)

    assert result.status == "ok"
    assert result.counts.normalized == 2
    assert result.record_count == 0
    assert sink.tables == {}
    assert "dry run: nothing was written" in result.notes


async def test_the_pull_timestamp_comes_from_the_context(sink: InMemorySink) -> None:
    async with stub_context(sink) as ctx:
        result = await run_adapter(StubAdapter([Row("a")]), ctx)

    assert result.pulled_at == ctx.now
