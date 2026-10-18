"""The limit on the endpoints that cost a database query rather than money.

CS-402. `test_rate_limit.py` covers the window itself and the draft endpoint;
this is about which endpoints carry the read limit, which ones deliberately do
not, and what a 429 tells the reader.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import rate_limit
from app.config import get_settings
from app.main import app


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A deployment that allows two reads per hour."""
    monkeypatch.setenv("READ_RATE_LIMIT", "2")
    monkeypatch.setenv("READ_RATE_WINDOW_S", "3600")
    get_settings.cache_clear()
    rate_limit.reset_all()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        rate_limit.reset_all()
        get_settings.cache_clear()


@pytest.fixture
def unlimited(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("READ_RATE_LIMIT", "0")
    get_settings.cache_clear()
    rate_limit.reset_all()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        rate_limit.reset_all()
        get_settings.cache_clear()


def test_a_read_endpoint_is_limited(limited: TestClient) -> None:
    assert limited.get("/indicators").status_code == 200
    assert limited.get("/indicators").status_code == 200

    refused = limited.get("/indicators")

    assert refused.status_code == 429
    assert refused.headers["Retry-After"]


def test_the_message_says_what_the_limit_is_and_that_the_data_is_still_public(
    limited: TestClient,
) -> None:
    """A 429 that reads as a refusal of access would misdescribe this one."""
    for _ in range(2):
        limited.get("/indicators")

    detail = limited.get("/indicators").json()["detail"]

    assert "2 read requests every 3600 seconds" in detail
    assert "no quota on how much of it you may have" in detail
    assert "try again in" in detail.lower()


def test_health_is_never_limited(limited: TestClient) -> None:
    """The uptime check polls it, and it must answer while the rest refuses.

    A limited health check pages the operator about a rate limit rather than
    about an outage, which is the opposite of what it is for.
    """
    for _ in range(10):
        assert limited.get("/health").status_code == 200


def test_the_two_limits_count_separately(limited: TestClient) -> None:
    """Clicking around the map must not use up a reader's drafts."""
    for _ in range(2):
        limited.get("/indicators")
    assert limited.get("/indicators").status_code == 429

    # No key is configured here, so /draft answers 503. What matters is that it
    # is not the 429 the read window would give it if they shared one.
    assert (
        limited.post(
            "/draft", json={"h3": "88444600ddfffff", "document_type": "public_comment_letter"}
        ).status_code
        != 429
    )


def test_a_limit_of_zero_turns_it_off(unlimited: TestClient) -> None:
    for _ in range(25):
        assert unlimited.get("/indicators").status_code == 200


def test_every_read_router_carries_the_limit() -> None:
    """A limit somebody has to remember to add is one the next endpoint lacks.

    It is declared on the router rather than the handler for that reason, and
    this asserts the set rather than trusting that it stayed declared.
    """
    from app.limits import enforce_read_limit

    # A router-level dependency is resolved into each route's dependant rather
    # than left on the app's route list, so this reads the routers themselves.
    limited_paths = set()
    for included in app.routes:
        router = getattr(included, "original_router", None)
        if router is None:
            continue
        for route in router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            if any(dep.call is enforce_read_limit for dep in dependant.dependencies):
                limited_paths.add(route.path)

    assert limited_paths == {"/hex/{h3_index}", "/provenance", "/indicators"}
