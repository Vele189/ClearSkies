"""Startup must not require the database.

A Railway deploy routinely comes up before Postgres is reachable. If the
process exits on that, the platform restarts it, it exits again, and the
service crash-loops behind a healthcheck that never answers. The whole point
of the optional pool in app/db.py is that the API instead starts, serves, and
says what is wrong. This is the regression check for that.
"""

from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import app

# Port 1 refuses immediately rather than hanging until db_connect_timeout, so
# this stays a fast test and does not depend on whether a local Postgres is up.
UNREACHABLE = "postgresql://clearskies:clearskies@127.0.0.1:1/clearskies"

# A real resolution 8 cell in the pilot state, so validation passes and the
# handler gets as far as needing the database.
LOUISIANA_HEX = "88444600ddfffff"


@pytest.fixture
def cold_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()


async def test_the_app_starts_with_no_database_and_leaves_the_pool_empty(
    cold_database: TestClient,
) -> None:
    assert await db.pool() is None


def test_health_answers_200_and_says_the_database_is_unavailable(
    cold_database: TestClient,
) -> None:
    r = cold_database.get("/health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert body["extensions"] == []
    assert body["notes"], "a degraded health report must say what is wrong"


def test_the_endpoints_that_need_no_database_still_serve(
    cold_database: TestClient,
) -> None:
    """The methodology and the schema are static, so a cold database cannot hide them."""
    assert cold_database.get("/indicators").status_code == 200
    assert cold_database.get("/openapi.json").status_code == 200
    assert cold_database.get("/docs").status_code == 200


def test_a_data_endpoint_reports_503_rather_than_failing(
    cold_database: TestClient,
) -> None:
    r = cold_database.get(f"/hex/{LOUISIANA_HEX}")

    assert r.status_code == 503
    assert "/health" in r.json()["detail"]


def test_validation_still_runs_without_a_database(cold_database: TestClient) -> None:
    """422 before 503: a malformed index is wrong whether or not Postgres is up."""
    assert cold_database.get("/hex/not-a-hex").status_code == 422


# ---- The pool is optional, not abandoned --------------------------------


async def test_the_pool_is_built_on_a_later_request_when_startup_could_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neon scales to zero, so the first connection after an idle period can
    time out. A process that started during one stayed degraded until somebody
    redeployed it, answering 503 with a healthy database on the other end."""
    built: list[str] = []

    async def create_pool(*args: object, **kwargs: object) -> str:
        built.append("pool")
        return "pool"

    assert await db.pool() is None

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    db.reset_for_tests()
    try:
        assert await db.pool() == "pool"
        # And once built, it is not rebuilt.
        assert await db.pool() == "pool"
        assert built == ["pool"]
    finally:
        db._pool = None
        db.reset_for_tests()


async def test_a_database_that_stays_down_is_not_dialled_on_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrying is worth a cold start and not worth a connection attempt per
    request while the database is genuinely gone."""
    attempts: list[str] = []

    async def create_pool(*args: object, **kwargs: object) -> str:
        attempts.append("try")
        raise OSError("refused")

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    db.reset_for_tests()
    try:
        assert await db.pool() is None
        assert await db.pool() is None
        assert len(attempts) == 1
    finally:
        db.reset_for_tests()


# ---- One provider client for the process --------------------------------


async def test_the_provider_client_is_built_once_and_closed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client per request leaves its connection pool and TLS sessions behind
    for the garbage collector, which under load is a slow leak of sockets."""
    from app import llm

    closed: list[str] = []

    class FakeClient:
        async def close(self) -> None:
            closed.append("closed")

    monkeypatch.setattr(llm, "_client", FakeClient())
    first = llm.client()

    assert llm.client() is first

    await llm.close()

    assert closed == ["closed"]
    assert llm._client is None
