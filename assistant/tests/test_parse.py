"""Parsing, with the emphasis on the two ways a citation goes silently wrong.

Both failures this file guards against produce a citation that *exists*. A
reader can look it up, the verifier's existence check passes, and the section it
names is simply not the section the text came from. That is worse than a
fabricated citation, which at least announces itself.
"""

from __future__ import annotations

import pytest

from corpus import parse
from corpus.fetch import Fetched
from corpus.parse import ParseError, _blocks_from_markers, _infer_depth, _place, _succeeds

# ---- United States Code -------------------------------------------------


def test_sections_are_found_with_their_numbers_and_headings(us_code_doc: Fetched) -> None:
    sections = parse.us_code(us_code_doc)

    assert [s.number for s in sections] == ["7401", "7412"]
    assert sections[0].heading == "Congressional findings and declaration of purpose"


def test_a_repealed_section_is_not_in_the_corpus(us_code_doc: Fetched) -> None:
    """It has no operative text, and a corpus of what the law says has no room
    for a section that says nothing."""
    assert "7413" not in {s.number for s in parse.us_code(us_code_doc)}


def test_editorial_apparatus_is_excluded(us_code_doc: Fetched) -> None:
    """Source credits and amendment notes are not the statute.

    A model shown them alongside the statute quotes a committee note as though
    Congress enacted it, and the citation on that quote is a real section.
    """
    text = "\n".join(s.text for s in parse.us_code(us_code_doc))
    assert "69 Stat. 322" not in text
    assert "Amendment notes that are not the statute" not in text
    assert "The Congress finds" in text


def test_an_en_dashed_section_number_survives_as_a_hyphen(us_code_dashed_doc: Fetched) -> None:
    """govinfo writes 2000d–1 with an en dash.

    Matching only the hyphen does not fail, it truncates: the number comes out
    as "2000d" and the rest is pushed into the heading, so all nine sections of
    Title VI end up sharing one citation.
    """
    (section,) = parse.us_code(us_code_dashed_doc)

    assert section.number == "2000d-1"
    assert section.heading.startswith("Federal authority")


def test_a_clause_is_not_promoted_to_a_subsection(us_code_doc: Fetched) -> None:
    """The (i) inside § 7412(c)(9)(B) is not § 7412(i).

    Both exist. They are about different things. Reading the clause as the
    subsection produces a citation that checks out against the corpus and is
    wrong about the law, which is the exact failure Phase 3 exists to prevent.
    """
    section = next(s for s in parse.us_code(us_code_doc) if s.number == "7412")
    clause = next(b for b in section.blocks if b.text.startswith("(i) In the case"))
    subsection = next(b for b in section.blocks if b.text.startswith("(i) Schedule for compliance"))

    assert clause.depth > subsection.depth
    assert subsection.depth == 0


def test_a_marker_inferred_from_body_text_is_not_citable(us_code_doc: Fetched) -> None:
    """Where the publisher marked the subdivision, the letter can be cited.
    Where the depth had to be guessed, it cannot."""
    section = next(s for s in parse.us_code(us_code_doc) if s.number == "7412")

    marked = next(b for b in section.blocks if b.text.startswith("(c) Source"))
    guessed = next(b for b in section.blocks if b.text.startswith("(i) In the case"))

    assert marked.citable
    assert not guessed.citable


def test_a_document_without_the_expected_markup_is_refused() -> None:
    from tests.conftest import make_fetched

    with pytest.raises(ParseError, match="govinfo has changed"):
        parse.us_code(make_fetched("<html><body><p>Nothing here.</p></body></html>"))


# ---- Depth inference ----------------------------------------------------


@pytest.mark.parametrize(
    ("marker", "previous", "expected"),
    [
        ("b", "a", True),
        ("i", "h", True),  # the ninth letter, not the first numeral
        ("2", "1", True),
        ("ii", "i", True),
        ("iv", "iii", True),
        ("B", "A", True),
        ("i", "c", False),  # the trap: c is also a roman numeral
        ("i", "a", False),
        ("a", "b", False),
        ("3", "1", False),
        ("A", "a", False),
    ],
)
def test_succession_decides_which_sequence_a_marker_continues(
    marker: str, previous: str, expected: bool
) -> None:
    assert _succeeds(marker, previous) is expected


def test_a_clause_opens_below_the_deepest_open_subdivision() -> None:
    # (c)(9)(B) are open; (i) starts a new sequence under them.
    assert _infer_depth("i", ["c", "9", "B"]) == 3


def test_a_subsection_continues_its_own_sequence() -> None:
    # (h) has just closed at the top level; (i) is the next subsection.
    assert _infer_depth("i", ["h"]) == 0


