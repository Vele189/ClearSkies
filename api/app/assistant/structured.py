"""Structured output, enforced by Pydantic AI, with no repair step.

One rule, and the whole module exists to hold it: **a response that does not
conform to the schema is rejected.** It is not patched, coerced, regex-scraped
into shape, or handed back with the missing field filled in from somewhere else.

That rule sounds like strictness for its own sake and is not. The schema is
where the safety properties live — the citation on every claim, the band that
cannot be "insufficient", the complaint that has only one forum. Repairing a
malformed response means a human wrote part of a document while the audit trail
says a model produced it under a schema, and the one part a human filled in is,
by construction, the part the model could not produce correctly. That is exactly
the part nobody should be quietly supplying.

Retries are a separate question and are allowed. Pydantic AI's retry hands the
validation error back to the model and asks it to try again, which is the model
correcting its own output against the same schema, not us editing it. The limit
is low: a model that cannot produce the shape in three attempts is not going to
produce a trustworthy document on the fourth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.models import Model

from app.assistant.documents import DraftDocument, model_for
from app.assistant.guardrails import Refusal

log = logging.getLogger(__name__)

# Three attempts at the schema, then stop. Each one costs a full generation, and
# a model still failing to produce the shape on the third is failing for a
# reason another attempt will not fix.
MAX_SCHEMA_ATTEMPTS = 3


def model_label(model: Model | str) -> str:
    """What to record as the model that produced a draft.

    `str()` on a Pydantic AI model object gives its class name, not the model:
    `OpenAIChatModel()`, every time, for every model. Using it stamped every
    draft's provenance with a string that identifies nothing and made the cost
    estimate zero, because no price table has an entry for a class name. Both
    failures are quiet — a draft still generates, a usage row still lands — and
    the second only shows up as a bill that does not match the reported spend.

    `model_name` is the attribute that carries it. Falling back to `str` keeps a
    plain string model name, which is what the tests pass, working unchanged.
    """
    return str(getattr(model, "model_name", None) or model)


class DraftRejected(RuntimeError):
    """The model did not produce a document conforming to its schema.

    Carries what was wrong so the endpoint can log it and CS-308 can audit it.
    Deliberately not a subclass of anything the API turns into a 200.
    """

    def __init__(self, document_type: str, reason: str, detail: str = "") -> None:
        self.document_type = document_type
        self.reason = reason
        self.detail = detail
        super().__init__(f"{document_type}: {reason}")


@dataclass(frozen=True)
class DraftResult:
    """A conforming document or a refusal, and what it cost to get it.

    A refusal is a result, not an error. The model was given a legitimate way to
    decline and used it, which is the behaviour CS-304 is trying to produce; the
    caller renders the explanation rather than retrying into a document that was
    never supportable.
    """

    document: DraftDocument | None
    refusal: Refusal | None
    request_tokens: int
    response_tokens: int
    model_name: str

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    @property
    def total_tokens(self) -> int:
        return self.request_tokens + self.response_tokens


def build_agent(
    document_type: str,
    model: Model | str,
    instructions: str,
) -> Agent[None, Any]:
    """An agent that can only return the schema for one document type.

    `output_type` is the enforcement. Pydantic AI hands the model the JSON schema
    and validates what comes back against it, so "the model returned prose with
    a citation in it" is not a state this code has to handle: it is a validation
    failure before any of our own logic sees it.
    """
    return Agent(
        model,
        # Two outputs, and the second is the safety feature. A model given only
        # the document schema has no way to say the passages do not support the
        # document; its options are to produce one anyway or to fail validation,
        # and it will produce one, because producing the requested shape is what
        # the schema asks for. Refusal has to be something it can return.
        output_type=[model_for(document_type), Refusal],
        instructions=instructions,
        retries=MAX_SCHEMA_ATTEMPTS,
    )


async def generate(
    document_type: str,
    model: Model | str,
    instructions: str,
    prompt: str,
) -> DraftResult:
    """Run one generation, or raise `DraftRejected`.

    There is no third outcome. Every failure path below ends in a rejection with
    a reason, because the alternative — returning something partial and letting
    the caller decide — is how a draft with one unverifiable claim reaches a
    user with a warning attached instead of not reaching them at all.
    """
    agent = build_agent(document_type, model, instructions)

    try:
        result = await agent.run(prompt)
    except UnexpectedModelBehavior as exc:
        # Pydantic AI raises this when the retries are used up without a
        # conforming response, among other things.
        raise DraftRejected(
            document_type,
            "the model did not return a document matching the schema",
            str(exc),
        ) from exc
    except ValidationError as exc:
        raise DraftRejected(
            document_type, "the response failed schema validation", str(exc)
        ) from exc

    output = result.output
    document: DraftDocument | None = None
    refusal: Refusal | None = None
    if isinstance(output, Refusal):
        refusal = output
        log.info("draft refused: %s (%s)", refusal.reason, document_type)
    elif isinstance(output, DraftDocument):
        document = output
    else:  # pragma: no cover - output_type pins this
        raise DraftRejected(
            document_type,
            f"the model returned {type(output).__name__}, not a draft document",
        )

    # A property on Pydantic AI 2.x, a method on 1.x. Accepting both keeps a
    # minor upgrade from turning cost logging into a 500.
    usage = result.usage
    if callable(usage):  # pragma: no cover - one branch per installed version
        usage = usage()
    return DraftResult(
        document=document,
        refusal=refusal,
        request_tokens=getattr(usage, "input_tokens", 0) or 0,
        response_tokens=getattr(usage, "output_tokens", 0) or 0,
        model_name=model_label(model),
    )
