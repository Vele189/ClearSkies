"""Structured output, and the refusal to repair a malformed one.

These run against Pydantic AI's `FunctionModel`, which lets a test say exactly
what the model returns without a network call or an API key. That matters more
than usual here: the behaviour under test is what happens when the model
misbehaves, and the only way to see it reliably is to make it misbehave.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.assistant.documents import PublicCommentLetter
from app.assistant.structured import MAX_SCHEMA_ATTEMPTS, DraftRejected, generate

INSTRUCTIONS = "Write a public comment letter."

GOOD_LETTER = {
    "document_type": "public_comment_letter",
    "recipient": "Louisiana Department of Environmental Quality",
    "subject": "Comment on a pending Title V permit renewal",
    "docket_reference": None,
    "requested_action": "Hold a public hearing before acting on the application.",
    "paragraphs": [
        {
            "text": "The application should not be granted without a hearing.",
            "citations": [
                {
                    "kind": "statute",
                    "section": "42 U.S.C. § 7661a",
                    "document_id": "usc-42-chap85",
                    "proposition": "Title V proceedings carry a public participation right.",
                }
            ],
        }
    ],
}


def responder(payloads: list[object]) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    """A model that returns each payload in turn.

    A payload that is a string comes back as plain text, which is how a model
    ignoring the schema entirely behaves. Anything else is returned as a call to
    the output tool, which is how a model answering the schema behaves, correctly
    or not.
    """
    calls = iter(payloads)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = next(calls)
        if isinstance(payload, str):
            return ModelResponse(parts=[TextPart(payload)])
        assert info.output_tools
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(payload))])

    return respond


async def test_a_conforming_response_is_returned_as_the_schema() -> None:
    result = await generate(
        "public_comment_letter",
        FunctionModel(responder([GOOD_LETTER])),
        INSTRUCTIONS,
        "Draft it.",
    )

    assert isinstance(result.document, PublicCommentLetter)
    assert result.document.recipient.startswith("Louisiana")
    assert len(result.document.citations) == 1


async def test_a_response_missing_a_required_field_is_rejected_not_repaired() -> None:
    """The missing field is exactly the part nobody should be quietly filling in
    on the model's behalf."""
    broken = {k: v for k, v in GOOD_LETTER.items() if k != "requested_action"}

    with pytest.raises(DraftRejected) as raised:
        await generate(
            "public_comment_letter",
            FunctionModel(responder([broken] * (MAX_SCHEMA_ATTEMPTS + 1))),
            INSTRUCTIONS,
            "Draft it.",
        )

    assert raised.value.document_type == "public_comment_letter"
    assert "schema" in str(raised.value)


async def test_a_response_with_no_citations_is_rejected() -> None:
    uncited = {
        **GOOD_LETTER,
        "paragraphs": [{"text": "The permit should be denied.", "citations": []}],
    }

    with pytest.raises(DraftRejected):
        await generate(
            "public_comment_letter",
            FunctionModel(responder([uncited] * (MAX_SCHEMA_ATTEMPTS + 1))),
            INSTRUCTIONS,
            "Draft it.",
        )


async def test_a_response_citing_free_text_is_rejected() -> None:
    """A model writing 'see the Clean Air Act' where a structured citation
    belongs produces nothing, rather than a draft with an uncheckable claim."""
    free_text = {
        **GOOD_LETTER,
        "paragraphs": [
            {"text": "The permit should be denied.", "citations": ["the Clean Air Act"]}
        ],
    }

    with pytest.raises(DraftRejected):
        await generate(
            "public_comment_letter",
            FunctionModel(responder([free_text] * (MAX_SCHEMA_ATTEMPTS + 1))),
            INSTRUCTIONS,
            "Draft it.",
        )


async def test_prose_instead_of_a_document_is_rejected() -> None:
    with pytest.raises(DraftRejected):
        await generate(
            "public_comment_letter",
            FunctionModel(
                responder(["Dear Department, I am writing to object."] * (MAX_SCHEMA_ATTEMPTS + 1))
            ),
            INSTRUCTIONS,
            "Draft it.",
        )


async def test_the_model_may_correct_itself_against_the_same_schema() -> None:
    """Retrying is the model fixing its own output against the schema it was
    given. That is different in kind from us editing the output, and it is the
    only correction this code permits."""
    broken = {k: v for k, v in GOOD_LETTER.items() if k != "requested_action"}

    result = await generate(
        "public_comment_letter",
        FunctionModel(responder([broken, GOOD_LETTER])),
        INSTRUCTIONS,
        "Draft it.",
    )

    assert isinstance(result.document, PublicCommentLetter)


async def test_a_rejection_carries_the_detail_an_audit_needs() -> None:
    broken = {**GOOD_LETTER, "paragraphs": []}

    with pytest.raises(DraftRejected) as raised:
        await generate(
            "public_comment_letter",
            FunctionModel(responder([broken] * (MAX_SCHEMA_ATTEMPTS + 1))),
            INSTRUCTIONS,
            "Draft it.",
        )

    assert raised.value.detail


async def test_usage_is_reported_so_the_endpoint_can_log_cost() -> None:
    result = await generate(
        "public_comment_letter",
        FunctionModel(responder([GOOD_LETTER])),
        INSTRUCTIONS,
        "Draft it.",
    )

    assert result.total_tokens == result.request_tokens + result.response_tokens
    assert result.request_tokens > 0
