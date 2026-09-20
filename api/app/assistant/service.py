"""One drafting request, end to end.

The order of operations is the design, and every step is placed where it is
because of what it costs to be wrong later:

1. **Band check.** Before anything is spent. An insufficient-confidence hexagon
   never reaches retrieval, let alone the model.
2. **Cache.** Keyed on the hexagon, the document type and the three versions
   that decide what a draft says. A hit skips everything below it, including
   verification, because nothing that failed verification was ever written.
3. **Retrieve.** From the sealed corpus only.
4. **Generate.** Structured output, with refusal available.
5. **Verify.** Every citation, against the database. A draft that fails is
   logged and discarded.
6. **Store.** Only what passed.

Cost is recorded at every exit, including the failures. Cost is incurred by
attempts, not by successes.

The thing this module refuses to do is return a partially good document. There
is no path through it that renders a draft with a warning attached, and no path
that strips a bad citation and returns the rest. Both were considered and both
are worse than failing: a warning is read once and then forgotten by whoever
forwards the document, and a stripped citation leaves the remaining claims
resting on nothing with no sign anything was removed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.models import Model

from app.assistant import cost, prompts, retrieval, verifier
from app.assistant.context import HexContext, build_prompt
from app.assistant.documents import DraftDocument, GeneratedDraft, model_for
from app.assistant.guardrails import Refusal, check_band
from app.assistant.structured import DraftRejected, generate, model_label

log = logging.getLogger(__name__)


class NoCorpus(RuntimeError):
    """Nothing is sealed, so no citation could be verified even if one were made."""


class ProviderUnavailable(RuntimeError):
    """The provider refused the call: rate limit, spend cap, or an outage.

    Separate from every other failure because the user's next step is different.
    A verifier rejection means asking again will probably fail the same way; a
    provider limit means asking again later will probably work, and the message
    should say which.
    """

    def __init__(self, detail: str, retryable: bool = True) -> None:
        self.detail = detail
        self.retryable = retryable
        super().__init__(detail)


@dataclass
class DraftOutcome:
    """What happened, in a form the router can turn into a response."""

    draft: GeneratedDraft | None = None
    refusal: Refusal | None = None
    from_cache: bool = False
    verification: verifier.Verification | None = None
    usd: float = 0.0

    @property
    def served(self) -> bool:
        return self.draft is not None


CACHE_LOOKUP = """
SELECT document, model, confidence_band, generated_at
  FROM draft
 WHERE h3 = $1 AND document_type = $2
   AND methodology_version = $3 AND corpus_version = $4 AND prompt_version = $5
"""

CACHE_STORE = """
INSERT INTO draft (
    h3, document_type, methodology_version, corpus_version, prompt_version,
    model, confidence_band, document, request_tokens, response_tokens
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
ON CONFLICT (h3, document_type, methodology_version, corpus_version, prompt_version)
DO NOTHING
"""


async def cached(
    conn: Any,
    h3: str,
    document_type: str,
    methodology_version: str,
    corpus_version: str,
    prompt_version: str,
) -> GeneratedDraft | None:
    """A previously verified draft for exactly this question, or None.

    No re-verification on a hit. Only drafts that passed are stored, and the
    corpus version is part of the key, so the corpus a cached draft was verified
    against is the corpus that is still active.
    """
    row = await conn.fetchrow(
        CACHE_LOOKUP, h3, document_type, methodology_version, corpus_version, prompt_version
    )
    if row is None:
        return None

    payload = row["document"]
    document = model_for(document_type).model_validate(
        json.loads(payload) if isinstance(payload, str) else payload
    )
    return GeneratedDraft(
        document=document,  # type: ignore[arg-type]
        h3=h3,
        confidence_band=row["confidence_band"],
        methodology_version=methodology_version,
        corpus_version=corpus_version,
        prompt_version=prompt_version,
        model=row["model"],
        generated_at=row["generated_at"],
    )


async def store(
    conn: Any,
    draft: GeneratedDraft,
    request_tokens: int,
    response_tokens: int,
) -> None:
    await conn.execute(
        CACHE_STORE,
        draft.h3,
        draft.document.document_type,
        draft.methodology_version,
        draft.corpus_version,
        draft.prompt_version,
        draft.model,
        draft.confidence_band,
        draft.document.stored_json(),
        request_tokens,
        response_tokens,
    )


def is_provider_limit(exc: Exception) -> bool:
    """Whether a failure is the provider saying no, rather than a bug.

    Matched on the exception's name and message rather than on an imported
    class, so that this module does not depend on the provider SDK's exception
    hierarchy. That hierarchy changes between major versions, and the failure
    mode of getting it wrong is a 500 where a legible "try later" belonged.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "ratelimit" in name
        or "rate limit" in text
        or "quota" in text
        or "insufficient_quota" in text
        or "billing" in text
        or "429" in text
    )


