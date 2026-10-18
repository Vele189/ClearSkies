"""POST /draft — the drafting endpoint.

A POST, and not because it is fashionable to be RESTful about it. Two reasons,
and the second is the one that matters.

It is not idempotent from the client's point of view: the first call for a
hexagon spends money at a third-party API, and a GET is something browsers,
proxies, link previewers and prefetchers will issue on their own. A GET here
would let a crawler run up a bill by following links.

And **it must never sit behind the CDN**. A cached response would hand one
hexagon's draft to whoever asked next, and a draft is keyed to a hexagon that
somebody is about to act on. Railway's CDN caches GET responses; POST is the
part of that contract this endpoint relies on, and `.railway/railway.ts` says
so next to the service definition.

Every failure is a distinct status with a sentence a person can act on, because
the failures here are not exceptional. A refusal is normal. A hexagon the
pipeline does not trust is normal. Both need to read as an answer rather than as
a fault.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import db, hex_detail, llm, rate_limit, runs
from app.assistant import cost, retrieval, service, verifier
from app.assistant.context import HexContext
from app.assistant.documents import DOCUMENT_MODELS, DocumentType, GeneratedDraft
from app.assistant.guardrails import InsufficientConfidence, Refusal
from app.assistant.structured import DraftRejected
from app.config import get_settings
from app.h3_cell import H3Cell

log = logging.getLogger(__name__)

#: Shown to a reader in the drafting panel, so it says what it means for them.
DATA_UNAVAILABLE = "Our data service isn't available right now. Please try again in a few minutes."

router = APIRouter(tags=["draft"])

#: Named so the two limits count separately: a reader who has been clicking
#: around the map has not used up their drafts.
DRAFT = "draft"


def limiter() -> rate_limit.SlidingWindow:
    """This endpoint's window, built from the settings on first use.

    Not at import time, so a test or a deployment can change the limit and be
    obeyed. See app/rate_limit.py for what this does and does not promise.
    """
    settings = get_settings()
    return rate_limit.window_for(DRAFT, settings.draft_rate_limit, settings.draft_rate_window_s)


def enforce_rate_limit(request: Request) -> None:
    """429 with a Retry-After, or nothing at all."""
    key = rate_limit.client_key(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )
    wait = limiter().check(key)
    if wait is None:
        return
    seconds = max(int(math.ceil(wait)), 1)
    raise HTTPException(
        status_code=429,
        detail=(
            f"You've asked for several drafts in a short time. Each one costs money to "
            f"write, so we allow {limiter().limit} every {int(limiter().window_s)} "
            f"seconds. Please try again in {seconds} seconds."
        ),
        headers={"Retry-After": str(seconds)},
    )


class DraftRequest(BaseModel):
    h3: H3Cell = Field(
        description=(
            "H3 cell index at resolution 8, as fifteen lower-case hex digits, e.g. 88444600ddfffff."
        )
    )
    document_type: DocumentType
    request: str = Field(
        default="",
        max_length=2000,
        description=(
            "Optional free text about what the document should cover. The draft is "
            "about the hexagon, and this steers which passages are retrieved and what "
            "the document argues, so it is part of the cache key: a draft answers the "
            "request that produced it and is not served to somebody who asked for "
            "something else."
        ),
    )


class DraftResponse(BaseModel):
    """A verified draft, or the model's reasoned refusal to write one."""

    status: Literal["drafted", "refused"]
    draft: GeneratedDraft | None = None
    refusal: Refusal | None = None
    from_cache: bool = False


class Unavailable(BaseModel):
    detail: str


