"""The citation verifier, and the four ways a citation fails.

The ticket names them and each is here: a fabricated ID, a near-miss ID, a
section that exists in the real world but not in this corpus, and a correct
section paired with a proposition it does not support. The last is the one this
component exists for, and it is the only one that needs a model to catch.

The judge is stubbed. What is under test is what the verifier does with each
answer, not whether a language model can read a statute, and a test whose result
depends on a live model is a test that fails for reasons unrelated to the code.
`docs/validation/` records what the real judge did.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.assistant.documents import (
    Paragraph,
    PublicCommentLetter,
    RecordCitation,
    StatuteCitation,
)
from app.assistant.verifier import (
    DATASET_LOOKUPS,
    CitationCheck,
    DraftUnverifiable,
    Verification,
    build_judge,
    check_record,
    check_statute,
    verify_document,
)

REAL_SECTION = "42 U.S.C. § 7412(b)"
H3 = "884446007dfffff"
PASSAGE = "The Congress establishes a list of hazardous air pollutants."


def judge_model(verdict: str, reason: str = "because") -> FunctionModel:
    """A judge that always returns one verdict."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.output_tools
        import json

        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    json.dumps({"verdict": verdict, "reason": reason}),
                )
            ]
        )

    return FunctionModel(respond)


class FakeConn:
    """The corpus and the facility table, as far as the verifier reads them."""

    def __init__(
        self,
        sections: dict[str, list[str]] | None = None,
        facilities: dict[str, str] | None = None,
    ) -> None:
        self.sections = sections if sections is not None else {REAL_SECTION: [PASSAGE]}
        self.facilities = facilities if facilities is not None else {"110000350053": "NUCOR"}
        self.logged: list[tuple[Any, ...]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "section_label = $1" in query:
            wanted = args[0]
            # The label itself or any subdivision of it, matching the real query.
            return [
                {
                    "section_label": label,
                    "document_id": "usc-42-chap85",
                    "text": text,
                    "may_reason_from": True,
                }
                for label, texts in sorted(self.sections.items())
                if label == wanted or label.startswith(f"{wanted}(")
                for text in texts
            ]
        # The near-miss query.
        wanted = args[0]
        return [
            {"section_label": label}
            for label in self.sections
            if label.startswith(wanted) or wanted.startswith(label)
        ][:5]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        name = self.facilities.get(args[0])
        return None if name is None else {"facility_id": args[0], "name": name}

    async def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> None:
        self.logged.extend(rows)


def statute(
    section: str = REAL_SECTION, proposition: str = "Congress listed pollutants."
) -> StatuteCitation:
    return StatuteCitation(section=section, document_id="usc-42-chap85", proposition=proposition)


def record(record_id: str = "110000350053", dataset: str = "echo") -> RecordCitation:
    return RecordCitation(
        record_id=record_id, dataset=dataset, proposition="This facility is permitted."
    )


def letter(*citations: Any) -> PublicCommentLetter:
    return PublicCommentLetter(
        recipient="LDEQ",
        subject="Comment",
        requested_action="Hold a hearing.",
        paragraphs=[Paragraph(text="A claim.", citations=list(citations))],
    )


# ---- Statute sections ---------------------------------------------------


async def test_a_real_section_supporting_its_proposition_verifies() -> None:
    check = await check_statute(FakeConn(), build_judge(judge_model("supported")), statute())

    assert check.ok
    assert check.verdict == "verified"


async def test_a_fabricated_section_is_rejected() -> None:
    check = await check_statute(
        FakeConn(), build_judge(judge_model("supported")), statute("42 U.S.C. § 9999")
    )

    assert check.verdict == "not_in_corpus"
    assert "not a section label in the sealed corpus" in check.detail


async def test_a_near_miss_section_is_rejected_and_says_what_it_was_near() -> None:
    """The difference between inventing a statute and dropping a subdivision.
    Both are rejected; only one is a sign the model is hallucinating."""
    check = await check_statute(
        FakeConn(), build_judge(judge_model("supported")), statute("42 U.S.C. § 7412(b)(99)")
    )

    assert check.verdict == "not_in_corpus"
    assert REAL_SECTION in check.near_misses


async def test_a_section_that_exists_in_the_world_but_not_the_corpus_is_rejected() -> None:
    """The Louisiana authorities are in Appendix B and not in the corpus. A
    model citing one from memory is citing something real and unverifiable,
    which is exactly what a closed corpus is for."""
    check = await check_statute(
        FakeConn(), build_judge(judge_model("supported")), statute("La. R.S. 30:2001")
    )

    assert check.verdict == "not_in_corpus"


async def test_a_real_section_with_an_unsupported_proposition_is_rejected() -> None:
    """The failure this component exists for.

    The section number is right. A reader can look it up and will find it. It
    does not say what the draft says it says, and the effort of checking makes
    the reader more confident, not less.
    """
    check = await check_statute(
        FakeConn(),
        build_judge(judge_model("not_supported", "the passage does not name any facility")),
        statute(proposition="This facility violated the standard."),
    )

    assert check.verdict == "unsupported"
    assert not check.ok
    assert "does not name any facility" in check.detail


async def test_an_unclear_judgement_fails_rather_than_passes() -> None:
    """A verifier that resolves its own uncertainty in favour of publishing is
    not a verifier. A false rejection costs one draft somebody can ask for
    again; a false acceptance ships a citation nobody will check twice."""
    check = await check_statute(
        FakeConn(), build_judge(judge_model("unclear", "cannot tell")), statute()
    )

    assert check.verdict == "unclear"
    assert not check.ok


async def test_a_citation_to_a_section_matches_its_subdivisions() -> None:
    """The corpus stores chunks and a citation names a unit. A section whose
    every chunk carries a subdivision label has no chunk labelled with the bare
    section, so an exact match would tell a user their statute does not exist."""
    conn = FakeConn(sections={"42 U.S.C. § 7410(a)": ["Plan requirements."]})

    check = await check_statute(
        conn, build_judge(judge_model("supported")), statute("42 U.S.C. § 7410")
    )

    assert check.ok


async def test_a_citation_does_not_match_a_sibling_subdivision() -> None:
    """(b) must not be satisfied by (a). The boundary is what stops a citation
    being verified against a passage from somewhere else in the section."""
    conn = FakeConn(sections={"42 U.S.C. § 7412(a)": ["Definitions."]})

    check = await check_statute(
        conn, build_judge(judge_model("supported")), statute("42 U.S.C. § 7412(b)")
    )

    assert check.verdict == "not_in_corpus"


async def test_a_section_split_across_chunks_is_judged_whole() -> None:
    """Judging chunk by chunk would reject a proposition that spans two halves
    of one section for being in neither."""
    conn = FakeConn(sections={REAL_SECTION: ["First half.", "Second half."]})
    captured: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        import json

        assert info.output_tools
        for message in messages:
            for part in getattr(message, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured.append(content)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    json.dumps({"verdict": "supported", "reason": "ok"}),
                )
            ]
        )

    await check_statute(conn, build_judge(FunctionModel(respond)), statute())

    joined = "\n".join(captured)
    assert "First half." in joined
    assert "Second half." in joined


