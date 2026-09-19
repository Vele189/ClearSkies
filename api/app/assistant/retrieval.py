"""Retrieval over the sealed statute corpus.

The property this module exists to have: **it cannot return anything that is not
a real, in-corpus section.** Not because the prompt says so, but because there is
no query here that can reach anything else.

That is one line of SQL doing the work. Every read goes through
`statute_corpus_active`, the view migration 0018 defines over the newest *sealed*
corpus version. A caller cannot forget to filter by version, because there is no
version column to filter on in the obvious query; cannot reach an unsealed
version being built right now, because the view does not show one; and cannot
reach a superseded version, for the same reason. Getting it wrong requires
writing a different query against `statute_chunk` by hand, which is a diff a
reviewer sees.

Two things come back with every passage and neither is decoration. The section
label is what a citation has to quote character for character, so CS-305 can look
it up. And `may_reason_from` is false for the two cases of Appendix B.3, carried
out of the database rather than inferred from the citation text, so the prompt
layer and the verifier read the same flag rather than each deciding for itself
what counts as case law.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Must match statute_chunk.embedding in migration 0010 and the width the corpus
# was built at. A mismatch is caught here rather than by Postgres, because the
# error Postgres gives names a type and not a cause.
EMBEDDING_DIMENSIONS = 1024

DEFAULT_LIMIT = 8

# Cosine distance, matching the hnsw vector_cosine_ops index. Above this a
# passage is not about the question: returning it anyway gives the model
# plausible-looking text to cite for a claim it does not support, which is
# worse than returning less.
MAX_DISTANCE = 0.75


class RetrievalError(RuntimeError):
    """Retrieval could not run. Never a reason to draft without context."""


@dataclass(frozen=True)
class Passage:
    """One retrieved chunk, with everything a citation to it needs."""

    section_label: str
    document_id: str
    text: str
    distance: float
    authority: str
    citation: str
    jurisdiction: str
    edition: str
    source_url: str
    may_reason_from: bool
    corpus_version: str

    @property
    def is_case_law(self) -> bool:
        return self.jurisdiction == "case_law"


# `statute_corpus_active` is the whole guarantee. See the module docstring.
SEARCH = """
SELECT section_label,
       document_id,
       text,
       embedding <=> $1::vector AS distance,
       authority,
       citation,
       jurisdiction,
       edition,
       source_url,
       may_reason_from,
       corpus_version
  FROM statute_corpus_active
 WHERE embedding IS NOT NULL
 ORDER BY embedding <=> $1::vector
 LIMIT $2
"""

# The ordering here must match `statute_corpus_active` in migration 0019
# exactly, including the tie-break. Two versions can share a sealed_at, and an
# ordering that differs from the view's would let this function name one corpus
# while retrieval reads another. Every draft is stamped with what this returns,
# so the two disagreeing means a draft carrying a corpus version it was not
# written against: an audit trail that is wrong rather than missing.
ACTIVE_VERSION = """
SELECT version, sealed_at, chunk_count, embedding_model
  FROM statute_corpus_version
 WHERE sealed_at IS NOT NULL
 ORDER BY sealed_at DESC, version DESC
 LIMIT 1
"""


def to_pgvector(values: list[float]) -> str:
    """pgvector's text input format, so no Python binding is needed."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def active_version(conn: Any) -> str | None:
    """The corpus version retrieval is reading, or None if nothing is sealed.

    Stamped onto every generated draft. A draft that cannot say which corpus it
    was written against is a draft nobody can re-verify later.
    """
    row = await conn.fetchrow(ACTIVE_VERSION)
    return None if row is None else str(row["version"])


async def embed_query(client: Any, model: str, text: str) -> list[float]:
    """One vector for the question being asked.

    The same model the corpus was embedded with, which is not a detail: vectors
    from two models share a coordinate space only by coincidence, and a mismatch
    produces retrieval that is subtly bad rather than obviously broken.
    """
    response = await client.embeddings.create(
        model=model, input=[text], dimensions=EMBEDDING_DIMENSIONS
    )
    values: list[float] = list(response.data[0].embedding)
    if len(values) != EMBEDDING_DIMENSIONS:
        raise RetrievalError(
            f"{model} returned {len(values)} dimensions, expected {EMBEDDING_DIMENSIONS}"
        )
    return values


