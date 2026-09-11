"""The four document types the assistant drafts, as schemas.

Public comment letter, agency complaint draft, community briefing sheet,
journalist fact sheet. Each is a Pydantic model, and the model is what the LLM
is required to produce: no free-form prose escapes the schema, and a response
that does not conform is rejected rather than repaired.

Four decisions here are guardrails rather than modelling, and are worth reading
as such because each one moves a rule out of the prompt and into a place a
prompt cannot argue with.

**Citations hang off paragraphs, not off the document.** A bibliography at the
end tells a verifier that a section was cited and not what it was cited *for*,
and Appendix B.4 rule 3 requires checking that the proposition actually appears
in the retrieved chunk. So every citation carries the proposition it supports,
attached to the paragraph making it. The document-level `citations` field the
ticket asks for is computed from those rather than supplied separately: asking
the model to maintain the same list twice produces disagreements between them,
and a disagreement would be a rejection of a draft that was otherwise fine.

**The confidence band is a type, not a check.** `confidence_band` cannot hold
"insufficient". Producing a cited complaint from a score the system does not
itself trust is the most damaging thing this tool could do, so the refusal is
in the prompt (CS-304), in the endpoint (CS-306) and here, where it is not a
refusal at all but an unconstructable object.

**An agency complaint has one forum.** `forum` is a Literal with one member:
`administrative_complaint`. A Title VI disparate-impact claim is a complaint to
EPA's External Civil Rights Compliance Office, not a lawsuit a resident can
file, which is exactly why *Sandoval* is in the corpus. A draft implying
otherwise sends someone down a dead end, and that is worse than a missing
citation, so the schema cannot express the wrong one.

**Every document states that it is a draft.** Appendix B.4 rule 5 says this is
enforced in the prompt, in the schema and in the interface. `draft_notice` is
the schema half: a computed constant, not a field the model fills, so it cannot
be softened, reworded or left out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# Section 12's bands, minus the one that may not be drafted from. The absence is
# the point: see the module docstring.
DraftableBand = Literal["high", "moderate", "low"]

DOCUMENT_TYPES = (
    "public_comment_letter",
    "agency_complaint_draft",
    "community_briefing_sheet",
    "journalist_fact_sheet",
)
DocumentType = Literal[
    "public_comment_letter",
    "agency_complaint_draft",
    "community_briefing_sheet",
    "journalist_fact_sheet",
]

DRAFT_NOTICE = (
    "DRAFT FOR HUMAN REVIEW. This document was assembled by an automated tool "
    "from public environmental data and a fixed corpus of statutes. It is not "
    "legal advice, it has not been reviewed by a lawyer, and every factual and "
    "legal claim in it must be checked before it is filed, sent or published."
)


# ---- Citations ----------------------------------------------------------


class StatuteCitation(BaseModel):
    """A citation to a section of the versioned statute corpus.

    `section` must be a section label that exists in the corpus version the
    draft was generated against, character for character. It is not a
    free-text citation the model composes: CS-305 looks it up, and a citation
    that has been reformatted into something a person would recognise but a
    query will not find is a citation that fails verification.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["statute"] = "statute"
    section: str = Field(
        min_length=1,
        description=(
            "The section label exactly as it appears in the retrieved passage, "
            "e.g. '42 U.S.C. § 7412(b)'. Copy it; do not reformat it."
        ),
    )
    document_id: str = Field(
        min_length=1,
        description="The corpus document the passage came from, e.g. 'usc-42-chap85'.",
    )
    proposition: str = Field(
        min_length=1,
        description=(
            "The single claim this section is cited for, in one sentence. It must "
            "be supported by the passage itself, not by inference from it."
        ),
    )


class RecordCitation(BaseModel):
    """A citation to a record in the loaded dataset.

    A facility, a release, a measurement: whatever the claim rests on, named by
    the identifier the dataset uses, so CS-305 can look it up rather than
    judging whether a description sounds plausible.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["record"] = "record"
    record_id: str = Field(
        min_length=1,
        description=(
            "The identifier the dataset uses, e.g. an EPA FRS registry ID. "
            "Copy it from the supplied data; never construct one."
        ),
    )
    dataset: str = Field(
        min_length=1,
        description="Which loaded dataset holds it, e.g. 'echo', 'tri', 'nei'.",
    )
    proposition: str = Field(
        min_length=1,
        description="The single claim this record is cited for, in one sentence.",
    )


Citation = Annotated[StatuteCitation | RecordCitation, Field(discriminator="kind")]


class Paragraph(BaseModel):
    """One paragraph of a draft, with the citations for what it claims.

    `citations` may be empty, and that is deliberate rather than a loophole. A
    paragraph that says who is writing and why makes no factual or legal claim,
    and requiring a citation on it would teach the model to attach one anyway.
    A citation attached to a sentence it does not support is the failure this
    whole phase is built to catch, so the schema does not create pressure to
    manufacture them.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)


