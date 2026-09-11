"""Embedding, and the ways a batch can go wrong without saying so.

Every test here is about a failure that would be invisible afterwards. A vector
attached to the wrong chunk, a width that does not match the column, a batch
silently short: none of these raises later, and none shows up as anything but
retrieval that is a bit worse than it should be. So they are caught at the point
of writing or not at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from corpus.embed import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    EmbeddingRun,
    embed_version,
    to_pgvector,
)


class FakeEmbeddings:
    def __init__(
        self,
        dimensions: int = EMBEDDING_DIMENSIONS,
        drop: int = 0,
        shuffle: bool = False,
    ) -> None:
        self.dimensions = dimensions
        self.drop = drop
        self.shuffle = shuffle
        self.batches: list[list[str]] = []

    async def create(self, model: str, input: list[str], dimensions: int) -> Any:
        self.batches.append(list(input))
        items = [
            type("Item", (), {"index": i, "embedding": [float(i)] * self.dimensions})()
            for i in range(len(input) - self.drop)
        ]
        if self.shuffle and len(items) > 1:
            items[0], items[1] = items[1], items[0]
        return type(
            "Response",
            (),
            {"data": items, "usage": type("U", (), {"total_tokens": 10 * len(input)})()},
        )()


class FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.embeddings = FakeEmbeddings(**kwargs)


class FakeConn:
    """Just enough of asyncpg to record what would have been written."""

    def __init__(self, pending: int, already: int = 0) -> None:
        self.pending = [{"chunk_id": i, "text": f"chunk {i}"} for i in range(1, pending + 1)]
        self.already = already
        self.stored: dict[int, str] = {}

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        return {"total": len(self.pending) + self.already, "embedded": self.already}

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return self.pending

    async def execute(self, query: str, *args: Any) -> None:
        self.stored[int(args[0])] = str(args[1])


async def test_every_pending_chunk_gets_a_vector() -> None:
    conn = FakeConn(pending=5)

    run = await embed_version(conn, "v1", FakeClient(), "text-embedding-3-small")

    assert run.chunks == 5
    assert set(conn.stored) == {1, 2, 3, 4, 5}


async def test_only_chunks_without_a_vector_are_sent() -> None:
    """Re-running ingestion must not re-embed the corpus. A step that quietly
    paid for the whole corpus again on every run is a bill nobody is watching."""
    conn = FakeConn(pending=0, already=2850)

    run = await embed_version(conn, "v1", FakeClient(), "text-embedding-3-small")

    assert run.chunks == 0
    assert run.skipped == 2850
    assert conn.stored == {}


async def test_batching_covers_every_chunk_exactly_once() -> None:
    conn = FakeConn(pending=10)
    client = FakeClient()

    await embed_version(conn, "v1", client, "text-embedding-3-small", batch_size=3)

    sent = [text for batch in client.embeddings.batches for text in batch]
    assert sent == [f"chunk {i}" for i in range(1, 11)]
    assert len(client.embeddings.batches) == 4


async def test_a_short_batch_is_refused_rather_than_guessed_at() -> None:
    """Fewer vectors than inputs means there is no way to know which chunk each
    belongs to, and a guess attaches statutes to the wrong text permanently."""
    conn = FakeConn(pending=4)

    with pytest.raises(EmbeddingError, match="refusing to guess"):
        await embed_version(conn, "v1", FakeClient(drop=1), "text-embedding-3-small")


async def test_results_out_of_order_are_refused() -> None:
    """No later step could detect this. Retrieval would simply be bad."""
    conn = FakeConn(pending=4)

    with pytest.raises(EmbeddingError, match="out of order"):
        await embed_version(conn, "v1", FakeClient(shuffle=True), "text-embedding-3-small")


async def test_the_wrong_width_is_refused() -> None:
    """statute_chunk.embedding has a fixed width, and a corpus holding vectors
    from two models returns quietly worse retrievals rather than failing."""
    conn = FakeConn(pending=2)

    with pytest.raises(EmbeddingError, match="dimensions"):
        await embed_version(conn, "v1", FakeClient(dimensions=512), "text-embedding-3-small")


async def test_a_version_with_no_chunks_is_an_error() -> None:
    conn = FakeConn(pending=0, already=0)

    with pytest.raises(EmbeddingError, match="no chunks"):
        await embed_version(conn, "v1", FakeClient(), "text-embedding-3-small")


async def test_token_usage_is_reported() -> None:
    conn = FakeConn(pending=4)

    run = await embed_version(conn, "v1", FakeClient(), "text-embedding-3-small")

    assert run.tokens == 40
    assert run.estimated_cost_usd > 0


def test_a_vector_is_formatted_the_way_pgvector_parses_it() -> None:
    assert to_pgvector([1.0, -0.5, 0.0]) == "[1.0,-0.5,0.0]"


def test_an_empty_run_costs_nothing() -> None:
    assert EmbeddingRun().estimated_cost_usd == 0.0
