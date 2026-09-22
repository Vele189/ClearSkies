"""The drafting endpoint, its cache, and the ways it declines.

Most of the surface here is failure, and that is the point: a refusal is normal,
a hexagon the pipeline does not trust is normal, and both have to read as an
answer rather than as a fault. Each gets its own status and a sentence somebody
can act on.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.assistant import cost, prompts, service
from app.assistant.context import HexContext
from app.assistant.documents import (
    GeneratedDraft,
    Paragraph,
    PublicCommentLetter,
    StatuteCitation,
)
from app.assistant.guardrails import InsufficientConfidence
from app.assistant.service import DEFAULT_REQUESTS, default_request
from app.config import get_settings
from app.main import app

CITATION = StatuteCitation(
    section="42 U.S.C. § 7661a",
    document_id="usc-42-chap85",
    proposition="Title V proceedings carry a public participation right.",
)


def letter() -> PublicCommentLetter:
    return PublicCommentLetter(
        recipient="LDEQ",
        subject="Comment",
        requested_action="Hold a hearing.",
        paragraphs=[Paragraph(text="A claim.", citations=[CITATION])],
    )


def hexagon(band: str = "moderate", run_id: int | None = 11) -> HexContext:
    return HexContext(
        h3="88444600ddfffff",
        parish="St. James",
        score=81.4,
        percentile=94.2,
        confidence=0.71,
        confidence_band=band,
        methodology_version="0.1.4",
        run_id=run_id,
    )


def stamped() -> GeneratedDraft:
    return GeneratedDraft(
        document=letter(),
        h3="88444600ddfffff",
        confidence_band="moderate",
        methodology_version="0.1.4",
        corpus_version="appendix-b-test",
        prompt_version="v1",
        model="gpt-4o",
        generated_at=datetime(2026, 9, 11, tzinfo=UTC),
    )


# ---- The 503 that a missing key produces -------------------------------


def test_an_unconfigured_deployment_says_so_rather_than_failing_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config.py has anticipated an absent key since Phase 0. The API starts and
    this one endpoint reports itself unavailable.

    The key is cleared explicitly. `Settings` reads `.env`, which this repository
    documents as where a developer puts their key and which is symlinked into
    `api/`, so without this the test asserts nothing on any machine that has one
    -- it passed only where the file was absent, and failed everywhere else for
    a reason that had nothing to do with the behaviour under test. An
    environment variable takes precedence over `.env` in pydantic-settings, so
    setting it empty is what "unconfigured" has to mean here.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post(
            "/draft", json={"h3": "88444600ddfffff", "document_type": "public_comment_letter"}
        )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert "Everything else in the API works normally" in response.json()["detail"]

    # The cache is shared with every other test in this process, and the next
    # one to read it should not inherit an unconfigured deployment.
    get_settings.cache_clear()


def test_the_rest_of_the_api_is_unaffected_by_the_assistant_being_off() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/indicators").status_code == 200


# ---- The endpoint is a POST --------------------------------------------


def test_drafting_is_a_post_and_not_a_get() -> None:
    """A GET would let a browser, proxy or link previewer spend money by
    following a link, and would let the CDN hand one hexagon's draft to whoever
    asked next."""
    paths = app.openapi()["paths"]

    assert set(paths["/draft"]) == {"post"}


def test_the_spend_report_is_a_get_because_it_costs_nothing() -> None:
    assert set(app.openapi()["paths"]["/draft/spend"]) == {"get"}


# ---- Defaults ------------------------------------------------------------


def test_every_document_type_has_a_default_request() -> None:
    """The request text is optional: a user who clicks "draft a comment letter"
    and types nothing still gets a comment letter."""
    from app.assistant.documents import DOCUMENT_MODELS

    assert set(DEFAULT_REQUESTS) == set(DOCUMENT_MODELS)
    for document_type in DOCUMENT_MODELS:
        assert default_request(document_type)


# ---- The cache -----------------------------------------------------------


class FakeConn:
    """The cache and the usage log, as far as the service reads them.

    The cache is a dictionary on the real key, because half of what is under
    test here is which requests share a row.
    """

    def __init__(
        self,
        row: dict[str, Any] | None = None,
        corpus: str | None = "corpus-1",
        key: tuple[Any, ...] | None = None,
    ) -> None:
        self.rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        if row is not None:
            self.rows[key if key is not None else cache_key()] = row
        self.corpus = corpus
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.looked_up: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "statute_corpus_version" in query:
            return None if self.corpus is None else {"version": self.corpus}
        if "FROM draft" in query:
            self.looked_up.append(args)
            return self.rows.get(args)
        if "llm_usage" in query:
            return {"usd": 0.0, "tokens": 0, "calls": 0}
        return None

    async def execute(self, query: str, *args: Any) -> None:
        self.executed.append((query, args))


def cache_key(
    request: str = "Draft it.",
    run_id: int = 11,
    h3: str = "88444600ddfffff",
    document_type: str = "public_comment_letter",
) -> tuple[Any, ...]:
    """The lookup's arguments, in the order the query takes them."""
    return (
        h3,
        document_type,
        run_id,
        service.request_digest(request),
        "0.1.4",
        "corpus-1",
        prompts.CURRENT_VERSION,
    )


