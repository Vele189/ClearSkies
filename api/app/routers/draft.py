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
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, hex_detail, runs
from app.assistant import cost, service, verifier
from app.assistant.context import HexContext
from app.assistant.documents import DOCUMENT_MODELS, DocumentType, GeneratedDraft
from app.assistant.guardrails import InsufficientConfidence, Refusal
from app.assistant.structured import DraftRejected
from app.config import get_settings
from app.methodology import METHODOLOGY_VERSION

log = logging.getLogger(__name__)

router = APIRouter(tags=["draft"])


class DraftRequest(BaseModel):
    h3: str = Field(description="H3 cell index at resolution 8.")
    document_type: DocumentType
    request: str = Field(
        default="",
        max_length=2000,
        description=(
            "Optional free text about what the document should cover. The draft is "
            "about the hexagon; this steers emphasis and is not part of the cache key, "
            "because two people asking for the same document in different words should "
            "get the same document."
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
        raise HTTPException(
            status_code=503,
            detail=(
                "The drafting assistant is not configured on this deployment: no "
                "OPENAI_API_KEY is set. Everything else in the API works normally."
            ),
        )
    return settings.draft_model, settings.embedding_model


@router.post(
    "/draft",
    response_model=DraftResponse,
    responses={
        409: {"model": Unavailable, "description": "The hexagon cannot be drafted from"},
        422: {"model": Unavailable, "description": "The draft failed verification"},
        503: {
            "model": Unavailable,
            "description": "Not configured, or the provider is unavailable",
        },
    },
)
async def create_draft(body: DraftRequest) -> DraftResponse:
    """Draft one document about one hexagon, with every citation verified.

    The draft is not legal advice, has not been reviewed by a lawyer, and says so
    on its face. There is no endpoint that sends, files or publishes one.
    """
    draft_model, embedding_model = _settings_or_503()

    if body.document_type not in DOCUMENT_MODELS:  # pragma: no cover - Literal pins it
        raise HTTPException(status_code=422, detail=f"unknown document type {body.document_type}")

    p = db.pool()
    if p is None:
        raise HTTPException(status_code=503, detail="Database unavailable. Check GET /health.")

    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel

    client = AsyncOpenAI(api_key=get_settings().openai_api_key)

    async with p.acquire() as conn:
        hex_context = await load_hex_context(conn, body.h3)

        try:
            outcome = await service.draft_for_hex(
                conn,
                client,
                OpenAIChatModel(draft_model),
                embedding_model,
                hex_context,
                body.document_type,
                body.request or default_request(body.document_type),
                METHODOLOGY_VERSION,
            )
        except InsufficientConfidence as exc:
            # 409 rather than 422: nothing about the request is malformed. The
            # hexagon is real and the system declines to draft from it, which is
            # a statement about the data and not about the caller.
            raise HTTPException(status_code=409, detail=exc.explanation) from exc
        except service.NoCorpus as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except service.ProviderUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The language model provider is temporarily unavailable or the "
                    "spend cap for this deployment has been reached. Nothing is wrong "
                    "with your request; try again later."
                ),
            ) from exc
        except verifier.DraftUnverifiable as exc:
            # The draft existed and is being thrown away. It is not returned in
            # any form: see app/assistant/verifier.py for why a warning or a
            # stripped citation would both be worse.
            raise HTTPException(
                status_code=422,
                detail=(
                    "A draft was produced but at least one of its citations could not "
                    "be verified against the data and the statute corpus, so it was "
                    "discarded rather than shown. This is the system working as "
                    "intended. Trying again may produce a draft that verifies."
                ),
            ) from exc
        except DraftRejected as exc:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The model did not produce a document in the required form, so "
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
    p = db.pool()
    if p is None:
        raise HTTPException(status_code=503, detail="Database unavailable. Check GET /health.")
    async with p.acquire() as conn:
        month = await cost.month_to_date(conn)
    return SpendReport(usd=round(month.usd, 4), tokens=month.tokens, calls=month.calls)


DEFAULT_REQUESTS: dict[str, str] = {
    "public_comment_letter": (
        "Draft a public comment letter about the permitted sources affecting this "
        "hexagon, based only on the supplied data and passages."
    ),
    "agency_complaint_draft": (
        "Draft an administrative complaint about the cumulative burden recorded for "
        "this hexagon, based only on the supplied data and passages."
    ),
    "community_briefing_sheet": (
        "Draft a plain-language briefing sheet for residents of this hexagon, based "
        "only on the supplied data and passages."
    ),
    "journalist_fact_sheet": (
        "Draft a fact sheet for a reporter covering this hexagon, based only on the "
        "supplied data and passages."
    ),
}


def default_request(document_type: str) -> str:
    return DEFAULT_REQUESTS[document_type]


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
            detail=(
                "No scored data yet, so there is nothing to draft about. The Phase 1 "
                "ingestion and Phase 2 scoring steps have not run for this deployment. "
                "See GET /health."
            ),
        )

    detail = await hex_detail.load(conn, h3, run)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No scored hex {h3} in the pilot state.")

    return HexContext(
        h3=detail.h3,
        parish=detail.parish,
        score=detail.score,
        percentile=detail.percentile,
        confidence=detail.confidence.value,
        confidence_band=detail.confidence.band,
        methodology_version=detail.methodology_version,
        indicators=[i.model_dump() for i in detail.indicators],
        demographics=detail.demographics.model_dump(),
        facilities=[f.model_dump() for f in detail.facilities],
        data_vintage=detail.data_vintage,
    )