async def search(
    conn: Any,
    vector: list[float],
    limit: int = DEFAULT_LIMIT,
    max_distance: float = MAX_DISTANCE,
) -> list[Passage]:
    """The nearest passages in the sealed corpus, closest first."""
    rows = await conn.fetch(SEARCH, to_pgvector(vector), limit)
    passages = [Passage(**dict(row)) for row in rows]
    return [p for p in passages if p.distance <= max_distance]


async def retrieve(
    conn: Any,
    client: Any,
    model: str,
    query: str,
    limit: int = DEFAULT_LIMIT,
    max_distance: float = MAX_DISTANCE,
) -> list[Passage]:
    """Embed a question and return the passages that answer it.

    An empty list is a real and useful answer. It means the corpus has nothing
    close to the question, and the right response upstream is to draft without
    that claim, or not to draft at all, rather than to proceed on whatever the
    nearest unrelated section happened to be.
    """
    if not query.strip():
        raise RetrievalError("cannot retrieve on an empty query")

    vector = await embed_query(client, model, query)
    passages = await search(conn, vector, limit=limit, max_distance=max_distance)
    log.info(
        "retrieval: %d passages for %r (closest %.3f)",
        len(passages),
        query[:60],
        passages[0].distance if passages else float("nan"),
    )
    return passages


# What each document type always needs to have in front of it, whatever the
# user typed. Retrieving on the request alone is not enough: "draft a comment
# letter about this permit" embeds to nothing in particular, the public
# participation right never comes back, and the model correctly refuses for want
# of an authority it should have been handed. These are the standing questions
# for each type, asked alongside the user's.
STANDING_QUERIES: dict[str, tuple[str, ...]] = {
    "public_comment_letter": (
        "public participation and comment rights in operating permit proceedings",
        "requirements a permit applicant must meet before a permit is issued",
        "hazardous air pollutants and emission standards for source categories",
    ),
    "agency_complaint_draft": (
        "discrimination by recipients of federal financial assistance",
        "how to file a complaint about discrimination with the agency",
        "disparate impact criteria and methods of administering a program",
    ),
    "community_briefing_sheet": (
        "hazardous air pollutants listed by Congress",
        "public participation rights in permit proceedings",
        "toxic chemical release reporting by facilities",
    ),
    "journalist_fact_sheet": (
        "toxic chemical release reporting requirements",
        "hazardous air pollutants and major source thresholds",
        "permits required to discharge or emit pollutants",
    ),
}


async def retrieve_for(
    conn: Any,
    client: Any,
    model: str,
    document_type: str,
    request: str,
    limit: int = DEFAULT_LIMIT,
    max_distance: float = MAX_DISTANCE,
) -> list[Passage]:
    """Passages for one drafting request: the user's question and the standing ones.

    Merged and deduplicated by section label, nearest first. Asking several
    questions rather than one is what stops a vaguely worded request retrieving
    nothing and the model refusing for want of an authority that is sitting in
    the corpus.

    Every query still goes through the same sealed view, so widening what is
    asked does not widen what can come back.
    """
    queries = [request, *STANDING_QUERIES.get(document_type, ())]
    seen: set[tuple[str, str]] = set()
    merged: list[Passage] = []
    for query in queries:
        for passage in await retrieve(
            conn, client, model, query, limit=limit, max_distance=max_distance
        ):
            key = (passage.section_label, passage.text)
            if key in seen:
                continue
            seen.add(key)
            merged.append(passage)

    merged.sort(key=lambda p: p.distance)
    return merged[: limit * 2]


def as_context(passages: list[Passage]) -> str:
    """The retrieved passages, formatted for the prompt.

    Every passage is labelled with the exact string a citation must carry, and
    the two cases are marked in the context itself rather than only in the
    instructions. A rule stated once at the top of a long prompt competes with
    everything after it; a rule attached to the passage it governs is read at
    the moment it applies.
    """
    blocks: list[str] = []
    for passage in passages:
        header = f"[{passage.section_label}] ({passage.authority}, {passage.edition})"
        if not passage.may_reason_from:
            header += (
                "\nCITE ONLY. This is case law included for context. You may cite it "
                "and you may not reason from it to a legal conclusion."
            )
        blocks.append(f"{header}\n{passage.text}")
    return "\n\n---\n\n".join(blocks)
