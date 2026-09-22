"""What the endpoint returns for each way drafting can fail.

The service's failures were covered and the mapping from them to a status was
not, which is the half a user meets. Every one of these is a normal outcome --
a hexagon the pipeline does not trust, a draft the verifier threw away, a
provider having a bad afternoon -- and each has to read as an answer rather
than as a fault.

The service itself is stubbed. What is under test is the router.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, rate_limit
from app.assistant import retrieval, service, verifier
from app.assistant.context import HexContext
from app.assistant.guardrails import InsufficientConfidence
from app.assistant.structured import DraftRejected
from app.config import get_settings
from app.main import app
from app.routers import draft as draft_router

CELL = "88444600ddfffff"


class FakeConn:
    async def fetchrow(self, query: str, *args: Any) -> None:
        return None


class FakePool:
    """Enough of an asyncpg pool for `async with pool.acquire() as conn`."""

    def acquire(self) -> Any:
        class Acquired:
            async def __aenter__(self) -> FakeConn:
                return FakeConn()

            async def __aexit__(self, *exc: object) -> None:
                return None

        return Acquired()


def hexagon() -> HexContext:
    return HexContext(
        h3=CELL,
        parish="St. James",
        score=81.4,
        percentile=94.2,
        confidence=0.71,
        confidence_band="moderate",
        methodology_version="0.1.4",
        run_id=11,
    )


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A deployment with a key, a database and a scored hexagon."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    rate_limit.reset_all()

    async def pool() -> FakePool:
        return FakePool()

    async def load(conn: Any, h3: str) -> HexContext:
        return hexagon()

    monkeypatch.setattr(db, "pool", pool)
    monkeypatch.setattr(draft_router, "load_hex_context", load)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        rate_limit.reset_all()
        get_settings.cache_clear()


def fails_with(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    async def draft_for_hex(*args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(service, "draft_for_hex", draft_for_hex)


def post(client: TestClient) -> Any:
    return client.post("/draft", json={"h3": CELL, "document_type": "public_comment_letter"})


def test_an_insufficient_hexagon_is_409_and_not_an_error(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing about the request is malformed. The hexagon is real and the
    system declines to draft from it, which is a statement about the data."""
    fails_with(monkeypatch, InsufficientConfidence(CELL, "insufficient"))

    response = post(configured)

    assert response.status_code == 409
    assert response.json()["detail"]


def test_a_draft_the_verifier_threw_away_is_422(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fails_with(monkeypatch, verifier.DraftUnverifiable(verifier.Verification()))

    response = post(configured)

    assert response.status_code == 422
    assert "discarded rather than shown" in response.json()["detail"]


def test_a_judge_that_could_not_be_asked_is_422_rather_than_500(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fails_with(monkeypatch, service.VerificationFailed("UnexpectedModelBehavior: retries"))

    response = post(configured)

    assert response.status_code == 422
    assert "could not be checked" in response.json()["detail"]


def test_a_response_that_missed_the_schema_is_422(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fails_with(monkeypatch, DraftRejected("public_comment_letter", "not the schema"))

    response = post(configured)

    assert response.status_code == 422
    assert "required form" in response.json()["detail"]


def test_no_sealed_corpus_is_503(configured: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fails_with(monkeypatch, service.NoCorpus("No sealed statute corpus is loaded."))

    response = post(configured)

    assert response.status_code == 503
    assert "sealed statute corpus" in response.json()["detail"]


def test_a_provider_outage_is_503_rather_than_500(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fails_with(monkeypatch, service.ProviderUnavailable("connection error"))

    response = post(configured)

    assert response.status_code == 503
    assert "try again later" in response.json()["detail"]


def test_a_corpus_embedded_with_another_model_is_503(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment fault rather than a bad request, and one that otherwise
    fails quietly: retrieval returns plausible text in a meaningless order."""
    fails_with(monkeypatch, retrieval.EmbeddingModelMismatch("models disagree"))

    response = post(configured)

    assert response.status_code == 503
    assert "different model" in response.json()["detail"]


def test_a_draft_that_succeeds_is_200(
    configured: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from app.assistant.documents import (
        GeneratedDraft,
        Paragraph,
        PublicCommentLetter,
        StatuteCitation,
    )

    letter = PublicCommentLetter(
        recipient="LDEQ",
        subject="Comment",
        requested_action="Hold a hearing.",
        paragraphs=[
            Paragraph(
                text="A claim.",
                citations=[
                    StatuteCitation(
                        section="42 U.S.C. § 7661a",
                        document_id="usc-42-chap85",
                        proposition="Title V proceedings carry a participation right.",
                    )
                ],
            )
        ],
    )

    async def drafted(*args: Any, **kwargs: Any) -> Any:
        return service.DraftOutcome(
            draft=GeneratedDraft(
                document=letter,
                h3=CELL,
                confidence_band="moderate",
                methodology_version="0.1.4",
                corpus_version="corpus-1",
                prompt_version="v3",
                model="gpt-4o",
                generated_at=datetime(2026, 9, 11, tzinfo=UTC),
            ),
            from_cache=True,
        )

    monkeypatch.setattr(service, "draft_for_hex", drafted)

    response = post(configured)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "drafted"
    assert body["from_cache"] is True
    assert body["draft"]["document"]["draft_notice"]
