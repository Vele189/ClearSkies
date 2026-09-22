"""One drafting request, end to end.

The order of operations is the design, and every step is placed where it is
because of what it costs to be wrong later:

1. **Band check.** Before anything is spent. An insufficient-confidence hexagon
   never reaches retrieval, let alone the model.
2. **Cache.** Keyed on everything that decides what the draft says: the
   hexagon, the document type, the scored run, the requester's free text, and
   the three versions. A hit skips everything below it, including verification,
   because nothing that failed verification was ever written.
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

import hashlib
import json
import logging
import unicodedata
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


class VerificationFailed(RuntimeError):
    """The judge could not be asked, so no citation could be checked.

    Distinct from `DraftUnverifiable`, which means the citations *were* checked
    and one of them failed. This means the check did not happen: the judge
    returned something that is not a judgement, ran out of retries, or timed
    out. Both end the same way -- the draft is discarded -- because an unchecked
    citation and a failed one are equally unfit to show, and this file's rule is
    that the only safe failure is no document.
    """


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
 WHERE h3 = $1 AND document_type = $2 AND run_id = $3 AND request_sha256 = $4
   AND methodology_version = $5 AND corpus_version = $6 AND prompt_version = $7
"""

CACHE_STORE = """
INSERT INTO draft (
    h3, document_type, run_id, request_sha256,
    methodology_version, corpus_version, prompt_version,
    model, confidence_band, document, request_tokens, response_tokens
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
ON CONFLICT (h3, document_type, run_id, request_sha256,
             methodology_version, corpus_version, prompt_version)
DO NOTHING
"""


def request_digest(request: str) -> str:
    """The cache key's share of the requester's free text.

    Normalised first, so that trailing spaces, a line break and a double space
    do not each buy their own cache row: Unicode NFC, then whitespace collapsed
    to single spaces and stripped. Case is kept, because the model reads the
    request as written and "the FLARE" is not certainly the same question as
    "the flare" -- a spurious miss costs one generation, and a spurious hit
    answers somebody else's request.

    Hashed rather than stored: the key is an index, and nothing reads the
    request back.
    """
    normalised = " ".join(unicodedata.normalize("NFC", request).split())
    return hashlib.sha256(normalised.encode()).hexdigest()


