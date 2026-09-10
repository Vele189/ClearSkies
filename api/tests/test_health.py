def test_health_reports_degraded_without_a_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["pilot_state"] == "LA"
    if body["database"] == "unavailable":
        assert body["extensions"] == []
        assert body["notes"]


def test_openapi_document_builds(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/hex/{h3_index}" in r.json()["paths"]