def cached_row() -> dict[str, Any]:
    return {
        "document": json.loads(letter().stored_json()),
        "model": "gpt-4o",
        "confidence_band": "moderate",
        "generated_at": datetime(2026, 9, 11, tzinfo=UTC),
    }


class Embedded(Exception):
    """Retrieval was reached, which means the cache missed.

    The service embeds the request before anything else it could do, so a
    client that raises here marks the miss without needing a model, a vector
    index or a corpus.
    """


class FakeClient:
    class embeddings:
        @staticmethod
        async def create(**kwargs: Any) -> Any:
            raise Embedded


async def draft(conn: FakeConn, request: str = "Draft it.", **overrides: Any) -> Any:
    return await service.draft_for_hex(
        conn,
        overrides.pop("client", FakeClient()),
        "gpt-4o",
        "text-embedding-3-small",
        overrides.pop("hex_context", hexagon()),
        "public_comment_letter",
        request,
        **overrides,
    )


async def missed(conn: FakeConn, request: str = "Draft it.", **overrides: Any) -> bool:
    """Whether this request went past the cache and on to retrieval."""
    with pytest.raises(Embedded):
        await draft(conn, request, **overrides)
    return True


async def test_a_repeat_request_is_served_from_the_cache() -> None:
    conn = FakeConn(row=cached_row())

    outcome = await draft(conn)

    assert outcome.from_cache
    assert outcome.draft is not None
    document = outcome.draft.document
    assert isinstance(document, PublicCommentLetter)
    assert document.recipient == "LDEQ"


async def test_a_cache_hit_is_still_recorded_as_a_call() -> None:
    """Zero tokens, but the fact that somebody asked is worth having."""
    conn = FakeConn(row=cached_row())

    await draft(conn)

    logged = [args for query, args in conn.executed if "llm_usage" in query]
    assert logged
    assert logged[0][7] == "cached"


async def test_an_insufficient_hexagon_never_reaches_the_cache_or_the_model() -> None:
    conn = FakeConn()

    with pytest.raises(InsufficientConfidence):
        await draft(conn, hex_context=hexagon(band="insufficient"))

    assert conn.executed == []


async def test_no_sealed_corpus_is_refused_before_anything_is_spent() -> None:
    """No corpus means no citation could be verified even if one were made."""
    conn = FakeConn(corpus=None)

    with pytest.raises(service.NoCorpus, match="No sealed statute corpus"):
        await draft(conn)


# ---- What the cache is keyed on ------------------------------------------


async def test_two_different_requests_do_not_share_a_cache_row() -> None:
    """The request steers retrieval and generation, so a draft written for one
    is an answer to a question the next requester did not ask. Under the old
    key the first person's free text was served to everybody after them."""
    conn = FakeConn(row=cached_row(), key=cache_key("Write about the flare."))

    assert (await draft(conn, "Write about the flare.")).from_cache
    assert await missed(conn, "Write about the odour complaints.")


async def test_the_same_request_typed_untidily_still_hits() -> None:
    """Whitespace is not a different question, and a key that thought so would
    miss often enough to be no cache at all."""
    conn = FakeConn(row=cached_row(), key=cache_key("Write about the flare."))

    assert (await draft(conn, "  Write about\n  the flare. ")).from_cache


async def test_no_request_is_keyed_on_the_empty_string() -> None:
    conn = FakeConn(row=cached_row(), key=cache_key(""))

    assert (await draft(conn, "")).from_cache
    assert service.request_digest("") == service.request_digest("   ")