async def cached(
    conn: Any,
    h3: str,
    document_type: str,
    run_id: int,
    request_sha256: str,
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
        CACHE_LOOKUP,
        h3,
        document_type,
        run_id,
        request_sha256,
        methodology_version,
        corpus_version,
        prompt_version,
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
    run_id: int,
    request_sha256: str,
    request_tokens: int,
    response_tokens: int,
) -> None:
    await conn.execute(
        CACHE_STORE,
        draft.h3,
        draft.document.document_type,
        run_id,
        request_sha256,
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


# Ways the provider can be unreachable rather than unwilling, by exception name
# and by message, matched the same way and for the same reason as a limit.
OUTAGE_NAMES = (
    "apiconnectionerror",
    "apitimeouterror",
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "timeout",
    "authenticationerror",
    "permissiondeniederror",
    "internalservererror",
    "apistatuserror",
)
OUTAGE_TEXT = (
    "connection error",
    "connection refused",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "internal server error",
    "overloaded",
    "invalid_api_key",
    "incorrect api key",
    "500",
    "502",
    "503",
    "504",
)


def is_provider_outage(exc: Exception) -> bool:
    """Whether the provider could not be reached or could not be used.

    Connection failures, timeouts, its own 5xx, and a key it rejects. The last
    is not transient and is here anyway: a deployment with a bad key is broken
    in a way the caller can do nothing about, and 503 "the assistant is
    unavailable" is the honest answer, where a 500 would invite them to retry a
    request that was never the problem.
    """
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return any(n in name for n in OUTAGE_NAMES) or any(t in text for t in OUTAGE_TEXT)


def provider_failure(exc: Exception) -> bool:
    """Whether this is the provider's fault rather than this code's."""
    return is_provider_limit(exc) or is_provider_outage(exc)


async def draft_for_hex(
    conn: Any,
    client: Any,
    draft_model: Model | str,
    embedding_model: str,
    hex_context: HexContext,
    document_type: str,
    request: str,
    prompt_version: str = prompts.CURRENT_VERSION,
) -> DraftOutcome:
    """Produce one verified draft, serve one from the cache, or fail saying why.

    `request` is the requester's free text as they sent it, empty when they sent
    none, and not the default that stands in for it: the default is a constant
    per document type, so hashing the text after substitution would key every
    unprompted request on the same digest by a longer route.

    The methodology version is the run's, taken from the context, rather than
    the application's constant. They differ exactly when the code has moved on
    from the run it is serving, and in that case the draft describes the run.
    """
    h3 = hex_context.h3
    methodology_version = hex_context.methodology_version
    request_sha256 = request_digest(request)
    request_text = request.strip() or default_request(document_type)

    # 1. Before anything is spent.
    check_band(h3, hex_context.confidence_band)

    corpus = await retrieval.active(conn)
    if corpus is None:
        raise NoCorpus(
            "No sealed statute corpus is loaded, so no citation could be verified. "
            "Run the corpus ingestion before enabling drafting."
        )
    # Before the cache, because a mismatch means every draft this deployment
    # would produce is retrieved from vectors that do not share a coordinate
    # space with the query's. Serving a cached one instead would hide it.
    retrieval.check_embedding_model(corpus, embedding_model)
    corpus_version = corpus.version

    # 2. Cache. A context no run produced -- the citation audit's fixtures --
    # cannot be keyed on a run, so it neither reads nor writes the cache.
    run_id = hex_context.run_id
    hit = (
        None
        if run_id is None
        else await cached(
            conn,
            h3,
            document_type,
            run_id,
            request_sha256,
            methodology_version,
            corpus_version,
            prompt_version,
        )
    )
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
        retrieved = await retrieval.retrieve_for(
            conn, client, embedding_model, document_type, request_text
        )
    except Exception as exc:
        if provider_failure(exc):
            raise ProviderUnavailable(str(exc)) from exc
        raise

    # One request embeds several queries, and none of them were on the bill.
    usd = await cost.record(
        conn,
        purpose="embedding",
        model=embedding_model,
        request_tokens=retrieved.request_tokens,
        response_tokens=0,
        outcome="retrieved",
        h3=h3,
        document_type=document_type,
    )

    # 4. Generate.
    try:
        result = await generate(
            document_type,
            draft_model,
            prompt.text,
            build_prompt(hex_context, retrieval.as_context(retrieved.passages), request_text),
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
        if provider_failure(exc):
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

    usd += await cost.record(
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
    #
    # A judge that cannot be asked is not a judge that said yes. Whatever the
    # verifier raises -- a malformed judgement, retries exhausted, a timeout --
    # the draft is discarded, and the failure is reported as a failure to
    # verify rather than as a fault in the server.
    try:
        verification = await verifier.verify_document(
            conn, draft_model, document, h3, hex_context.facility_ids()
        )
    except Exception as exc:
        if provider_failure(exc):
            await cost.record(
                conn,
                purpose="verification",
                model=model_name,
                request_tokens=0,
                response_tokens=0,
                outcome="provider_error",
                h3=h3,
                document_type=document_type,
                detail=str(exc)[:500],
            )
            raise ProviderUnavailable(str(exc)) from exc
        await cost.record(
            conn,
            purpose="verification",
            model=model_name,
            request_tokens=0,
            response_tokens=0,
            outcome="unverifiable",
            h3=h3,
            document_type=document_type,
            detail=f"judge failed: {type(exc).__name__}: {exc}"[:500],
        )
        raise VerificationFailed(f"{type(exc).__name__}: {exc}") from exc
    # The judge is a second model run per claim, and it was recorded as zero
    # tokens whether the draft passed or failed, which understated the bill by
    # the part that scales with how much a draft cites.
    usd += await cost.record(
        conn,
        purpose="verification",
        model=model_name,
        request_tokens=verification.request_tokens,
        response_tokens=verification.response_tokens,
        outcome="verified" if verification.verified else "unverifiable",
        h3=h3,
        document_type=document_type,
        detail=(
            "" if verification.verified else f"{len(verification.failures)} citation(s) failed"
        ),
    )

    if not verification.verified:
        await verifier.log_rejections(
            conn, verification, h3, document_type, corpus_version, prompt_version, model_name
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
    if run_id is not None:
        await store(
            conn,
            stamped,
            run_id,
            request_sha256,
            result.request_tokens,
            result.response_tokens,
        )
    return DraftOutcome(draft=stamped, verification=verification, usd=usd)


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
    """What a user who clicks the button and types nothing is asking for."""
    return DEFAULT_REQUESTS[document_type]
