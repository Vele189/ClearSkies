"""The two guardrails that are code, and the red-team set that probes them.

The refusal path gets exercised end to end through a stub model, because a
refusal channel nobody has driven is a channel that turns out to be wired to
nothing on the day it is needed.

What is *not* here is any assertion that the real model obeys the prompt. Only
`scripts/run_redteam.py` can measure that, and it costs money and needs a key.
The offline tests cover everything that can hold without one: the band refusal,
the refusal schema, the shape of the attack set, and the scan CS-308 uses to
read fifty drafts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.assistant.guardrails import (
    CONFIDENCE_BANDS,
    REFUSED_BAND,
    InsufficientConfidence,
    Refusal,
    check_band,
)
from app.assistant.redteam import ATTACKS, Attack, by_category, scan
from app.assistant.structured import generate

H3 = "88444600ddfffff"


# ---- The band that cannot be drafted from -------------------------------


@pytest.mark.parametrize("band", ["high", "moderate", "low"])
def test_a_trusted_hexagon_may_be_drafted_from(band: str) -> None:
    check_band(H3, band)


def test_an_insufficient_hexagon_is_refused_before_anything_is_spent() -> None:
    """Checked before retrieval and before the model, so the request never
    reaches a place where a document could be written for it."""
    with pytest.raises(InsufficientConfidence) as raised:
        check_band(H3, REFUSED_BAND)

    assert raised.value.h3 == H3
    assert raised.value.band == REFUSED_BAND


def test_the_refusal_is_explained_in_plain_language() -> None:
    """CS-307 renders this rather than an error code. The reader is being told
    the tool does not trust its own number for their neighbourhood."""
    raised = InsufficientConfidence(H3, REFUSED_BAND)

    assert "not enough data" in raised.explanation
    assert "looks well supported and is not" in raised.explanation
    assert "error" not in raised.explanation.lower()


def test_a_band_that_is_not_one_of_section_twelve_s_is_an_error() -> None:
    """Not a silent pass. A typo'd band would otherwise draft freely."""
    with pytest.raises(ValueError, match="not one of"):
        check_band(H3, "unknown")


def test_the_refused_band_is_one_of_the_bands() -> None:
    assert REFUSED_BAND in CONFIDENCE_BANDS


# ---- The refusal output -------------------------------------------------


def test_a_refusal_must_explain_itself() -> None:
    with pytest.raises(ValidationError):
        Refusal(reason="insufficient_data", explanation="")


def test_a_refusal_cannot_carry_a_partial_draft() -> None:
    with pytest.raises(ValidationError):
        Refusal(
            reason="insufficient_data",
            explanation="Not enough data.",
            paragraphs=[{"text": "Here is a start anyway."}],  # type: ignore[call-arg]
        )


def test_a_refusal_is_never_a_success_in_disguise() -> None:
    refusal = Refusal(reason="no_supporting_authority", explanation="Nothing on point.")

    assert refusal.refused is True


def responder(payload: object) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # The refusal tool is the one whose name mentions refusal; the other is
        # the document. Picking by name rather than by position keeps this
        # working if Pydantic AI orders them differently.
        tools = info.output_tools
        assert tools
        wants_refusal = isinstance(payload, dict) and payload.get("refused")
        tool = next(
            (t for t in tools if ("refus" in t.name.lower()) == bool(wants_refusal)),
            tools[0],
        )
        return ModelResponse(parts=[ToolCallPart(tool.name, json.dumps(payload))])

    return respond


async def test_the_model_can_refuse_and_the_refusal_reaches_the_caller() -> None:
    """The channel exists and is wired. A model given only a document schema has
    no way to say the passages do not support one, so it produces one."""
    result = await generate(
        "public_comment_letter",
        FunctionModel(
            responder(
                {
                    "refused": True,
                    "reason": "no_supporting_authority",
                    "explanation": "No retrieved passage addresses cumulative impact review.",
                    "missing": ["a cumulative impact provision"],
                }
            )
        ),
        "Write a public comment letter.",
        "Draft it.",
    )

    assert result.refused
    assert result.document is None
    assert result.refusal is not None
    assert result.refusal.reason == "no_supporting_authority"
    assert result.refusal.missing == ["a cumulative impact provision"]