# ---- Records ------------------------------------------------------------


async def test_a_real_facility_verifies() -> None:
    check = await check_record(FakeConn(), record())

    assert check.ok
    assert "NUCOR" in check.detail


async def test_a_fabricated_record_id_is_rejected() -> None:
    check = await check_record(FakeConn(), record(record_id="999999999999"))

    assert check.verdict == "not_in_dataset"


async def test_a_near_miss_record_id_is_rejected() -> None:
    """One digit out. Plausible, checkable, and wrong."""
    check = await check_record(FakeConn(), record(record_id="110000350054"))

    assert check.verdict == "not_in_dataset"


async def test_a_dataset_with_no_public_identifier_is_rejected() -> None:
    """A modelled AirToxScreen value is a number for a hexagon, not a record
    somebody can look up. Accepting it would mean a citation with nothing behind
    it for a reader to check."""
    check = await check_record(FakeConn(), record(dataset="airtoxscreen"))

    assert check.verdict == "not_in_dataset"
    assert "not a dataset a record can be cited from" in check.detail


def test_the_datasets_that_can_be_cited_all_have_a_lookup() -> None:
    assert set(DATASET_LOOKUPS) == {"echo", "frs", "tri"}


# ---- The hexagon the draft is about -------------------------------------


async def test_the_hexagon_itself_is_a_citable_record() -> None:
    """The schema requires a citation on every factual claim, and a hexagon's
    score and demographics are factual claims. Without this the model had no
    legitimate way to attribute them, invented a dataset, and had otherwise
    sound drafts discarded for it."""
    check = await check_record(FakeConn(), record(record_id=H3, dataset="hex"), subject_h3=H3)

    assert check.ok
    assert "the hexagon this draft is about" in check.detail