async def draft_for_hex(
    conn: Any,
    client: Any,
    draft_model: Model | str,
    embedding_model: str,
    hex_context: HexContext,
    document_type: str,
    request: str,
    methodology_version: str,
    prompt_version: str = prompts.CURRENT_VERSION,
) -> DraftOutcome:
    """Produce one verified draft, serve one from the cache, or fail saying why."""
    h3 = hex_context.h3

    # 1. Before anything is spent.
    check_band(h3, hex_context.confidence_band)

    corpus_version = await retrieval.active_version(conn)
    if corpus_version is None:
        raise NoCorpus(
            "No sealed statute corpus is loaded, so no citation could be verified. "
            "Run the corpus ingestion before enabling drafting."
        )

    # 2. Cache.
    hit = await cached(conn, h3, document_type, methodology_version, corpus_version, prompt_version)
    if hit is not None:
        await cost.record(
            conn,
            purpose="generation",
            model=hit.model,
            request_tokens=0,
            response_tokens=0,
            outcome="cached",
            h3=h3,
            document_type=document_type,
        )
        return DraftOutcome(draft=hit, from_cache=True)

    prompt = prompts.load(document_type, prompt_version)
    model_name = model_label(draft_model)

    # 3. Retrieve.
    try:
        passages = await retrieval.retrieve_for(
            conn, client, embedding_model, document_type, request
        )
    except Exception as exc:
        if is_provider_limit(exc):
            raise ProviderUnavailable(str(exc)) from exc
        raise

    # 4. Generate.
    try:
        result = await generate(
            document_type,
            draft_model,
            prompt.text,
            build_prompt(hex_context, retrieval.as_context(passages), request),
        )
    except DraftRejected as exc:
        await cost.record(
            conn,
            purpose="generation",
            model=model_name,
            request_tokens=0,
            response_tokens=0,
            outcome="schema_rejected",
            h3=h3,
            document_type=document_type,
            detail=exc.reason,
        )
        raise
    except Exception as exc:
        if is_provider_limit(exc):
            await cost.record(
                conn,
                purpose="generation",
                model=model_name,
                request_tokens=0,
                response_tokens=0,
                outcome="provider_error",
                h3=h3,
                document_type=document_type,
                detail=str(exc)[:500],
            )
            raise ProviderUnavailable(str(exc)) from exc
        raise

    usd = await cost.record(
        conn,
        purpose="generation",
        model=model_name,
        request_tokens=result.request_tokens,
        response_tokens=result.response_tokens,
        outcome="refused" if result.refused else "generated",
        h3=h3,
        document_type=document_type,
    )

    if result.refused:
        assert result.refusal is not None
        return DraftOutcome(refusal=result.refusal, usd=usd)

    document = result.document
    assert isinstance(document, DraftDocument)

    # 5. Verify. Nothing that fails here is ever rendered.
    verification = await verifier.verify_document(conn, draft_model, document, h3)
    if not verification.verified:
        await verifier.log_rejections(
            conn, verification, h3, document_type, corpus_version, prompt_version, model_name
        )
        await cost.record(
            conn,
            purpose="verification",
            model=model_name,
            request_tokens=0,
            response_tokens=0,
            outcome="unverifiable",
            h3=h3,
            document_type=document_type,
            detail=f"{len(verification.failures)} citation(s) failed",
        )
        raise verifier.DraftUnverifiable(verification)

    stamped = GeneratedDraft(
        document=document,  # type: ignore[arg-type]
        h3=h3,
        confidence_band=hex_context.confidence_band,  # type: ignore[arg-type]
        methodology_version=methodology_version,
        corpus_version=corpus_version,
        prompt_version=prompt_version,
        model=model_name,
        generated_at=datetime.now(UTC),
    )

    # 6. Store only what passed.
    await store(conn, stamped, result.request_tokens, result.response_tokens)
    return DraftOutcome(draft=stamped, verification=verification, usd=usd)
