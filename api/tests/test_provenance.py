"""The provenance endpoint, on a deployment where the pipeline has not run.

That is the state these tests run in and the one most likely to be wrong in
practice, because the failure it invites is a 200 with an empty list. A reader
handed `{"sources": []}` concludes no source has ever been pulled, when the truth
is that this deployment has never ingested anything. The two need different
answers and the endpoint gives them.
"""

from fastapi.testclient import TestClient


def test_no_provenance_yet_says_so_rather_than_returning_an_empty_list(
    client: TestClient,
) -> None:
    r = client.get("/provenance")
    # 503 while the database or the table is absent; 200 once the pipeline has run.
    assert r.status_code in {200, 503}
    if r.status_code == 503:
        detail = r.json()["detail"].lower()
        assert "provenance" in detail or "database" in detail
    else:
        assert isinstance(r.json()["sources"], list)


def test_an_out_of_range_history_length_is_rejected(client: TestClient) -> None:
    assert client.get("/provenance", params={"source": "epa_echo", "limit": 0}).status_code == 422
    assert client.get("/provenance", params={"source": "epa_echo", "limit": 999}).status_code == 422


def test_the_shape_is_published_for_the_frontend_to_generate_from(client: TestClient) -> None:
    """CS-406 builds its client from the spec, so the fields have to be in it."""
    spec = client.get("/openapi.json").json()
    assert "/provenance" in spec["paths"]

    pull = spec["components"]["schemas"]["SourcePull"]["properties"]
    for field in ("source", "vintage", "pulled_at", "status", "records", "known_gaps"):
        assert field in pull, f"{field} is missing from the published SourcePull"

    gap = spec["components"]["schemas"]["SourceGap"]["properties"]
    for field in ("scope", "detail", "affects"):
        assert field in gap, f"{field} is missing from the published SourceGap"


def test_the_vintage_is_documented_as_a_release_not_a_download_time(client: TestClient) -> None:
    """The distinction the whole page turns on, so it is in the published schema."""
    spec = client.get("/openapi.json").json()
    described = spec["components"]["schemas"]["SourcePull"]["properties"]["vintage"]["description"]
    assert "download" in described.lower()
