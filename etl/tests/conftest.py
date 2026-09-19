from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import httpx
import pytest

from pipeline.context import RunContext
from pipeline.http import HttpFetcher
from pipeline.policy import DEFAULT_POLICY, SourcePolicy
from pipeline.sinks import InMemorySink, Sink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore

# One fixed moment, so every assertion about provenance is exact.
FIXED_NOW = datetime(2026, 9, 10, 7, 0, tzinfo=UTC)


class FakeClock:
    """A monotonic clock that only moves when something sleeps on it.

    Backoff and rate limiting are behaviour worth testing and wall time is not,
    so every test injects this and asserts on `slept`.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sink() -> InMemorySink:
    return InMemorySink()


@pytest.fixture
def snapshots() -> InMemorySnapshotStore:
    return InMemorySnapshotStore()


def make_fetcher(
    client: httpx.AsyncClient,
    *,
    source: str = "fake",
    policy: SourcePolicy = DEFAULT_POLICY,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
    now: datetime = FIXED_NOW,
) -> HttpFetcher:
    ticker = clock if clock is not None else FakeClock()
    return HttpFetcher(
        client,
        source=source,
        policy=policy,
        snapshots=snapshots,
        now=lambda: now,
        monotonic=ticker.monotonic,
        sleep=ticker.sleep,
    )


def make_context(
    *,
    http: HttpFetcher,
    sink: Sink,
    policy: SourcePolicy = DEFAULT_POLICY,
    source: str = "fake",
    now: datetime = FIXED_NOW,
    pilot_state: str = "LA",
    dry_run: bool = False,
    credentials: Mapping[str, str] | None = None,
) -> RunContext:
    return RunContext(
        source=source,
        now=now,
        http=http,
        sink=sink,
        policy=policy,
        pilot_state=pilot_state,
        dry_run=dry_run,
        credentials=dict(credentials or {}),
    )


def counting_transport(
    responses: list[httpx.Response] | Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request],
) -> httpx.MockTransport:
    """Replays `responses` in order, recording every request it saw."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if callable(responses):
            return responses(request)
        index = min(len(calls) - 1, len(responses) - 1)
        return responses[index]

    return httpx.MockTransport(handler)
