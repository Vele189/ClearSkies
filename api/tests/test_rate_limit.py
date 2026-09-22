"""The per-client limit on the endpoint that spends money.

What is under test is the window's arithmetic and the endpoint's 429, not a
promise about a deployment: the counters are this process's, so two replicas
allow twice the limit. See app/rate_limit.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.rate_limit import SlidingWindow, client_key
from app.routers import draft as draft_router


def test_requests_under_the_limit_pass() -> None:
    window = SlidingWindow(limit=3, window_s=60.0)

    assert [window.check("a", now=1.0) for _ in range(3)] == [None, None, None]


def test_the_next_request_is_told_how_long_to_wait() -> None:
    window = SlidingWindow(limit=2, window_s=60.0)
    window.check("a", now=10.0)
    window.check("a", now=20.0)

    assert window.check("a", now=30.0) == pytest.approx(40.0)


def test_the_window_slides_rather_than_resetting() -> None:
    window = SlidingWindow(limit=2, window_s=60.0)
    window.check("a", now=10.0)
    window.check("a", now=20.0)

    # The first hit has aged out; the second has not.
    assert window.check("a", now=71.0) is None
    assert window.check("a", now=72.0) == pytest.approx(8.0)


def test_knocking_while_limited_does_not_extend_the_wait() -> None:
    """A rejected request that recorded itself would push the window forward
    with every retry, which turns a rate limit into a ban."""
    window = SlidingWindow(limit=1, window_s=60.0)
    window.check("a", now=0.0)

    assert window.check("a", now=30.0) == pytest.approx(30.0)
    assert window.check("a", now=59.0) == pytest.approx(1.0)


def test_clients_are_counted_separately() -> None:
    window = SlidingWindow(limit=1, window_s=60.0)
    window.check("a", now=1.0)

    assert window.check("b", now=1.0) is None


def test_a_limit_of_zero_turns_it_off() -> None:
    window = SlidingWindow(limit=0, window_s=60.0)

    assert not window.enabled
    assert all(window.check("a", now=1.0) is None for _ in range(100))


def test_idle_clients_are_forgotten() -> None:
    """A long-running process should not accumulate one deque per address it
    has ever seen."""
    window = SlidingWindow(limit=2, window_s=60.0)
    window.check("gone", now=0.0)
    window.check("here", now=1000.0)

    assert set(window._hits) == {"here"}


def test_the_client_is_the_first_forwarded_hop_when_there_is_one() -> None:
    """Behind the platform's proxy every peer address is the proxy's."""
    assert client_key("203.0.113.7, 10.0.0.1", "10.0.0.1") == "203.0.113.7"
    assert client_key(None, "203.0.113.7") == "203.0.113.7"
    assert client_key("", None) == "unknown"


# ---- The endpoint --------------------------------------------------------


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A deployment configured with a key and a limit of two drafts."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DRAFT_RATE_LIMIT", "2")
    monkeypatch.setenv("DRAFT_RATE_WINDOW_S", "3600")
    get_settings.cache_clear()
    draft_router._limiter = None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        draft_router._limiter = None
        get_settings.cache_clear()


def body() -> dict[str, str]:
    return {"h3": "88444600ddfffff", "document_type": "public_comment_letter"}


def test_over_the_limit_is_429_with_a_retry_after(limited: TestClient) -> None:
    """The first two get as far as the database, which this process does not
    have; the third never gets that far."""
    for _ in range(2):
        assert limited.post("/draft", json=body()).status_code == 503

    response = limited.post("/draft", json=body())

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert "Try again in" in response.json()["detail"]


def test_the_limit_is_on_by_default() -> None:
    """Off by default would mean the endpoint that spends money is unguarded on
    every deployment that has not read the settings."""
    get_settings.cache_clear()
    settings = get_settings()
    try:
        assert settings.draft_rate_limit > 0
        assert settings.draft_rate_window_s > 0
    finally:
        get_settings.cache_clear()
