"""Chunking, and the two invariants that make a chunk citable.

A chunk never spans two sections, and a chunk's label always names a subdivision
that contains the whole chunk. Everything else here is about size, which matters
for retrieval quality and not for whether a citation is honest.
"""

from __future__ import annotations

from corpus.chunking import Chunk, chunk_section
from corpus.parse import Block, Section


def section(*blocks: Block, number: str = "7412", heading: str = "Hazardous") -> Section:
    return Section(number=number, heading=heading, blocks=blocks)


def body(marker: str | None, text: str, depth: int = 0, citable: bool = True) -> Block:
    prefix = f"({marker}) " if marker else ""
    return Block(depth=depth, marker=marker, text=f"{prefix}{text}", citable=citable)


BASE = "42 U.S.C. § 7412"


def labels(chunks: list[Chunk]) -> list[str]:
    return [c.section_label for c in chunks]


def test_a_short_section_is_one_chunk_labelled_with_the_section() -> None:
    chunks = chunk_section(section(body("a", "Short."), body("b", "Also short.")), BASE)

    assert labels(chunks) == [BASE]


def test_the_heading_rides_on_every_chunk() -> None:
    """A passage retrieved from the middle of a long section otherwise arrives
    with no indication of which law it is."""
    chunks = chunk_section(
        section(body("a", "x" * 4000), body("b", "y" * 4000)), BASE, target_chars=5000
    )

    assert len(chunks) > 1
    assert all(c.text.startswith("42 U.S.C. § 7412. Hazardous.") for c in chunks)


def test_a_chunk_label_is_never_narrower_than_the_text_it_covers() -> None:
    """The invariant. A chunk holding (a) and (b) can only honestly be cited as
    the section; labelling it with the first marker in it would name a
    subdivision the quoted text is only partly inside."""
    chunks = chunk_section(
        section(body("a", "a" * 100), body("b", "b" * 100)), BASE, target_chars=100_000
    )

    assert labels(chunks) == [BASE]


def test_a_subsection_that_fits_keeps_its_own_label() -> None:
    chunks = chunk_section(
        section(body("a", "a" * 3000), body("b", "b" * 3000)), BASE, target_chars=4000
    )

    assert labels(chunks) == [f"{BASE}(a)", f"{BASE}(b)"]


def test_a_subsection_too_large_to_fit_splits_at_its_paragraphs() -> None:
    blocks = [
        body("a", "head"),
        body("1", "x" * 3000, depth=1),
        body("2", "y" * 3000, depth=1),
    ]

    chunks = chunk_section(section(*blocks), BASE, target_chars=4000)

    assert labels(chunks) == [f"{BASE}(a)", f"{BASE}(a)(1)", f"{BASE}(a)(2)"]


def test_an_uncitable_marker_does_not_reach_the_label() -> None:
    """Where the depth had to be guessed, the letter stays out of the citation
    and the chunk is cited against the nearest subdivision the publisher
    actually marked."""
    blocks = [
        body("c", "head"),
        body("9", "para", depth=1),
        body("i", "z" * 3000, depth=2, citable=False),
        body("ii", "w" * 3000, depth=2, citable=False),
    ]

    chunks = chunk_section(section(*blocks), BASE, target_chars=4000)

    assert all(not label.endswith("(i)") for label in labels(chunks))
    assert all(label.startswith(f"{BASE}(c)") for label in labels(chunks))


def test_ordinals_are_unique_within_a_label() -> None:
    """statute_chunk keys on (section_label, ordinal), so a subsection backed by
    two chunks has to number them."""
    blocks = [body("a", "head"), body(None, "x" * 12_000)]

    chunks = chunk_section(section(*blocks), BASE, target_chars=4000)

    keys = [(c.section_label, c.ordinal) for c in chunks]
    assert len(keys) == len(set(keys))
    ordinals = [c.ordinal for c in chunks if c.section_label == f"{BASE}(a)"]
    assert len(ordinals) > 1
    assert ordinals == list(range(len(ordinals)))


def test_two_sections_never_share_a_chunk() -> None:
    """Appendix B rule 2. Chunking is called per section, so this is a property
    of the interface rather than of an algorithm, and the test is here to keep
    it that way."""
    first = chunk_section(section(body("a", "x" * 200), number="7412"), BASE)
    second = chunk_section(section(body("a", "y" * 200), number="7413"), "42 U.S.C. § 7413")

    # Neither section's text nor its citation can appear in the other's chunks.
    assert all("7413" not in c.text and "y" * 200 not in c.text for c in first)
    assert all("7412" not in c.text and "x" * 200 not in c.text for c in second)
    assert {c.section_label for c in first} == {f"{BASE}(a)"}
    assert {c.section_label for c in second} == {"42 U.S.C. § 7413(a)"}


def test_an_oversized_single_block_is_split_rather_than_dropped() -> None:
    blocks = [body(None, ". ".join(f"Sentence {i}" for i in range(2000)))]

    chunks = chunk_section(section(*blocks), BASE, target_chars=2000)

    assert len(chunks) > 1
    assert all(len(c.text) <= 4000 for c in chunks)


def test_tiny_neighbouring_subdivisions_are_merged() -> None:
    """A section of twenty one-line definitions should not become twenty chunks
    that each embed to a point near everything and useful for nothing."""
    blocks = [body(str(i), f"Definition {i}.", depth=0) for i in range(1, 21)]

    chunks = chunk_section(section(*blocks), BASE, target_chars=6000, min_chars=400)

    assert len(chunks) < 20


def test_an_empty_section_produces_nothing() -> None:
    assert chunk_section(section(), BASE) == []
