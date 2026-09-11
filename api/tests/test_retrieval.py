"""Retrieval: the context it builds, and the guards it keeps.

The database half of this is `test_retrieval_sql.py`, which needs a corpus. What
is here runs without one, and covers the parts that decide whether a passage
reaches the model in a state a citation can be checked against.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.assistant.retrieval import (
    EMBEDDING_DIMENSIONS,
    MAX_DISTANCE,
    Passage,
    RetrievalError,
    as_context,
    embed_query,
    retrieve,
    search,
    to_pgvector,
)


def passage(
    section_label: str = "42 U.S.C. § 7412(b)",
    distance: float = 0.2,
    may_reason_from: bool = True,
    jurisdiction: str = "federal",
    text: str = "The Congress establishes a list of hazardous air pollutants.",
) -> Passage:
    return Passage(
        section_label=section_label,
        document_id="usc-42-chap85",
        text=text,
        distance=distance,
        authority="Clean Air Act",
        citation="42 U.S.C. §§ 7401–7671q",
        jurisdiction=jurisdiction,
        edition="United States Code, 2024 Edition",
        source_url="https://www.govinfo.gov/example",
        may_reason_from=may_reason_from,
        corpus_version="appendix-b-test",
    )


class FakeEmbeddings:
    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: list[str] = []

    async def create(self, model: str, input: list[str], dimensions: int) -> Any:
        self.calls.append(input[0])

        class Item:
            embedding = [0.1] * self.dimensions

        class Response:
            data = [Item()]

        return Response()


class FakeClient:
    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.embeddings = FakeEmbeddings(dimensions)


class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        return self.rows


def row(**overrides: Any) -> dict[str, Any]:
    base = passage().__dict__.copy()
    base.update(overrides)
    return base


# ---- The context handed to the model ------------------------------------


def test_every_passage_carries_the_label_a_citation_must_quote() -> None:
    """The model copies this string. If it is not in the context, the model
    composes one, and a composed citation is one the verifier cannot find."""
    context = as_context([passage(section_label="42 U.S.C. § 7661a")])

    assert "[42 U.S.C. § 7661a]" in context


def test_case_law_is_marked_cite_only_on_the_passage_itself() -> None:
    """Appendix B.3 permits citation and forbids reasoning to a legal
    conclusion. Stating that once at the top of a long prompt makes it compete
    with everything after it; stating it on the passage puts it where it
    applies."""
    context = as_context([passage(section_label="532 U.S. 275 (2001)", may_reason_from=False)])

    assert "CITE ONLY" in context
    assert "may not reason from it" in context


def test_a_statute_passage_is_not_marked_cite_only() -> None:
    assert "CITE ONLY" not in as_context([passage()])


def test_passages_are_separated_so_two_sections_cannot_read_as_one() -> None:
    context = as_context(
        [passage(section_label="42 U.S.C. § 7412"), passage(section_label="42 U.S.C. § 7413")]
    )

    assert context.count("---") >= 1
    assert "[42 U.S.C. § 7412]" in context
    assert "[42 U.S.C. § 7413]" in context


def test_an_empty_result_produces_empty_context() -> None:
    assert as_context([]) == ""


# ---- The guards ---------------------------------------------------------


async def test_an_empty_query_is_refused() -> None:
    """Whatever comes back for an empty question is not about anything."""
    with pytest.raises(RetrievalError, match="empty query"):
        await retrieve(FakeConn([]), FakeClient(), "text-embedding-3-small", "   ")


async def test_a_model_returning_the_wrong_width_is_refused() -> None:
    """Vectors from two models share a coordinate space only by coincidence, so
    a width mismatch is caught here rather than becoming quietly bad ranking."""
    with pytest.raises(RetrievalError, match="dimensions"):
        await embed_query(FakeClient(dimensions=512), "text-embedding-3-small", "x")


async def test_distant_passages_are_dropped() -> None:
    """A passage that is not about the question gives the model
    plausible-looking text to cite for a claim it does not support."""
    conn = FakeConn([row(distance=0.1), row(distance=MAX_DISTANCE + 0.2)])

    results = await search(conn, [0.1] * EMBEDDING_DIMENSIONS)

    assert len(results) == 1
    assert results[0].distance == 0.1


async def test_retrieval_may_return_nothing() -> None:
    """An empty list is a real answer: the corpus has nothing close. Drafting
    on the nearest unrelated section instead is the failure to avoid."""
    conn = FakeConn([row(distance=MAX_DISTANCE + 0.5)])

    assert await retrieve(conn, FakeClient(), "text-embedding-3-small", "unrelated") == []


async def test_retrieval_reads_only_the_active_corpus_view() -> None:
    """The whole 'cannot return anything outside the versioned corpus'
    guarantee is this: the query names the view, which is defined over the
    newest sealed version. Reaching anything else needs a different query
    written by hand, which is a diff a reviewer sees."""
    conn = FakeConn([row()])

    await retrieve(conn, FakeClient(), "text-embedding-3-small", "hazardous air pollutants")

    assert "statute_corpus_active" in conn.queries[0]
    assert "statute_chunk" not in conn.queries[0]


def test_a_vector_is_sent_in_the_format_pgvector_parses() -> None:
    assert to_pgvector([1.0, -0.5]) == "[1.0,-0.5]"


def test_case_law_is_identifiable_from_the_passage() -> None:
    assert passage(jurisdiction="case_law").is_case_law
    assert not passage().is_case_law
