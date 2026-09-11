"""The four document schemas, and what they refuse.

Most of this file is about rejection. The schemas carry safety properties that
the rest of Phase 3 relies on — a citation behind every claim, a band that
cannot be the one the system does not trust, a complaint with only one forum —
and a property that is not tested is a property that quietly stops holding.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.assistant.documents import (
    DOCUMENT_MODELS,
    DRAFT_NOTICE,
    AgencyComplaintDraft,
    CommunityBriefingSheet,
    GeneratedDraft,
    JournalistFactSheet,
    KeyFigure,
    Paragraph,
    PublicCommentLetter,
    RecordCitation,
    StatuteCitation,
    model_for,
)

SECTION = StatuteCitation(
    section="42 U.S.C. § 7412(b)",
    document_id="usc-42-chap85",
    proposition="Congress established a list of hazardous air pollutants.",
)
RECORD = RecordCitation(
    record_id="110000350053",
    dataset="echo",
    proposition="This facility holds a Title V operating permit.",
)


def cited(text: str = "A claim.") -> Paragraph:
    return Paragraph(text=text, citations=[SECTION])


def letter(**overrides: object) -> PublicCommentLetter:
    fields: dict[str, object] = {
        "recipient": "Louisiana Department of Environmental Quality",
        "subject": "Comment on a pending Title V permit renewal",
        "requested_action": "Hold a public hearing before acting on the application.",
        "paragraphs": [cited()],
    }
    fields.update(overrides)
    return PublicCommentLetter(**fields)  # type: ignore[arg-type]


# ---- One schema per type, each with a non-empty citations field ---------


def test_there_are_exactly_four_document_types() -> None:
    assert set(DOCUMENT_MODELS) == {
        "public_comment_letter",
        "agency_complaint_draft",
        "community_briefing_sheet",
        "journalist_fact_sheet",
    }


def test_model_for_rejects_a_type_that_is_not_one_of_the_four() -> None:
    with pytest.raises(KeyError, match="not one of the four"):
        model_for("press_release")


def test_a_draft_with_no_citation_anywhere_is_rejected() -> None:
    """An uncited draft is the thing this tool exists not to produce."""
    with pytest.raises(ValidationError, match="must cite at least one"):
        letter(paragraphs=[Paragraph(text="We are writing to object.")])


def test_a_draft_with_no_paragraphs_is_rejected() -> None:
    with pytest.raises(ValidationError):
        letter(paragraphs=[])


def test_the_citations_field_gathers_every_citation_in_the_document() -> None:
    other = StatuteCitation(
        section="42 U.S.C. § 7661a",
        document_id="usc-42-chap85",
        proposition="Title V permit proceedings carry a public participation right.",
    )
    document = letter(
        paragraphs=[
            Paragraph(text="One.", citations=[SECTION]),
            Paragraph(text="Two.", citations=[other, RECORD]),
        ]
    )

    assert [c.proposition for c in document.citations] == [
        SECTION.proposition,
        other.proposition,
        RECORD.proposition,
    ]


def test_a_citation_used_twice_appears_once() -> None:
    document = letter(
        paragraphs=[
            Paragraph(text="One.", citations=[SECTION]),
            Paragraph(text="Two.", citations=[SECTION]),
        ]
    )

    assert len(document.citations) == 1


def test_a_framing_paragraph_may_carry_no_citation() -> None:
    """Requiring one on a paragraph that makes no claim teaches the model to
    attach a citation that does not support anything."""
    document = letter(
        paragraphs=[
            Paragraph(text="I live in St. James Parish."),
            cited(),
        ]
    )

    assert len(document.citations) == 1


# ---- Citations are structured, never free text -------------------------


def test_a_statute_citation_needs_a_section_a_document_and_a_proposition() -> None:
    for missing in ("section", "document_id", "proposition"):
        fields = {
            "section": "42 U.S.C. § 7412",
            "document_id": "usc-42-chap85",
            "proposition": "x",
        }
        del fields[missing]
        with pytest.raises(ValidationError):
            StatuteCitation(**fields)  # type: ignore[arg-type]


def test_an_empty_section_label_is_rejected() -> None:
    with pytest.raises(ValidationError):
        StatuteCitation(section="", document_id="usc-42-chap85", proposition="x")


def test_a_citation_cannot_be_a_bare_string() -> None:
    """The failure this prevents is a model writing 'see the Clean Air Act'."""
    with pytest.raises(ValidationError):
        Paragraph(text="A claim.", citations=["42 U.S.C. 7412"])  # type: ignore[list-item]


def test_a_citation_with_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Paragraph(
            text="A claim.",
            citations=[{"kind": "website", "url": "https://example.test"}],  # type: ignore[list-item]
        )


def test_extra_fields_on_a_citation_are_rejected() -> None:
    """A model inventing a field is a model doing something the schema did not
    ask for, and the safe response is to refuse the document."""
    with pytest.raises(ValidationError):
        StatuteCitation(
            section="42 U.S.C. § 7412",
            document_id="usc-42-chap85",
            proposition="x",
            confidence="high",  # type: ignore[call-arg]
        )


# ---- Rule 5: every document says it is a draft -------------------------


def test_every_document_type_carries_the_draft_notice() -> None:
    documents = [
        letter(),
        AgencyComplaintDraft(
            recipient_office="U.S. EPA External Civil Rights Compliance Office",
            legal_basis=[SECTION],
            relief_sought="Open an investigation.",
            paragraphs=[cited()],
        ),
        CommunityBriefingSheet(
            headline="What the data says about the air where you live",
            area_description="St. James Parish",
            what_this_means="The score describes modelled exposure, not wrongdoing.",
            what_you_can_do=["Comment on the pending permit."],
            paragraphs=[cited()],
        ),
        JournalistFactSheet(
            headline="Eleven permitted sources within ten kilometres",
            key_figures=[KeyFigure(label="Facilities", value="11", citation=RECORD)],
            caveats=["The score is a Louisiana percentile, not a national one."],
            paragraphs=[cited()],
        ),
    ]

    for document in documents:
        assert document.draft_notice == DRAFT_NOTICE
        assert "not legal advice" in document.draft_notice


def test_the_draft_notice_cannot_be_supplied_by_the_model() -> None:
    """It is computed, so a response trying to set it is refused outright
    rather than having its wording accepted."""
    with pytest.raises(ValidationError):
        letter(draft_notice="This document is final and ready to file.")


# ---- The Sandoval guardrail --------------------------------------------


def test_an_agency_complaint_has_only_one_forum() -> None:
    """A Title VI disparate-impact claim is an administrative complaint to EPA,
    not a lawsuit a resident can file. That is the holding of Sandoval, it is
    why Sandoval is in the corpus, and the schema cannot express the other."""
    with pytest.raises(ValidationError):
        AgencyComplaintDraft(
            forum="lawsuit",  # type: ignore[arg-type]
            recipient_office="U.S. District Court",
            legal_basis=[SECTION],
            relief_sought="Damages.",
            paragraphs=[cited()],
        )


def test_an_agency_complaint_says_on_its_face_that_it_is_not_a_lawsuit() -> None:
    complaint = AgencyComplaintDraft(
        recipient_office="U.S. EPA External Civil Rights Compliance Office",
        legal_basis=[SECTION],
        relief_sought="Open an investigation.",
        paragraphs=[cited()],
    )

    assert "not a lawsuit" in complaint.filing_note


def test_a_complaint_cannot_proceed_on_a_dataset_record_alone() -> None:
    with pytest.raises(ValidationError):
        AgencyComplaintDraft(
            recipient_office="U.S. EPA External Civil Rights Compliance Office",
            legal_basis=[RECORD],  # type: ignore[list-item]
            relief_sought="Open an investigation.",
            paragraphs=[cited()],
        )


def test_a_complaint_needs_a_legal_basis() -> None:
    with pytest.raises(ValidationError):
        AgencyComplaintDraft(
            recipient_office="U.S. EPA External Civil Rights Compliance Office",
            legal_basis=[],
            relief_sought="Open an investigation.",
            paragraphs=[cited()],
        )


# ---- Type-specific requirements ----------------------------------------


def test_a_fact_sheet_requires_caveats() -> None:
    """The failure mode here is not a wrong number. It is a correct number
    printed without the limitation that makes it meaningful."""
    with pytest.raises(ValidationError):
        JournalistFactSheet(
            headline="Eleven permitted sources within ten kilometres",
            key_figures=[KeyFigure(label="Facilities", value="11", citation=RECORD)],
            caveats=[],
            paragraphs=[cited()],
        )


def test_a_key_figure_must_name_where_it_came_from() -> None:
    with pytest.raises(ValidationError):
        KeyFigure(label="Facilities", value="11")  # type: ignore[call-arg]


def test_a_figure_cited_only_in_the_table_still_reaches_the_verifier() -> None:
    """The figures are the part most likely to be reprinted without the prose,
    so a figure whose source never reached CS-305 would be the least checked
    number in the document."""
    sheet = JournalistFactSheet(
        headline="Eleven permitted sources within ten kilometres",
        key_figures=[KeyFigure(label="Facilities", value="11", citation=RECORD)],
        caveats=["Louisiana percentiles are not national percentiles."],
        paragraphs=[Paragraph(text="Background.", citations=[SECTION])],
    )

    assert {c.proposition for c in sheet.citations} == {
        SECTION.proposition,
        RECORD.proposition,
    }


def test_a_briefing_sheet_requires_something_a_resident_can_do() -> None:
    with pytest.raises(ValidationError):
        CommunityBriefingSheet(
            headline="What the data says",
            area_description="St. James Parish",
            what_this_means="The score describes modelled exposure.",
            what_you_can_do=[],
            paragraphs=[cited()],
        )


def test_a_comment_letter_omits_a_docket_it_was_not_given() -> None:
    """A constructed docket number misfiles the comment, which is worse than
    filing it without one."""
    assert letter().docket_reference is None


# ---- The envelope -------------------------------------------------------


def envelope(**overrides: object) -> GeneratedDraft:
    fields: dict[str, object] = {
        "document": letter(),
        "h3": "88444600ddfffff",
        "confidence_band": "moderate",
        "methodology_version": "0.1.4",
        "corpus_version": "appendix-b-4ff29b03c9be",
        "prompt_version": "1",
        "model": "gpt-4o",
        "generated_at": datetime(2026, 9, 11, tzinfo=UTC),
    }
    fields.update(overrides)
    return GeneratedDraft(**fields)  # type: ignore[arg-type]


def test_a_draft_cannot_be_generated_for_an_insufficient_confidence_hexagon() -> None:
    """Producing a cited complaint from a score the system does not trust is the
    most damaging thing this tool could do. The band is absent from the type, so
    it is not a refusal, it is an object that cannot be built."""
    with pytest.raises(ValidationError):
        envelope(confidence_band="insufficient")


@pytest.mark.parametrize("band", ["high", "moderate", "low"])
def test_the_three_draftable_bands_are_accepted(band: str) -> None:
    assert envelope(confidence_band=band).confidence_band == band


def test_the_envelope_records_which_corpus_and_prompt_produced_the_draft() -> None:
    stamped = envelope()

    assert stamped.corpus_version == "appendix-b-4ff29b03c9be"
    assert stamped.prompt_version == "1"
    assert stamped.methodology_version == "0.1.4"


def test_review_is_always_required() -> None:
    assert envelope().review_required is True


def test_the_envelope_dispatches_on_the_document_type() -> None:
    payload = envelope().model_dump()
    payload["document"]["document_type"] = "journalist_fact_sheet"

    with pytest.raises(ValidationError):
        GeneratedDraft.model_validate(payload)