def _settings_or_503() -> tuple[str, str]:
    """The models to use, or a 503 that explains what is missing.

    `config.py` has anticipated an absent key since Phase 0: the service starts
    and this endpoint reports itself unavailable, rather than the whole API
    failing at import because one feature is unconfigured.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        # The reason is for whoever runs the deployment, so it goes to the log;
        # the reader is told what it means for them.
        log.warning("drafting requested but OPENAI_API_KEY is not set")
        raise HTTPException(
            status_code=503,
            detail=(
                "Document drafting isn't switched on for this site yet. Everything "
                "else works normally."
            ),
        )
    return settings.draft_model, settings.embedding_model


@router.post(
    "/draft",
    response_model=DraftResponse,
    responses={
        409: {"model": Unavailable, "description": "The hexagon cannot be drafted from"},
        422: {"model": Unavailable, "description": "The draft failed verification"},
        429: {"model": Unavailable, "description": "Too many drafts from this client"},
        503: {
            "model": Unavailable,
            "description": "Not configured, or the provider is unavailable",
        },
    },
)
async def create_draft(body: DraftRequest, request: Request) -> DraftResponse:
    """Draft one document about one hexagon, with every citation verified.

    The draft is not legal advice, has not been reviewed by a lawyer, and says so
    on its face. There is no endpoint that sends, files or publishes one.
    """
    draft_model, embedding_model = _settings_or_503()
    enforce_rate_limit(request)

    if body.document_type not in DOCUMENT_MODELS:  # pragma: no cover - Literal pins it
        raise HTTPException(status_code=422, detail=f"unknown document type {body.document_type}")

    p = await db.pool()
    if p is None:
        raise HTTPException(status_code=503, detail=DATA_UNAVAILABLE)

    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    # The key comes from the typed settings object, which reads `.env` as well
    # as the environment. `OpenAIChatModel` with no provider infers one, and the
    # inferred provider reads `os.environ["OPENAI_API_KEY"]` directly -- so a
    # deployment that configures the key the way this project documents, in
    # `.env`, satisfies the 503 check above and then raises inside the model
    # constructor. That is a 500 on the one endpoint CS-008 requires to degrade
    # rather than crash.
    #
    # Handing the provider the process's client fixes it and collapses two
    # configurations into one: the retrieval embeddings and the draft model
    # demonstrably use the same key and the same HTTP client. The client is the
    # process's rather than this request's; `app/llm.py` says why.
    client = llm.client()
    model = OpenAIChatModel(draft_model, provider=OpenAIProvider(openai_client=client))

    async with p.acquire() as conn:
        hex_context = await load_hex_context(conn, body.h3)

        try:
            outcome = await service.draft_for_hex(
                conn,
                client,
                model,
                embedding_model,
                hex_context,
                body.document_type,
                body.request,
            )
        except InsufficientConfidence as exc:
            # 409 rather than 422: nothing about the request is malformed. The
            # hexagon is real and the system declines to draft from it, which is
            # a statement about the data and not about the caller.
            raise HTTPException(status_code=409, detail=exc.explanation) from exc
        except service.NoCorpus as exc:
            log.error("drafting requested with no usable statute corpus: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Document drafting is unavailable because of a setup problem on our "
                    "side. Everything else works normally."
                ),
            ) from exc
        except retrieval.EmbeddingModelMismatch as exc:
            # A deployment fault, not a bad request: every draft it produced
            # would be retrieved from vectors in a different coordinate space
            # from the corpus's, which fails quietly rather than loudly.
            log.error("corpus and query embedding models disagree: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=(
                    "Document drafting is unavailable because of a setup problem on our "
                    "side. Everything else works normally."
                ),
            ) from exc
        except service.ProviderUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The AI service that writes drafts is unavailable right now, or we've "
                    "reached our spending limit for the moment. Nothing is wrong with your "
                    "request; please try again later."
                ),
            ) from exc
        except service.VerificationFailed as exc:
            # The citations were never checked, because the judge could not be
            # asked. Reported as 422 rather than 500 for the same reason as a
            # failed check: the draft is gone either way, and nothing about
            # this is a fault the caller can read as a bug in their request.
            log.warning("verification could not run: %s", exc)
            raise HTTPException(
                status_code=422,
                detail=(
                    "A draft was written, but we couldn't finish checking its sources, so "
                    "we threw it away rather than show you something unchecked. Trying "
                    "again may work."
                ),
            ) from exc
        except verifier.DraftUnverifiable as exc:
            # The draft existed and is being thrown away. It is not returned in
            # any form: see app/assistant/verifier.py for why a warning or a
            # stripped citation would both be worse.
            raise HTTPException(
                status_code=422,
                detail=(
                    "A draft was written, but at least one of its sources didn't hold up "
                    "when we checked it against the data and the law, so we threw it away "
                    "rather than show it to you. That is the checking doing its job. "
                    "Trying again may give a draft that passes."
                ),
            ) from exc
        except DraftRejected as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The assistant didn't produce a document in the expected format, so "
                    "nothing was shown. Trying again may work."
                ),
            ) from exc

    if outcome.refusal is not None:
        return DraftResponse(status="refused", refusal=outcome.refusal)

    return DraftResponse(status="drafted", draft=outcome.draft, from_cache=outcome.from_cache)


class SpendReport(BaseModel):
    """What the assistant has cost this calendar month, estimated."""

    usd: float = Field(description="Estimated from token counts, not the provider's invoice.")
    tokens: int
    calls: int
    note: str = (
        "Indicative only. The hard cap is set with the provider, because a limit "
        "the application enforces is a limit that stops working when the "
        "application has a bug."
    )


@router.get("/draft/spend", response_model=SpendReport)
async def spend() -> SpendReport:
    """Month-to-date usage, so the bill is legible before it arrives."""
    p = await db.pool()
    if p is None:
        raise HTTPException(status_code=503, detail=DATA_UNAVAILABLE)
    async with p.acquire() as conn:
        month = await cost.month_to_date(conn)
    return SpendReport(usd=round(month.usd, 4), tokens=month.tokens, calls=month.calls)


async def load_hex_context(conn: Any, h3: str) -> HexContext:
    """The hexagon's data, as the model will see it.

    Deliberately the *same* assembly the drill-down panel uses, through
    `hex_detail.load`, rather than a query written for drafting. If the two ever
    diverged, a draft would cite figures nobody could find on the map it came
    from, and reconciling them afterwards would mean re-reading two queries to
    work out which was right.
    """
    run = await runs.current(conn)
    if run is None:
        raise HTTPException(
            status_code=503,
            detail="No results have been published yet, so there is nothing to draft about.",
        )

    detail = await hex_detail.load(conn, h3, run)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="We don't have a result for this area, so there is nothing to draft about.",
        )

    return HexContext(
        h3=detail.h3,
        parish=detail.parish,
        run_id=run.run_id,
        score=detail.score,
        percentile=detail.percentile,
        confidence=detail.confidence.value,
        confidence_band=detail.confidence.band,
        methodology_version=detail.methodology_version,
        indicators=[i.model_dump() for i in detail.indicators],
        demographics=detail.demographics.model_dump(),
        facilities=[f.model_dump() for f in detail.facilities],
        facility_count=detail.facility_count,
        data_vintage=detail.data_vintage,
    )
