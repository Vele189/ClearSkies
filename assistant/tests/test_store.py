"""Writing a corpus version, and sealing it.

The seal is the only irreversible step in the project, and the only one whose
failure is silent: a version recorded as sealed with the wrong hash reports a
corpus that nobody can reproduce, and says so only to whoever eventually tries.
So these tests are about what the seal reads before it writes — the database,
under a lock, in the transaction that closes the version — rather than about
what the ingesting process believed it had written.

No database. A fake connection stands in for asyncpg the way `test_embed` does,
keeping the rows in dictionaries and refusing what migration 0018's triggers
refuse, which is enough to exercise every branch these two functions have.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

import pytest

from corpus.chunking import Chunk
from corpus.ingest import Build, Document
from corpus.store import SealError, seal, version_row, write


class FakeConn:
    """Just enough of asyncpg, and of 0018, to write and seal a version."""

    def __init__(self) -> None:
        self.versions: dict[str, dict[str, Any]] = {}
        self.documents: list[dict[str, Any]] = []
        self.chunks: list[dict[str, Any]] = []
        self.unembedded = 0
        self.locked: list[str] = []
        self.log: list[str] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        snapshot = (deepcopy(self.versions), list(self.documents), list(self.chunks))
        try:
            yield self
        except Exception:
            self.versions, self.documents, self.chunks = snapshot
            raise

    async def execute(self, query: str, *args: Any) -> None:
        if "INSERT INTO statute_corpus_version" in query:
            self.log.append("insert version")
            self.versions.setdefault(
                args[0],
                {
                    "version": args[0],
                    "manifest_sha256": args[1],
                    "embedding_model": args[2],
                    "sealed_at": None,
                    "content_sha256": None,
                    "document_count": None,
                    "chunk_count": None,
                },
            )
        elif "DELETE FROM statute_chunk" in query:
            self.chunks = [c for c in self.chunks if c["corpus_version"] != args[0]]
        elif "DELETE FROM statute_document" in query:
            self.documents = [d for d in self.documents if d["corpus_version"] != args[0]]
        elif "INSERT INTO statute_document" in query:
            self._refuse_if_sealed(args[0])
            self.documents.append({"corpus_version": args[0], "document_id": args[1]})
        elif "INSERT INTO statute_chunk" in query:
            self._refuse_if_sealed(args[0])
            self.chunks.append(
                {
                    "corpus_version": args[0],
                    "document_id": args[1],
                    "section_label": args[2],
                    "ordinal": args[3],
                    "text": args[4],
                }
            )
        elif "UPDATE statute_corpus_version" in query:
            self.log.append("seal")
            row = self.versions[args[0]]
            self._refuse_if_sealed(args[0])
            row |= {
                "sealed_at": "now",
                "content_sha256": args[1],
                "document_count": args[2],
                "chunk_count": args[3],
            }
        else:  # pragma: no cover - a query this fake has not been taught
            raise AssertionError(query)

    def _refuse_if_sealed(self, version: str) -> None:
        """What the 0018 triggers do, so a test cannot pass by writing through."""
        if self.versions.get(version, {}).get("sealed_at") is not None:
            raise AssertionError(f"corpus version {version} is sealed")

    async def executemany(self, query: str, rows: list[tuple[Any, ...]]) -> None:
        for row in rows:
            await self.execute(query, *row)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "FOR UPDATE" in query:
            self.log.append("lock")
            self.locked.append(args[0])
            return self.versions.get(args[0])
        if "count(*) AS total" in query:
            total = len([c for c in self.chunks if c["corpus_version"] == args[0]])
            return {"total": total, "embedded": total - self.unembedded}
        return self.versions.get(args[0])

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return [c for c in self.chunks if c["corpus_version"] == args[0]]

    async def fetchval(self, query: str, *args: Any) -> int:
        return len([d for d in self.documents if d["corpus_version"] == args[0]])


def make_build(*texts: str, documents: int = 1) -> Build:
    """A build of `documents` documents, each holding the same chunks."""
    return Build(
        documents=[
            Document(
                document_id=f"doc-{n}",
                authority="A",
                citation="42 U.S.C. § 7412",
                jurisdiction="federal",
                edition="2024",
                source_url="https://example.test/doc",
                retrieved_at=None,  # type: ignore[arg-type]
                full_text=" ".join(texts),
                may_reason_from=True,
                chunks=[
                    Chunk(section_label="42 U.S.C. § 7412", ordinal=i, text=text)
                    for i, text in enumerate(texts)
                ],
            )
            for n in range(documents)
        ]
    )


# ---- Writing ------------------------------------------------------------


async def test_a_write_fills_the_version_it_opened() -> None:
    conn = FakeConn()

    await write(conn, "v1", make_build("one", "two"), "text-embedding-3-small")

    assert conn.versions["v1"]["sealed_at"] is None
    assert [c["text"] for c in conn.chunks] == ["one", "two"]


async def test_a_second_write_replaces_the_first_rather_than_appending() -> None:
    """An interrupted run is redone, not resumed, so a version's content hash
    cannot depend on how many times ingestion was interrupted."""
    conn = FakeConn()

    await write(conn, "v1", make_build("one", "two"), "m")
    await write(conn, "v1", make_build("three"), "m")

    assert [c["text"] for c in conn.chunks] == ["three"]


async def test_a_write_to_a_sealed_version_is_refused_before_it_starts() -> None:
    conn = FakeConn()
    build = make_build("one")
    await write(conn, "v1", build, "m")
    await seal(conn, "v1", build, force=True)

    with pytest.raises(SealError, match="already sealed"):
        await write(conn, "v1", make_build("two"), "m")

    assert [c["text"] for c in conn.chunks] == ["one"]


# ---- Sealing ------------------------------------------------------------


async def test_the_seal_records_what_the_database_holds() -> None:
    conn = FakeConn()
    build = make_build("one", "two")
    await write(conn, "v1", build, "m")

    await seal(conn, "v1", build, force=True)

    row = await version_row(conn, "v1")
    assert row is not None and row.sealed
    assert row.content_sha256 == build.content_sha256()
    assert (row.document_count, row.chunk_count) == (1, 2)


async def test_the_seal_locks_the_version_row_before_it_reads_the_chunks() -> None:
    """Without the lock, a concurrent write could land between the hash and
    the UPDATE, and the seal would vouch for text that is no longer there."""
    conn = FakeConn()
    build = make_build("one")
    await write(conn, "v1", build, "m")
    conn.log.clear()

    await seal(conn, "v1", build, force=True)

    assert conn.log == ["lock", "seal"]


async def test_a_seal_whose_rows_are_not_the_build_is_refused() -> None:
    """Something else wrote to the version. Recording the in-memory hash here
    would produce an audit trail that points at text the database does not
    have, which is worse than no audit trail because it looks like one."""
    conn = FakeConn()
    build = make_build("one", "two")
    await write(conn, "v1", build, "m")
    conn.chunks[0]["text"] = "something else"

    with pytest.raises(SealError, match="written to it"):
        await seal(conn, "v1", build, force=True)

    assert conn.versions["v1"]["sealed_at"] is None


async def test_a_seal_is_refused_when_chunks_are_missing_their_vectors() -> None:
    conn = FakeConn()
    build = make_build("one", "two")
    await write(conn, "v1", build, "m")
    conn.unembedded = 1

    with pytest.raises(SealError, match="without an embedding"):
        await seal(conn, "v1", build, force=True)

    assert conn.versions["v1"]["sealed_at"] is None


async def test_a_second_seal_is_refused() -> None:
    conn = FakeConn()
    build = make_build("one")
    await write(conn, "v1", build, "m")
    await seal(conn, "v1", build, force=True)

    with pytest.raises(SealError, match="already sealed"):
        await seal(conn, "v1", build, force=True)


async def test_a_version_that_was_never_opened_cannot_be_sealed() -> None:
    with pytest.raises(SealError, match="no corpus version"):
        await seal(FakeConn(), "v1", make_build("one"), force=True)


async def test_a_partial_corpus_is_not_sealed_and_says_what_is_missing() -> None:
    """An incomplete corpus is not published rather than published with a
    caveat: an unsealed version is invisible to retrieval and to the verifier."""
    conn = FakeConn()
    build = make_build("one")
    await write(conn, "v1", build, "m")

    with pytest.raises(SealError, match="la-const-art9-sec1"):
        await seal(conn, "v1", build)

    assert conn.versions["v1"]["sealed_at"] is None