async def test_a_document_is_not_mistaken_for_a_refusal() -> None:
    result = await generate(
        "public_comment_letter",
        FunctionModel(
            responder(
                {
                    "document_type": "public_comment_letter",
                    "recipient": "LDEQ",
                    "subject": "Comment",
                    "docket_reference": None,
                    "requested_action": "Hold a hearing.",
                    "paragraphs": [
                        {
                            "text": "A claim.",
                            "citations": [
                                {
                                    "kind": "statute",
                                    "section": "42 U.S.C. § 7661a",
                                    "document_id": "usc-42-chap85",
                                    "proposition": "Public participation is required.",
                                }
                            ],
                        }
                    ],
                }
            )
        ),
        "Write a public comment letter.",
        "Draft it.",
    )

    assert not result.refused
    assert result.document is not None


# ---- The attack set -----------------------------------------------------


def test_the_set_covers_every_category_cs304_names() -> None:
    for category in ("intent_claim", "legal_advice", "invented_fact", "wrong_forum"):
        assert by_category(category), category


def test_every_attack_is_identified_and_explained() -> None:
    for attack in ATTACKS:
        assert attack.id
        assert attack.request
        assert attack.note, attack.id


def test_attack_ids_are_unique() -> None:
    assert len({a.id for a in ATTACKS}) == len(ATTACKS)


def test_the_set_contains_controls_that_should_not_be_refused() -> None:
    """A guardrail that refuses everything passes every refusal test and is
    useless. The controls are legitimate requests that must still produce a
    document, and without them the set measures only timidity."""
    assert any(a.expected == "comply_without" for a in ATTACKS)
    assert any(a.expected == "refuse" for a in ATTACKS)


def test_the_set_probes_the_sandoval_failure() -> None:
    """A draft that sends somebody to court on a claim no court will hear is
    the most consequential failure available to this tool."""
    forum = by_category("wrong_forum")

    assert any("lawsuit" in a.request.lower() for a in forum)
    assert any(a.expected == "comply_without" for a in forum)


def test_a_refusal_attack_says_what_must_not_appear_or_is_a_plain_refusal() -> None:
    for attack in ATTACKS:
        if attack.expected == "comply_without":
            assert attack.must_not_contain, attack.id


# ---- The prohibited-language scan ---------------------------------------


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("The operator deliberately sited the plant here.", "intent"),
        ("The company knew the emissions were harmful.", "intent"),
        ("This was no coincidence.", "intent"),
        ("The siting was not accidental.", "intent"),
        ("The operator has been reckless.", "culpability"),
        ("This amounts to wrongdoing.", "culpability"),
        ("You are likely to win this challenge.", "prediction"),
        ("You should file suit in federal court.", "litigation"),
        ("You have a claim under Title VI.", "advice"),
    ],
)
def test_the_scan_catches_the_language_it_exists_for(text: str, category: str) -> None:
    assert category in {flag.category for flag in scan(text)}


def test_the_scan_is_quiet_on_a_documented_fact() -> None:
    text = (
        "Eleven permitted sources operate within ten kilometres of a census tract "
        "whose population is 78% Black. The facility holds a Title V operating "
        "permit, EPA registry ID 110000350053."
    )

    assert scan(text) == []


def test_the_scan_returns_context_a_reviewer_can_judge() -> None:
    """A phrase with no surrounding sentence cannot be reviewed, only obeyed."""
    flags = scan("The permit was granted. The operator knew of the requirement.")

    assert flags
    assert "knew of the requirement" in flags[0].context


def test_the_scan_flags_a_correct_sentence_too() -> None:
    """Deliberate. A complaint that correctly says it is not a lawsuit contains
    the word, and a scan tuned until it stays quiet on that is a scan tuned
    until it stays quiet."""
    flags = scan("This is an administrative complaint and not a lawsuit.")

    assert "litigation" in {f.category for f in flags}


def test_an_attack_is_a_frozen_record() -> None:
    """The set is the record of what was probed. A test that mutated one would
    leave the committed report describing a run that did not happen."""
    with pytest.raises(FrozenInstanceError):
        ATTACKS[0].request = "changed"  # type: ignore[misc]


def test_attacks_are_typed_as_expected() -> None:
    assert all(isinstance(a, Attack) for a in ATTACKS)
