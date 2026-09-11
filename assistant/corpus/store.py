"""Write a build into the database, and seal it.

The schema does the enforcing. Migration 0018 refuses any write to a sealed
version, so the sequence here is: open a version, fill it, check it, seal it.
After the seal this module has no way to change what it wrote, and neither does
anything else with a connection string.

Sealing is the only interesting decision. It requires the build to cover every
authority in Appendix B, and it records the content hash, the document count and
the chunk count in the same statement that sets `sealed_at`, because a seal
without the numbers it sealed is not an audit trail. A version that fails the
completeness check stays open, which makes it invisible to
`statute_corpus_active` and therefore invisible to retrieval and to the
verifier. An incomplete corpus is not published rather than published with a
caveat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from corpus.ingest import Build
from corpus.manifest import MANIFEST, manifest_sha256

log = logging.getLogger(__name__)


class SealError(RuntimeError):
    """The corpus is not in a state that may be sealed."""


@dataclass(frozen=True)
class VersionRow:
    version: str
    manifest_sha256: str
    embedding_model: str
    sealed_at: Any
    content_sha256: str | None
    document_count: int | None
    chunk_count: int | None

    @property
    def sealed(self) -> bool:
        return self.sealed_at is not None


INSERT_VERSION = """
INSERT INTO statute_corpus_version (version, manifest_sha256, embedding_model, notes)
VALUES ($1, $2, $3, $4)
ON CONFLICT (version) DO NOTHING
"""

INSERT_DOCUMENT = """
INSERT INTO statute_document (
    corpus_version, document_id, authority, citation, jurisdiction,
    edition, source_url, retrieved_at, full_text, may_reason_from
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""

INSERT_CHUNK = """
INSERT INTO statute_chunk (corpus_version, document_id, section_label, ordinal, text)
VALUES ($1, $2, $3, $4, $5)
"""

SEAL = """
UPDATE statute_corpus_version
   SET sealed_at = now(),
       content_sha256 = $2,
       document_count = $3,
       chunk_count = $4
 WHERE version = $1
"""


async def version_row(conn: Any, version: str) -> VersionRow | None:
    row = await conn.fetchrow(
        """
        SELECT version, manifest_sha256, embedding_model, sealed_at,
               content_sha256, document_count, chunk_count
          FROM statute_corpus_version WHERE version = $1
        """,
        version,
    )
    return None if row is None else VersionRow(**dict(row))


async def write(
    conn: Any,
    version: str,
    build: Build,
    embedding_model: str,
    notes: str = "",
) -> None:
    """Create the version if it is new and fill it with the build.

    One transaction. A half-written corpus version that a later run appends to
    is a corpus whose content hash depends on how many times ingestion was
    interrupted.
    """
    existing = await version_row(conn, version)
    if existing is not None and existing.sealed:
        raise SealError(
            f"corpus version {version} is already sealed. "
            "A changed manifest produces a different version; an unchanged one "
            "is already built."
        )

    async with conn.transaction():
        await conn.execute(INSERT_VERSION, version, manifest_sha256(), embedding_model, notes)
        # Clearing first makes the write idempotent for an open version, so a
        # run interrupted after ten of twelve authorities can simply be redone.
        await conn.execute("DELETE FROM statute_chunk WHERE corpus_version = $1", version)
        await conn.execute("DELETE FROM statute_document WHERE corpus_version = $1", version)

        for document in build.documents:
            await conn.execute(
                INSERT_DOCUMENT,
                version,
                document.document_id,
                document.authority,
                document.citation,
                document.jurisdiction,
                document.edition,
                document.source_url,
                document.retrieved_at,
                document.full_text,
                document.may_reason_from,
            )
            await conn.executemany(
                INSERT_CHUNK,
                [
                    (version, document.document_id, c.section_label, c.ordinal, c.text)
                    for c in document.chunks
                ],
            )

    log.info(
        "wrote corpus version %s: %d documents, %d chunks",
        version,
        len(build.documents),
        build.chunk_count,
    )


async def seal(conn: Any, version: str, build: Build, force: bool = False) -> None:
    """Close a version to further writes, once it covers the whole manifest."""
    row = await version_row(conn, version)
    if row is None:
        raise SealError(f"no corpus version {version}")
    if row.sealed:
        raise SealError(f"corpus version {version} is already sealed")

    coverage = build.coverage
    if not coverage.complete and not force:
        missing = ", ".join(coverage.missing)
        raise SealError(
            f"corpus version {version} is missing {len(coverage.missing)} of "
            f"{len(MANIFEST)} Appendix B authorities: {missing}. "
            "Sealing it would publish a corpus the methodology does not describe. "
            "Fix the fetch, or pass --force to seal a deliberately partial corpus "
            "and accept that drafts will cite only what is in it."
        )

    await conn.execute(
        SEAL, version, build.content_sha256(), len(build.documents), build.chunk_count
    )
    log.info("sealed corpus version %s", version)


async def summary(conn: Any) -> list[dict[str, Any]]:
    """Every corpus version, newest first, with what it holds."""
    rows = await conn.fetch(
        """
        SELECT v.version,
               v.manifest_sha256,
               v.embedding_model,
               v.built_at,
               v.sealed_at,
               v.content_sha256,
               v.document_count,
               v.chunk_count,
               (SELECT count(*) FROM statute_document d
                 WHERE d.corpus_version = v.version) AS documents_now,
               (SELECT count(*) FROM statute_chunk c
                 WHERE c.corpus_version = v.version) AS chunks_now,
               (SELECT count(*) FROM statute_chunk c
                 WHERE c.corpus_version = v.version AND c.embedding IS NOT NULL)
                 AS chunks_embedded
          FROM statute_corpus_version v
         ORDER BY v.built_at DESC
        """
    )
    return [dict(row) for row in rows]
