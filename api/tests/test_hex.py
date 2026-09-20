from fastapi.testclient import TestClient


def test_malformed_index_is_rejected(client: TestClient) -> None:
    r = client.get("/hex/not-a-cell")
    assert r.status_code == 422


def test_wrong_resolution_is_rejected_with_an_explanation(client: TestClient) -> None:
    # A resolution 7 cell. ClearSkies scores resolution 8 only.
    r = client.get("/hex/87444600dffffff")
    assert r.status_code == 422
    assert "resolution" in r.json()["detail"]


def test_valid_cell_reports_no_data_rather_than_guessing(client: TestClient) -> None:
    r = client.get("/hex/88444600ddfffff")
    # 503 while the pipeline has not run, 404 once it has but the cell is unscored.
    assert r.status_code in {404, 503}


def test_indicators_endpoint_publishes_the_running_configuration(client: TestClient) -> None:
    r = client.get("/indicators")
    assert r.status_code == 200
    body = r.json()
    assert len(body["indicators"]) == 15
    assert body["group_weights"]["environmental_effects"] == 0.5