async def test_citing_a_different_hexagon_is_rejected() -> None:
    """The figures would be real and about somewhere else, which is the one
    thing that can go wrong here."""
    check = await check_record(
        FakeConn(), record(record_id="88444600ddfffff", dataset="hex"), subject_h3=H3
    )

    assert check.verdict == "not_in_dataset"
    assert "but this draft is about" in check.detail


async def test_a_hexagon_citation_needs_to_know_which_hexagon() -> None:
    """Verifying one without the subject would pass anything."""
    check = await check_record(FakeConn(), record(record_id=H3, dataset="hex"))

    assert check.verdict == "not_in_dataset"


async def test_a_facility_citation_is_unaffected_by_the_subject_hexagon() -> None:
    check = await check_record(FakeConn(), record(), subject_h3=H3)

    assert check.ok


# ---- Whole documents ----------------------------------------------------


async def test_a_document_whose_citations_all_verify_passes() -> None:
    verification = await verify_document(
        FakeConn(), judge_model("supported"), letter(statute(), record())
    )

    assert verification.verified
    assert len(verification.checks) == 2


async def test_one_bad_citation_fails_the_whole_document() -> None:
    """Not shown with a warning, not shown with the citation removed. A warning
    is forgotten by whoever forwards the document, and a silently deleted
    citation leaves the remaining claims resting on nothing."""
    verification = await verify_document(
        FakeConn(),
        judge_model("supported"),
        letter(statute(), statute("42 U.S.C. § 9999")),
    )

    assert not verification.verified
    assert len(verification.failures) == 1


async def test_every_failure_is_reported_not_just_the_first() -> None:
    """The audit wants to know how a draft failed, and "the first thing we
    noticed" is a worse answer than "these three things"."""
    verification = await verify_document(
        FakeConn(),
        judge_model("supported"),
        letter(
            statute("42 U.S.C. § 9998"),
            statute("42 U.S.C. § 9999"),
            record(record_id="000000000000"),
        ),
    )

    assert len(verification.failures) == 3


def test_a_document_with_no_checks_does_not_count_as_verified() -> None:
    """The schema requires a citation, so this cannot happen today. A verifier
    that returned True for an empty list would be one that passed anything the
    schema ever stopped requiring."""
    assert not Verification().verified


def test_the_exception_names_what_failed() -> None:
    verification = Verification(
        checks=[
            CitationCheck(citation=statute("42 U.S.C. § 9999"), verdict="not_in_corpus"),
        ]
    )

    with pytest.raises(DraftUnverifiable, match="9999"):
        raise DraftUnverifiable(verification)


# ---- The audit log ------------------------------------------------------


async def test_every_failure_is_logged_with_the_citation_that_caused_it() -> None:
    from app.assistant.verifier import log_rejections

    conn = FakeConn()
    verification = await verify_document(
        conn,
        judge_model("not_supported", "no"),
        letter(statute(proposition="A claim the passage does not make.")),
    )

    written = await log_rejections(
        conn, verification, "88444600ddfffff", "public_comment_letter", "v-corpus", "v1", "gpt-4o"
    )

    assert written == 1
    row = conn.logged[0]
    assert row[0] == "88444600ddfffff"
    assert row[5] == "unsupported"
    assert row[7] == REAL_SECTION
    assert row[8] == "A claim the passage does not make."


async def test_nothing_is_logged_for_a_clean_draft() -> None:
    from app.assistant.verifier import log_rejections

    conn = FakeConn()
    verification = await verify_document(conn, judge_model("supported"), letter(statute()))

    assert await log_rejections(conn, verification, "h", "t", "c", "p", "m") == 0
    assert conn.logged == []
