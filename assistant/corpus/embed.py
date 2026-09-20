"""Embed the corpus, before it is sealed.

The order matters and is forced by the schema rather than chosen. Migration 0018
refuses every write to a sealed corpus version, embeddings included, so vectors
have to land while the version is still open. That turns into a useful
invariant: a sealed corpus is fully embedded, and retrieval against a sealed
version never meets a chunk it cannot rank. `store.seal` enforces it.

Embedding is the one step in the corpus build that costs money and touches a
third-party API, so it is also the one step that is careful about doing it
twice. Only chunks with no vector are sent, batches are small enough to retry
cheaply, and the token count is reported, because an ingestion that quietly
re-embedded the whole corpus on every run would be a bill nobody was watching.

The dimension is pinned to what `statute_chunk.embedding` declares. OpenAI's v3
embedding models accept a `dimensions` argument and truncate accordingly, so the
column is the source of truth and a mismatch is a startup error rather than a
corpus holding vectors of two shapes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Must equal the dimension in migration 0010. A corpus holding vectors from two
# models, or two widths, returns quietly worse retrievals rather than failing,
# which is the failure mode worth spending a constant on.
EMBEDDING_DIMENSIONS = 1024

# Small enough that a failure costs little to retry and large enough that the
# whole corpus is a few dozen requests rather than a few thousand.
BATCH_SIZE = 96


class EmbeddingError(RuntimeError):
    """The embedding provider did not return usable vectors."""


@dataclass
class EmbeddingRun:
    """What one embedding pass did."""

    chunks: int = 0
    batches: int = 0
    tokens: int = 0
    skipped: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        """text-embedding-3-small is $0.02 per million tokens.

        Printed rather than enforced. The hard cap belongs with the provider,
        per CS-306, because a limit the application enforces is a limit that
        stops working when the application has a bug.
        """
        return self.tokens / 1_000_000 * 0.02


PENDING = """
SELECT chunk_id, text
  FROM statute_chunk
 WHERE corpus_version = $1
   AND embedding IS NULL
 ORDER BY chunk_id
"""

STORE = "UPDATE statute_chunk SET embedding = $2 WHERE chunk_id = $1"

COUNTS = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
  FROM statute_chunk WHERE corpus_version = $1
"""


def to_pgvector(values: list[float]) -> str:
    """pgvector's text input format.

    Passed as text rather than through a type codec so the assistant package
    needs no pgvector Python binding: the column accepts '[1,2,3]' and asyncpg
    sends a string. One less dependency for one format that has not changed.
    """
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def counts(conn: Any, version: str) -> tuple[int, int]:
    row = await conn.fetchrow(COUNTS, version)
    return int(row["total"]), int(row["embedded"])


async def embed_version(
    conn: Any,
    version: str,
    client: Any,
    model: str,
    dimensions: int = EMBEDDING_DIMENSIONS,
    batch_size: int = BATCH_SIZE,
) -> EmbeddingRun:
    """Give every unembedded chunk of one version a vector.

    Resumable by construction: what it selects is what is missing, so a run
    interrupted after forty batches picks up at forty-one rather than starting
    again or, worse, appearing to succeed with a hole in the middle.
    """
    run = EmbeddingRun()
    total, already = await counts(conn, version)
    run.skipped = already
    if total == 0:
        raise EmbeddingError(f"corpus version {version} has no chunks to embed")

    rows = await conn.fetch(PENDING, version)
    if not rows:
        log.info("corpus version %s is already fully embedded (%d chunks)", version, total)
        return run

    log.info(
        "embedding %d of %d chunks in corpus version %s with %s",
        len(rows),
        total,
        version,
        model,
    )

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        response = await client.embeddings.create(
            model=model,
            input=[row["text"] for row in batch],
            dimensions=dimensions,
        )
        vectors = response.data
        if len(vectors) != len(batch):
            raise EmbeddingError(
                f"asked for {len(batch)} embeddings and got {len(vectors)}; "
                "refusing to guess which chunk each belongs to"
            )

        # The API documents that results come back in input order, and index is
        # returned so it can be checked rather than assumed. Assuming it and
        # being wrong would attach every vector to the wrong statute, which no
        # later step could detect: retrieval would simply be bad.
        for offset, item in enumerate(vectors):
            if getattr(item, "index", offset) != offset:
                raise EmbeddingError("embedding results came back out of order")
            values = item.embedding
            if len(values) != dimensions:
                raise EmbeddingError(
                    f"{model} returned {len(values)} dimensions, expected {dimensions}. "
                    "statute_chunk.embedding has a fixed width; changing models "
                    "means a migration and a re-embed."
                )
            await conn.execute(STORE, batch[offset]["chunk_id"], to_pgvector(values))

        run.batches += 1
        run.chunks += len(batch)
        usage = getattr(response, "usage", None)
        run.tokens += int(getattr(usage, "total_tokens", 0) or 0)
        log.info("  batch %d: %d chunks, %d tokens", run.batches, len(batch), run.tokens)

    return run
