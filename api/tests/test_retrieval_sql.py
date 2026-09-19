"""Retrieval against a real database, and the isolation it depends on.

The claim CS-302 makes is that retrieval cannot return anything outside the
versioned corpus, by construction. `test_retrieval.py` shows the query names the
view. This file shows the view does what the claim needs, against real Postgres
with real pgvector, because the alternative is trusting a reading of a CREATE
VIEW statement.

Three things are seeded and all three matter: a sealed version, an *open* one
being built, and a *superseded* sealed one. Retrieval must see exactly the first.
A test with only one version in the database would pass no matter what the view
said.

Skips unless CLEARSKIES_TEST_DATABASE_URL names a migrated database, the same
gate the spatial tests use. Everything is rolled back.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest

from app.assistant.retrieval import EMBEDDING_DIMENSIONS, active_version, search, to_pgvector

DATABASE_URL = os.environ.get("CLEARSKIES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set CLEARSKIES_TEST_DATABASE_URL to a migrated database to run the corpus tests",
)


def vector(lead: float) -> str:
    """A vector pointing mostly along one axis, so distances are predictable."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[0] = lead
    values[1] = 1.0 - abs(lead)
    return to_pgvector(values)


async def seed_version(
    conn: asyncpg.Connection,
    version: str,
    section: str,
    lead: float,
    sealed_at: datetime | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO statute_corpus_version (version, manifest_sha256, embedding_model)
        VALUES ($1, 'test', 'text-embedding-3-small')
        """,
        version,
    )
    await conn.execute(
        """
        INSERT INTO statute_document (
            corpus_version, document_id, authority, citation, jurisdiction,
            edition, source_url, retrieved_at, full_text, may_reason_from
        ) VALUES ($1, 'doc', 'Test Authority', '1 U.S.C. § 1', 'federal',
                  '2024', 'https://example.test', now(), 'full text', true)
        """,
        version,
    )
    await conn.execute(
        """
        INSERT INTO statute_chunk (
            corpus_version, document_id, section_label, ordinal, text, embedding
        ) VALUES ($1, 'doc', $2, 0, $3, $4::vector)
        """,
        version,
        section,
        f"text of {section}",
        vector(lead),
    )
    if sealed_at is not None:
        # An explicit timestamp rather than now(). now() is the *transaction*
        # timestamp, so seeding two versions in one transaction gives both the
        # same value and "newest" stops meaning anything. Production seals in
        # separate transactions and these are the values it would produce.
        await conn.execute(
            """
            UPDATE statute_corpus_version
               SET sealed_at = $2, content_sha256 = 'h',
                   document_count = 1, chunk_count = 1
             WHERE version = $1
            """,
            version,
            sealed_at,
        )


@pytest.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(DATABASE_URL)
    transaction = connection.transaction()
    await transaction.start()
    try:
        # An older sealed version, the current sealed one, and one still being
        # built. The older one is named so it sorts *after* the current one
        # alphabetically, so a view that fell back to the name rather than the
        # seal time would fail these tests rather than pass them by luck.
        await seed_version(
            connection, "zz-old-sealed", "9 U.S.C. § 99", 1.0, datetime(2099, 1, 1, tzinfo=UTC)
        )
        await seed_version(
            connection, "aa-current", "42 U.S.C. § 7412", 0.99, datetime(2099, 6, 1, tzinfo=UTC)
        )
        await seed_version(connection, "mm-open", "50 U.S.C. § 50", 1.0, None)
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


async def test_retrieval_sees_only_the_newest_sealed_version(
    conn: asyncpg.Connection,
) -> None:
    results = await search(conn, [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), limit=50)

    assert {p.corpus_version for p in results} == {"aa-current"}


async def test_a_superseded_version_is_unreachable(conn: asyncpg.Connection) -> None:
    """Its chunk is an exact match for the query vector and still must not come
    back: a draft cites the corpus that was current, not every corpus there
    has ever been."""
    results = await search(conn, [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), limit=50)

    assert "9 U.S.C. § 99" not in {p.section_label for p in results}


async def test_a_corpus_still_being_built_is_unreachable(
    conn: asyncpg.Connection,
) -> None:
    """Sealing is the publish step. An unsealed version is half a corpus, and
    half a corpus is the one thing worse than none."""
    results = await search(conn, [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), limit=50)

    assert "50 U.S.C. § 50" not in {p.section_label for p in results}


async def test_the_active_version_is_the_newest_sealed_one(
    conn: asyncpg.Connection,
) -> None:
    assert await active_version(conn) == "aa-current"


async def test_a_passage_carries_the_section_label_a_citation_needs(
    conn: asyncpg.Connection,
) -> None:
    results = await search(conn, [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1), limit=50)

    assert [p.section_label for p in results] == ["42 U.S.C. § 7412"]
    assert results[0].document_id == "doc"
    assert results[0].text


async def test_two_versions_sealed_at_the_same_instant_resolve_the_same_way_every_time(
    conn: asyncpg.Connection,
) -> None:
    """Migration 0019. sealed_at alone is not a total order.

    now() is the transaction timestamp, so anything sealing two versions in one
    transaction gives both the same value, and the view then returned whichever
    row the planner reached first. Postgres may break that tie differently
    between two runs, which would mean the corpus a draft is written against
    could change with no write in between: worse than reading the wrong corpus,
    because that at least is a bug somebody can find.
    """
    await seed_version(conn, "tie-a", "1 U.S.C. § 1", 1.0, datetime(2099, 9, 1, tzinfo=UTC))
    await seed_version(conn, "tie-b", "2 U.S.C. § 2", 1.0, datetime(2099, 9, 1, tzinfo=UTC))

    answers = {await active_version(conn) for _ in range(5)}

    assert answers == {"tie-b"}


async def test_a_sealed_corpus_refuses_a_new_chunk(conn: asyncpg.Connection) -> None:
    """The other half of "cannot grow at runtime": the API has a connection and
    provably cannot use it to add an authority."""
    with pytest.raises(asyncpg.PostgresError, match="sealed"):
        await conn.execute(
            """
            INSERT INTO statute_chunk (
                corpus_version, document_id, section_label, ordinal, text
            ) VALUES ('aa-current', 'doc', '42 U.S.C. § 9999', 0, 'invented')
            """
        )
