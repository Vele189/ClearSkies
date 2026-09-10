import hashlib

import httpx
import pytest

from pipeline.errors import PermanentSourceError, TransientSourceError
from pipeline.http import USER_AGENT, build_client
from pipeline.policy import RetryPolicy, SourcePolicy
from pipeline.snapshots import InMemorySnapshotStore
from tests.conftest import FIXED_NOW, FakeClock, counting_transport, make_fetcher

URL = "https://source.invalid/data.csv"
BODY = b"station_id,value\nBR-01,1.0\n"

NO_JITTER = SourcePolicy(retry=RetryPolicy(jitter=0.0))


async def test_a_download_is_checksummed_and_dated() -> None:
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(200, content=BODY)], calls)
    async with build_client(transport=transport) as client:
        download = await make_fetcher(client).get(URL)

    assert download.content == BODY
    assert download.artifact.sha256 == hashlib.sha256(BODY).hexdigest()
    assert download.artifact.size_bytes == len(BODY)
    assert download.artifact.retrieved_at == FIXED_NOW
    assert download.artifact.url == URL
    assert not download.artifact.from_snapshot


async def test_the_client_identifies_itself() -> None:
    # Agencies serving this data are entitled to know who calls them nightly.
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(200, content=BODY)], calls)
    async with build_client(transport=transport) as client:
        await make_fetcher(client).get(URL)
    assert calls[0].headers["User-Agent"] == USER_AGENT


async def test_a_503_is_retried_and_then_succeeds() -> None:
    calls: list[httpx.Request] = []
    transport = counting_transport(
        [httpx.Response(503), httpx.Response(503), httpx.Response(200, content=BODY)], calls
    )
    clock = FakeClock()
    async with build_client(transport=transport) as client:
        fetcher = make_fetcher(client, policy=NO_JITTER, clock=clock)
        download = await fetcher.get(URL)

    assert download.content == BODY
    assert len(calls) == 3
    assert fetcher.retries == 2
    assert clock.slept == [1.0, 2.0]


async def test_retries_are_finite() -> None:
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(500)], calls)
    policy = SourcePolicy(retry=RetryPolicy(max_attempts=3, jitter=0.0))
    async with build_client(transport=transport) as client:
        with pytest.raises(TransientSourceError):
            await make_fetcher(client, policy=policy).get(URL)

    assert len(calls) == 3


async def test_a_429_waits_as_long_as_it_was_asked_to() -> None:
    calls: list[httpx.Request] = []
    transport = counting_transport(
        [httpx.Response(429, headers={"Retry-After": "9"}), httpx.Response(200, content=BODY)],
        calls,
    )
    clock = FakeClock()
    async with build_client(transport=transport) as client:
        await make_fetcher(client, policy=NO_JITTER, clock=clock).get(URL)

    assert clock.slept == [9.0]


async def test_a_404_is_not_retried() -> None:
    # A withdrawn dataset does not come back because we asked five times.
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(404)], calls)
    async with build_client(transport=transport) as client:
        with pytest.raises(PermanentSourceError):
            await make_fetcher(client).get(URL)

    assert len(calls) == 1


async def test_a_timeout_is_transient() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectTimeout("too slow", request=request)

    transport = httpx.MockTransport(handler)
    policy = SourcePolicy(retry=RetryPolicy(max_attempts=2, jitter=0.0))
    async with build_client(transport=transport) as client:
        with pytest.raises(TransientSourceError):
            await make_fetcher(client, policy=policy, clock=FakeClock()).get(URL)

    assert len(calls) == 2


async def test_every_download_becomes_a_snapshot() -> None:
    store = InMemorySnapshotStore()
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(200, content=BODY)], calls)
    async with build_client(transport=transport) as client:
        await make_fetcher(client, snapshots=store).get(URL)

    snapshot = await store.get("fake", URL)
    assert snapshot is not None
    assert snapshot.content == BODY


async def test_offline_serves_the_snapshot_without_touching_the_network() -> None:
    store = InMemorySnapshotStore()
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(200, content=BODY)], calls)
    async with build_client(transport=transport) as client:
        fetcher = make_fetcher(client, snapshots=store)
        await fetcher.get(URL)
        assert await fetcher.can_serve_offline()

        fetcher.offline = True
        replayed = await fetcher.get(URL)

    assert len(calls) == 1
    assert replayed.content == BODY
    assert replayed.artifact.from_snapshot
    assert replayed.artifact.sha256 == hashlib.sha256(BODY).hexdigest()


async def test_offline_with_nothing_stored_is_a_permanent_failure() -> None:
    calls: list[httpx.Request] = []
    transport = counting_transport([httpx.Response(200, content=BODY)], calls)
    async with build_client(transport=transport) as client:
        fetcher = make_fetcher(client, snapshots=InMemorySnapshotStore())
        fetcher.offline = True
        with pytest.raises(PermanentSourceError):
            await fetcher.get(URL)

    assert calls == []
