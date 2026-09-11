"""Prompts: versioned, frozen, and saying what they are required to say.

The checksum test is the one that matters most. A prompt is part of how a
document was produced, and editing a released version leaves every past draft
stamped with a version that now says something else. That is an audit trail
which reads as precise and is wrong, which is worse than one that is missing.

The content tests are deliberately about *presence*, not wording. They assert
that v1 still tells the model the things CS-304 requires it to be told. They
cannot assert the model obeys, which is what the red-team run is for.
"""

from __future__ import annotations

import pytest

from app.assistant import prompts
from app.assistant.documents import DOCUMENT_MODELS
from app.assistant.prompts import CURRENT_VERSION, PromptError, load, verify, versions


def test_every_document_type_has_a_prompt_at_the_current_version() -> None:
    for document_type in DOCUMENT_MODELS:
        prompt = load(document_type)
        assert prompt.guidance
        assert prompt.version == CURRENT_VERSION


def test_a_released_prompt_version_has_not_been_edited() -> None:
    """Changing a prompt means adding a version, not changing one.

    If this fails, the fix is almost never to update the recorded checksum. It
    is to copy the version directory, edit the copy, and bump CURRENT_VERSION.
    """
    for version in versions():
        assert verify(version) == []


def test_an_unknown_version_is_refused_with_the_ones_that_exist() -> None:
    with pytest.raises(PromptError, match="no prompt version"):
        load("public_comment_letter", version="v99")


def test_an_unknown_document_type_is_refused() -> None:
    with pytest.raises(PromptError, match="has no"):
        load("press_release")


def test_the_shared_rules_come_before_the_document_description() -> None:
    """A model told how to write a complaint and only then told what it may not
    claim has already been given a shape to fill."""
    prompt = load("agency_complaint_draft")

    assert prompt.text.index(prompt.system) < prompt.text.index(prompt.guidance)


# ---- What the system prompt is required to say -------------------------


@pytest.fixture(scope="module")
def system() -> str:
    """The shared rules, with line wrapping flattened.

    The file is wrapped for people to read and these assertions are about what
    it says, not where the lines break. Matching the raw text would make an
    unrelated reflow fail a safety test, which teaches everyone to edit the
    test.
    """
    return " ".join(load("public_comment_letter").system.split())


def test_the_prompt_limits_the_model_to_the_supplied_sources(system: str) -> None:
    assert "You have two sources and no others" in system
    assert "you do not have your own knowledge of the law" in system


def test_the_prompt_prohibits_claims_about_intent(system: str) -> None:
    assert "intent, motive, knowledge or culpability" in system
    for word in ("intended", "negligent", "reckless", "bad faith"):
        assert word in system


def test_the_prompt_closes_the_hedging_loophole(system: str) -> None:
    """The prohibited claim is prohibited in every form. A rule that only bans
    the direct wording teaches the model to soften it."""
    assert "softened into" in system
    assert "attributed to residents" in system


def test_the_prompt_forbids_legal_advice(system: str) -> None:
    assert "You do not give legal advice" in system
    assert "You may not apply either to a reader's circumstances" in system


def test_the_prompt_carries_the_sandoval_posture(system: str) -> None:
    """The most consequential single instruction in the file."""
    assert "no private right of action" in system
    assert "External Civil Rights Compliance Office" in system
    assert "administrative complaint" in system


def test_the_prompt_forbids_reasoning_from_case_law(system: str) -> None:
    assert "CITE ONLY" in system
    assert "You do not reason from case law" in system


def test_the_prompt_forbids_constructing_identifiers(system: str) -> None:
    assert "Never construct an identifier" in system


def test_the_prompt_requires_the_proposition_to_be_in_the_passage(system: str) -> None:
    """Appendix B.4 rule 3, stated to the model as well as checked by CS-305."""
    assert "supported by the passage" in system


def test_the_prompt_tells_the_model_it_may_refuse(system: str) -> None:
    """A model with no way to decline produces a document anyway."""
    assert "You have a refusal output" in system


def test_the_prompt_says_the_score_is_not_a_finding_of_wrongdoing(system: str) -> None:
    assert "not a finding of wrongdoing by any operator" in system


# ---- Per-type guidance ---------------------------------------------------


def guidance_for(document_type: str) -> str:
    return " ".join(load(document_type).guidance.split())


def test_the_complaint_prompt_forbids_litigation_vocabulary() -> None:
    guidance = guidance_for("agency_complaint_draft")

    assert "Not a lawsuit" in guidance
    assert "no plaintiff, no defendant" in guidance


def test_the_briefing_sheet_prompt_forbids_medical_and_legal_advice() -> None:
    guidance = guidance_for("community_briefing_sheet")

    assert "legal advice, and medical advice" in guidance


def test_the_fact_sheet_prompt_makes_caveats_the_priority() -> None:
    guidance = guidance_for("journalist_fact_sheet")

    assert "most important field" in guidance


def test_the_comment_letter_prompt_forbids_inventing_a_docket() -> None:
    guidance = guidance_for("public_comment_letter")

    assert "constructed docket number misfiles" in guidance


def test_the_prompt_hash_is_stable_for_a_given_version() -> None:
    """Logged alongside the version, so two runs of the same version are
    provably the same instructions."""
    assert load("public_comment_letter").sha256 == load("public_comment_letter").sha256


def test_checksums_are_recorded_for_every_version_in_the_repository() -> None:
    assert set(versions()) == set(prompts.CHECKSUMS)