# ---- The shared shape ---------------------------------------------------


class DraftDocument(BaseModel):
    """What every draft carries regardless of type.

    This is the part the model writes, and nothing else. Where the draft came
    from — which hexagon, which corpus version, which prompt — is stamped by
    `GeneratedDraft` below, because a model asked to report its own provenance
    is a model that can get it wrong, and provenance that can be wrong is worse
    than none.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    paragraphs: list[Paragraph] = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def draft_notice(self) -> str:
        """Rule 5, in the schema. Constant, and not the model's to write."""
        return DRAFT_NOTICE

    @computed_field  # type: ignore[prop-decorator]
    @property
    def citations(self) -> list[Citation]:
        """Every citation in the document, deduplicated, in order of first use.

        Computed rather than supplied. The ticket asks for a required, non-empty
        citations field on each type, and this is it: a reader and the verifier
        both get one list, while the model is never asked to keep two in step.
        """
        seen: set[tuple[str, ...]] = set()
        out: list[Citation] = []
        for paragraph in self.paragraphs:
            for citation in paragraph.citations:
                key = (
                    (citation.kind, citation.section, citation.document_id)
                    if isinstance(citation, StatuteCitation)
                    else (citation.kind, citation.record_id, citation.dataset)
                )
                if key in seen:
                    continue
                seen.add(key)
                out.append(citation)
        return out

    @model_validator(mode="after")
    def _at_least_one_citation(self) -> DraftDocument:
        if not self.citations:
            raise ValueError(
                "a draft must cite at least one statute section or dataset record; "
                "an uncited draft is the thing this tool exists not to produce"
            )
        return self


# ---- The four types -----------------------------------------------------


class PublicCommentLetter(DraftDocument):
    """A comment on a pending permit action, for the agency's docket.

    The right the letter exercises is real and specific: 42 U.S.C. § 7661a
    requires public participation in Title V operating permit proceedings. The
    letter is addressed to the agency and asks for something.
    """

    document_type: Literal["public_comment_letter"] = "public_comment_letter"

    recipient: str = Field(
        min_length=1, description="The agency and office the comment is addressed to."
    )
    subject: str = Field(min_length=1, description="One line naming the permit action.")
    docket_reference: str | None = Field(
        default=None,
        description=(
            "The agency's docket or permit number, only if it was supplied. "
            "Never construct one; a wrong docket number misfiles the comment."
        ),
    )
    requested_action: str = Field(
        min_length=1,
        description="What the commenter asks the agency to do, in one or two sentences.",
    )