async def test_a_new_run_misses_the_cache() -> None:
    """A re-run under the same methodology version produces new scores for the
    same hexagon, and a draft describing the old ones is about figures the map
    no longer shows."""
    conn = FakeConn(row=cached_row(), key=cache_key(run_id=11))

    assert (await draft(conn, hex_context=hexagon(run_id=11))).from_cache
    assert await missed(conn, hex_context=hexagon(run_id=12))


async def test_a_context_no_run_produced_is_not_cached_at_all() -> None:
    """The citation audit drafts from fixtures. There is no run to key them on,
    and keying them on nothing would let a fixture's draft be served for a real
    hexagon."""
    conn = FakeConn(row=cached_row(), key=cache_key())

    assert await missed(conn, hex_context=hexagon(run_id=None))
    assert conn.looked_up == []


def test_the_draft_is_stamped_with_the_runs_methodology_version() -> None:
    """Not the application's constant. They differ exactly when the code has
    moved on from the run it is serving, and the draft describes the run."""
    from app.methodology import METHODOLOGY_VERSION

    context = hexagon()

    assert context.methodology_version == "0.1.4"
    assert context.methodology_version != METHODOLOGY_VERSION


# ---- Cost ----------------------------------------------------------------


def test_a_known_model_is_priced() -> None:
    assert cost.estimate_usd("gpt-4o", 1_000_000, 0) == pytest.approx(2.50)
    assert cost.estimate_usd("gpt-4o", 0, 1_000_000) == pytest.approx(10.00)


def test_an_unknown_model_costs_nothing_rather_than_a_confident_guess() -> None:
    """The estimate gates nothing, so a visibly zero cost is safer than a
    number that looks authoritative and is wrong."""
    assert cost.estimate_usd("some-future-model", 1_000_000, 1_000_000) == 0.0


def test_embeddings_have_no_output_price() -> None:
    assert cost.estimate_usd("text-embedding-3-small", 0, 1_000_000) == 0.0


def test_the_model_name_recorded_is_the_model_not_its_class() -> None:
    """`str()` on a Pydantic AI model gives `OpenAIChatModel()`, for every
    model. Using it stamped every draft's provenance with a string identifying
    nothing, and made every cost estimate zero because no price table has an
    entry for a class name. Both failures are silent."""
    from app.assistant.structured import model_label

    class FakeModel:
        model_name = "gpt-4o"

        def __str__(self) -> str:
            return "FakeModel()"

    # A stand-in rather than a real provider model: constructing one needs an
    # API key, and what is under test is which attribute is read.
    label = model_label(FakeModel())  # type: ignore[arg-type]

    assert label == "gpt-4o"
    assert cost.estimate_usd(label, 1_000_000, 0) > 0


def test_a_plain_model_name_is_passed_through() -> None:
    from app.assistant.structured import model_label

    assert model_label("gpt-4o-mini") == "gpt-4o-mini"


def test_the_month_starts_at_the_first() -> None:
    start = cost.month_start(datetime(2026, 9, 17, 13, 45, tzinfo=UTC))

    assert start == datetime(2026, 9, 1, tzinfo=UTC)


# ---- Provider limits -----------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("Error code: 429 - rate limit reached"),
        RuntimeError("You exceeded your current quota"),
        RuntimeError("insufficient_quota: check your billing"),
        type("RateLimitError", (Exception,), {})("slow down"),
    ],
)
def test_a_provider_limit_is_recognised_without_importing_the_sdk(exc: Exception) -> None:
    """Matched on name and message rather than an imported class, because that
    hierarchy changes between major versions and getting it wrong turns a
    legible "try later" into a 500."""
    assert service.is_provider_limit(exc)


def test_an_ordinary_bug_is_not_mistaken_for_a_provider_limit() -> None:
    assert not service.is_provider_limit(KeyError("h3"))
    assert not service.is_provider_limit(ValueError("bad input"))


# ---- The draft that is thrown away ---------------------------------------


def test_a_stamped_draft_records_all_three_versions() -> None:
    draft = stamped()

    assert draft.corpus_version == "appendix-b-test"
    assert draft.prompt_version == "v1"
    assert draft.methodology_version == "0.1.4"
    assert draft.review_required is True
