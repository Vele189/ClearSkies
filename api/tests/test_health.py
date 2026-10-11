from fastapi.testclient import TestClient


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