class AgencyComplaintDraft(DraftDocument):
    """An administrative complaint to a federal or state office.

    `forum` has one legal value. A Title VI disparate-impact claim is an
    administrative complaint to EPA's External Civil Rights Compliance Office
    and not a lawsuit a resident can file, which is the holding of *Sandoval*
    and the reason *Sandoval* is in the corpus at all. Making the alternative
    unrepresentable is cheaper and more reliable than catching it in review.
    """

    document_type: Literal["agency_complaint_draft"] = "agency_complaint_draft"

    forum: Literal["administrative_complaint"] = "administrative_complaint"
    recipient_office: str = Field(
        min_length=1,
        description=(
            "The office that receives the complaint, e.g. 'U.S. EPA External Civil "
            "Rights Compliance Office'."
        ),
    )
    legal_basis: list[StatuteCitation] = Field(
        min_length=1,
        description=(
            "The provisions the complaint proceeds under. Statute sections only: "
            "a complaint cannot proceed under a dataset record."
        ),
    )
    relief_sought: str = Field(
        min_length=1, description="What the complainant asks the office to do."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def filing_note(self) -> str:
        """Stated on the document, not left for the reader to infer."""
        return (
            "This is an administrative complaint, submitted to a federal or state "
            "agency's civil rights or environmental office. It is not a lawsuit and "
            "filing it does not begin one."
        )


class CommunityBriefingSheet(DraftDocument):
    """A plain-language summary for the people who live in the hexagon.

    The audience is not a lawyer and not a reporter. It is somebody who wants to
    know what the data says about where they live and what they can do about it,
    so the schema asks for those two things by name rather than hoping they turn
    up in the prose.
    """

    document_type: Literal["community_briefing_sheet"] = "community_briefing_sheet"

    headline: str = Field(min_length=1, description="One plain sentence, no jargon.")
    area_description: str = Field(
        min_length=1,
        description="Where this is about, in terms a resident would use, e.g. a parish.",
    )
    what_this_means: str = Field(
        min_length=1,
        description=(
            "What the score does and does not say. It describes modelled exposure, "
            "nearby permitted sources and a vulnerable population. It is not a "
            "finding of wrongdoing by any operator and not a health diagnosis."
        ),
    )
    what_you_can_do: list[str] = Field(
        min_length=1,
        description=(
            "Concrete next steps available to a resident, such as commenting on a "
            "pending permit. Never legal advice and never a prediction of outcome."
        ),
    )


class KeyFigure(BaseModel):
    """One number a journalist might print, with the record it came from."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    value: str = Field(min_length=1, description="The figure as it should be printed.")
    unit: str = Field(default="", description="Empty when the value carries its own.")
    citation: Citation = Field(
        description="Where the figure comes from. A figure with no record is not a figure."
    )


class JournalistFactSheet(DraftDocument):
    """A briefing for a reporter, built so every number can be checked.

    `caveats` is required and non-empty because the failure mode for this
    document is not a wrong number, it is a correct number printed without the
    limitation that makes it meaningful. Section 16 of the methodology is a page
    of those, and a fact sheet that omits them is worse than no fact sheet.
    """

    document_type: Literal["journalist_fact_sheet"] = "journalist_fact_sheet"

    headline: str = Field(min_length=1)
    key_figures: list[KeyFigure] = Field(min_length=1)
    caveats: list[str] = Field(
        min_length=1,
        description=(
            "What a reader could wrongly conclude from these figures, and why they "
            "should not. Draw on the methodology's stated limitations."
        ),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def citations(self) -> list[Citation]:
        """Paragraph citations plus the source of every key figure.

        A figure cited only in the table would otherwise never reach the
        verifier, and the figures are the part of this document most likely to
        be reprinted without the surrounding prose.
        """
        out = list(DraftDocument.citations.fget(self))  # type: ignore[attr-defined]
        seen = {_key(c) for c in out}
        for figure in self.key_figures:
            if _key(figure.citation) not in seen:
                seen.add(_key(figure.citation))
                out.append(figure.citation)
        return out


def _key(citation: Citation) -> tuple[str, ...]:
    if isinstance(citation, StatuteCitation):
        return (citation.kind, citation.section, citation.document_id)
    return (citation.kind, citation.record_id, citation.dataset)


DOCUMENT_MODELS: dict[str, type[DraftDocument]] = {
    "public_comment_letter": PublicCommentLetter,
    "agency_complaint_draft": AgencyComplaintDraft,
    "community_briefing_sheet": CommunityBriefingSheet,
    "journalist_fact_sheet": JournalistFactSheet,
}


def model_for(document_type: str) -> type[DraftDocument]:
    try:
        return DOCUMENT_MODELS[document_type]
    except KeyError:
        raise KeyError(
            f"{document_type!r} is not one of the four document types: "
            + ", ".join(DOCUMENT_MODELS)
        ) from None


# ---- The envelope -------------------------------------------------------


class GeneratedDraft(BaseModel):
    """A document plus everything needed to reconstruct how it was made.

    The version stamps are not decoration. A draft outlives the session that
    produced it, and somebody holding one a year later has to be able to say
    which score, which corpus and which prompt stood behind it. Section 17
    makes the methodology version load-bearing for a score, and the argument is
    stronger for a document somebody may have filed with an agency.

    Every field here is supplied by the system. None is written by the model.
    """

    model_config = ConfigDict(extra="forbid")

    document: Annotated[
        PublicCommentLetter | AgencyComplaintDraft | CommunityBriefingSheet | JournalistFactSheet,
        Field(discriminator="document_type"),
    ]

    h3: str = Field(description="The hexagon the draft is about, at resolution 8.")
    confidence_band: DraftableBand = Field(
        description=(
            "Section 12's band for this hexagon. The insufficient band is absent "
            "from the type: a hexagon the system does not trust cannot be drafted "
            "from, and the refusal belongs in the type rather than in a check."
        )
    )
    methodology_version: str
    corpus_version: str = Field(
        description="The sealed corpus version retrieval and verification used."
    )
    prompt_version: str = Field(description="The prompt revision, per CS-304.")
    model: str = Field(description="The model that produced the document.")
    generated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def review_required(self) -> Literal[True]:
        """Never false. No path through this system produces a document that
        does not need a person to read it before it is used."""
        return True
