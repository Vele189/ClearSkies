"""Measure retrieval against the hand-written question set.

Reports two numbers per question: whether the expected section came back at all
within the top *k*, and at what rank. Both matter and they fail differently. A
section that never comes back is a claim the assistant cannot make. A section
that comes back eighth is one the model may not read carefully among seven
closer passages, so a drop in mean rank is a real regression even while recall
stays at one.

This is a spot-check and not a benchmark, and the distinction is worth keeping.
Twenty hand-written pairs cannot tell you the corpus retrieves well. They can
tell you it has stopped retrieving things it used to, which is the failure that
would otherwise be discovered by reading a bad draft.

The query runs through exactly the path the API uses, `statute_corpus_active`,
so a result here is a statement about production retrieval rather than about a
query written for the test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from corpus.embed import EMBEDDING_DIMENSIONS, to_pgvector
from corpus.questions import QUESTIONS, Question

log = logging.getLogger(__name__)

DEFAULT_K = 8

SEARCH = """
SELECT section_label, document_id, embedding <=> $1::vector AS distance
  FROM statute_corpus_active
 WHERE embedding IS NOT NULL
 ORDER BY embedding <=> $1::vector
 LIMIT $2
"""


@dataclass(frozen=True)
class Hit:
    question: Question
    rank: int | None
    closest: str
    distance: float

    @property
    def found(self) -> bool:
        return self.rank is not None


@dataclass
class Report:
    hits: list[Hit]
    k: int

    @property
    def found(self) -> int:
        return sum(1 for h in self.hits if h.found)

    @property
    def recall(self) -> float:
        return self.found / len(self.hits) if self.hits else 0.0

    @property
    def mean_rank(self) -> float:
        """Over the questions that were answered at all.

        Averaging a miss as rank k would make recall and rank move together and
        hide which of the two actually changed.
        """
        ranks = [h.rank for h in self.hits if h.rank is not None]
        return sum(ranks) / len(ranks) if ranks else float("nan")

    @property
    def misses(self) -> list[Hit]:
        return [h for h in self.hits if not h.found]


async def run(
    conn: Any,
    client: Any,
    model: str,
    questions: tuple[Question, ...] = QUESTIONS,
    k: int = DEFAULT_K,
) -> Report:
    """Ask every question and record where its expected section landed."""
    hits: list[Hit] = []
    for question in questions:
        response = await client.embeddings.create(
            model=model, input=[question.text], dimensions=EMBEDDING_DIMENSIONS
        )
        vector = list(response.data[0].embedding)
        rows = await conn.fetch(SEARCH, to_pgvector(vector), k)

        rank: int | None = None
        for position, row in enumerate(rows, start=1):
            # A prefix match: a question about § 7412(b) is answered by any
            # subdivision of it, and demanding an exact label would measure the
            # chunker rather than retrieval.
            if str(row["section_label"]).startswith(question.expect):
                rank = position
                break

        hits.append(
            Hit(
                question=question,
                rank=rank,
                closest=str(rows[0]["section_label"]) if rows else "",
                distance=float(rows[0]["distance"]) if rows else float("nan"),
            )
        )
    return Report(hits=hits, k=k)


def render(report: Report) -> str:
    lines = [
        f"Retrieval spot-check over {len(report.hits)} questions, top {report.k}",
        "",
    ]
    for hit in report.hits:
        mark = f"rank {hit.rank}" if hit.found else "MISS"
        lines.append(f"  {mark:<8} {hit.question.expect:<24} {hit.question.text[:58]}")
        if not hit.found:
            lines.append(f"           closest was {hit.closest} at {hit.distance:.3f}")
    lines += [
        "",
        f"  recall@{report.k}   {report.found}/{len(report.hits)} ({report.recall:.0%})",
        f"  mean rank    {report.mean_rank:.2f} (of the {report.found} found)",
    ]
    return "\n".join(lines)