# ---- The two markers that are both a letter and a numeral ---------------
#
# (i) after (h), with a paragraph open in between, is either the next
# subsection or the first clause of that paragraph. Both readings produce a
# label that exists. Only one of them is about the right subject.


def test_a_clause_under_an_open_paragraph_is_read_as_a_clause() -> None:
    """(h)(1)(i) followed by (ii): a roman sequence has started."""
    assert _place("i", ["h", "1"], ("ii",)) == (2, True)


def test_a_subsection_after_its_paragraphs_is_read_as_a_subsection() -> None:
    """(h)(1), (h)(2), then (i)(1): the letters have carried on. This is the
    shape of 42 U.S.C. § 7412(h) and § 7412(i), and reading it the other way
    would bury a whole subsection inside the one before it."""
    assert _place("i", ["h", "2"], ("1",)) == (0, True)
    assert _place("i", ["h", "2"], ("j",)) == (0, True)


def test_an_undecidable_marker_is_placed_but_not_citable() -> None:
    """Nothing follows it, so nothing says which sequence it belongs to. It
    still delimits its text, and its letter stays out of every label."""
    assert _place("i", ["h", "1"], ()) == (2, False)


def test_a_subclause_is_told_apart_from_the_next_subparagraph() -> None:
    """The same collision one level down: (I) after (H), with a clause open."""
    assert _place("I", ["a", "1", "H", "i"], ("II",)) == (4, True)
    assert _place("I", ["a", "1", "H", "i"], ("J",)) == (2, True)


def test_a_roman_reading_needs_a_parent_that_could_have_one() -> None:
    """(i) after (ii) is not a clause of (ii): a CFR clause opens (A), not (i).
    With only one reading left there is nothing to be uncertain about."""
    assert _place("i", ["h", "1", "ii"], ()) == (0, True)


# ---- eCFR ---------------------------------------------------------------


def test_cfr_sections_and_their_numbers(ecfr_doc: Fetched) -> None:
    sections = parse.ecfr(ecfr_doc)

    assert [s.number for s in sections] == ["7.10", "7.35"]
    assert sections[0].heading == "Purpose of this part."


def test_cfr_paragraphs_nest_under_their_subsection(ecfr_doc: Fetched) -> None:
    section = next(s for s in parse.ecfr(ecfr_doc) if s.number == "7.35")
    subsection = next(b for b in section.blocks if b.marker == "a")
    paragraph = next(b for b in section.blocks if b.marker == "1")

    assert subsection.depth == 0
    assert paragraph.depth == 1


def test_a_cfr_clause_does_not_become_a_subsection() -> None:
    """The CFR nests (h)(1)(i), and its paragraphs arrive as a flat run of
    text with the markers inline. Read as continuing (h), the clause becomes
    § 7.35(i) and the subsection that really is (i) becomes (ii)(i): two
    citations that a reader can look up and that are about something else.
    """
    blocks = _blocks_from_markers(
        [
            "(h) Heading.",
            "(1) A paragraph of it.",
            "(i) The first clause.",
            "(ii) The second clause.",
            "(i) The next subsection.",
            "(1) A paragraph of that one.",
        ]
    )

    assert [(b.depth, b.marker, b.citable) for b in blocks] == [
        (0, "h", True),
        (1, "1", True),
        (2, "i", False),
        (2, "ii", False),
        (0, "i", True),
        (1, "1", True),
    ]


def test_a_cfr_document_with_no_sections_is_refused() -> None:
    from tests.conftest import make_fetched

    with pytest.raises(ParseError, match="schema has changed"):
        parse.ecfr(make_fetched("<DIV5></DIV5>"))


# ---- Case law -----------------------------------------------------------


def test_an_opinion_is_one_section_with_no_invented_subdivisions(caselaw_doc: Fetched) -> None:
    """There is no such thing as "paragraph 14 of Sandoval" in a citation a
    reader can check, so the opinion carries one label."""
    (section,) = parse.caselaw(caselaw_doc)

    assert section.number == ""
    assert section.heading == "Alexander v. Sandoval"
    assert all(b.marker is None for b in section.blocks)


def test_publisher_headnotes_are_not_treated_as_the_court_speaking(caselaw_doc: Fetched) -> None:
    (section,) = parse.caselaw(caselaw_doc)

    assert "publisher's summary" not in section.text
    assert "no private right of action" in section.text


def test_a_record_with_no_opinion_text_is_refused() -> None:
    from tests.conftest import make_fetched

    with pytest.raises(ParseError, match="no opinion text"):
        parse.caselaw(make_fetched('{"casebody": {"opinions": []}}'))
