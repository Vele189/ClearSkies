from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_health_reports_degraded_without_a_database(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    # Coverage is read from `scored_state` since 0031, so there is no
    # configured value to assert here. That is the point: a deploy reporting a
    # pilot state out of its own environment was claiming coverage it had never
    # checked against the database it serves.
    assert isinstance(body["scored_states"], list)
    if body["database"] == "unavailable":
        assert body["extensions"] == []
        assert body["scored_states"] == []
        assert body["notes"]


def test_openapi_document_builds(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/hex/{h3_index}" in r.json()["paths"]


class _HealthConn:
    """Answers the four questions /health asks, with a current run on file."""

    def __init__(self, current: dict[str, int] | None) -> None:
        self.current = current
        self.queries: list[str] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, str]]:
        self.queries.append(query)
        if "clearskies_extensions" in query:
            return [{"name": n, "version": "1"} for n in ("postgis", "h3", "vector")]
        return [{"usps": "LA", "name": "Louisiana"}]

    async def fetchval(self, query: str, *args: object) -> object:
        self.queries.append(query)
        return True

    async def fetchrow(self, query: str, *args: object) -> dict[str, int] | None:
        self.queries.append(query)
        return self.current


def _client_with(monkeypatch: pytest.MonkeyPatch, conn: _HealthConn) -> TestClient:
    class Pool:
        def acquire(self) -> AbstractAsyncContextManager[_HealthConn]:
            @asynccontextmanager
            async def acquired() -> AsyncIterator[_HealthConn]:
                yield conn

            return acquired()

    async def pool() -> Pool:
        return Pool()

    monkeypatch.setattr(db, "pool", pool)
    return TestClient(app)


def test_health_counts_the_current_run_not_every_run_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    # Counting hex_score added up every run ever kept: 345,149 for a state
    # whose current run ranked 19,881. The figure is the run's own.
    conn = _HealthConn(current={"scored_hexes": 19881})
    with _client_with(monkeypatch, conn) as client:
        body = client.get("/health").json()

    assert body["scored_hexes"] == 19881
    assert body["status"] == "ok"
    assert not any("count(*) FROM hex_score" in q for q in conn.queries)


def test_health_says_when_no_run_is_promoted(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _HealthConn(current=None)
    with _client_with(monkeypatch, conn) as client:
        body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert any("promoted" in note for note in body["notes"])
