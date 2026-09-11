"""Command line entry point for the statute corpus.

    python -m corpus manifest            what Appendix B asks for
    python -m corpus check               the manifest against the paper
    python -m corpus build               fetch, parse and chunk, writing nothing
    python -m corpus ingest              build, then write a corpus version
    python -m corpus ingest --seal       and seal it, if it covers the manifest
    python -m corpus versions            what the database holds

`build` runs the whole pipeline without a database, which is what CI can do: it
proves the parsers still understand what the publishers serve, which is the part
most likely to break without anybody touching this repository.

Ingestion is a command rather than a notebook because Appendix B rule 4 makes
the corpus a versioned artifact. An artifact that only one person can rebuild is
one nobody can check.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

import asyncpg

from corpus import appendix, store
from corpus.fetch import Cache, build_client
from corpus.ingest import Build, version_label
from corpus.ingest import build as build_corpus
from corpus.manifest import MANIFEST, manifest_sha256

log = logging.getLogger("corpus")

# The corpus is built for one embedding model and statute_chunk.embedding has a
# fixed dimension. CS-302 generates the vectors; the name is recorded here so a
# mismatch is a visible property of the version rather than a silent drop in
# retrieval quality.
EMBEDDING_MODEL = "text-embedding-3-small"

DEFAULT_DATABASE_URL = "postgresql://clearskies:clearskies@localhost:5432/clearskies"


def _database_url(args: argparse.Namespace) -> str:
    return args.database_url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def cmd_manifest(args: argparse.Namespace) -> int:
    print(f"Appendix B manifest, sha256 {manifest_sha256()[:16]}\n")
    for authority in MANIFEST:
        flag = "" if authority.may_reason_from else "   [cite only, no reasoning]"
        print(f"  {authority.document_id:<32} {authority.citation}{flag}")
        print(f"  {'':<32} {authority.plan.url}")
    print(f"\n{len(MANIFEST)} authorities")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """The manifest against Appendix B, both directions."""
    try:
        rows = appendix.parse()
    except appendix.AppendixError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    paper = {(r.name, r.citation) for r in rows}
    code = {(a.appendix_name, a.citation) for a in MANIFEST}

    problems = []
    for name, citation in sorted(paper - code):
        problems.append(f"in the paper, not in the manifest: {name} ({citation})")
    for name, citation in sorted(code - paper):
        problems.append(f"in the manifest, not in the paper: {name} ({citation})")

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(
            "\nAppendix B.4 rule 4: adding an authority requires a manifest entry "
            "in the paper first.",
            file=sys.stderr,
        )
        return 1

    print(f"{len(rows)} authorities, and the manifest matches Appendix B exactly")
    for i, rule in enumerate(appendix.rules(), start=1):
        print(f"  rule {i}: {rule[:78]}")
    return 0


async def _build(args: argparse.Namespace) -> tuple[int, Build]:
    cache = None if args.no_cache else Cache()
    async with build_client() as client:
        result = await build_corpus(client, cache=cache, refresh=args.refresh)

    coverage = result.coverage
    print(f"\n{len(result.documents)} documents, {result.chunk_count} chunks")
    print(f"content sha256 {result.content_sha256()[:16]}")
    for document in result.documents:
        labels = len({c.section_label for c in document.chunks})
        print(
            f"  {document.document_id:<32} {len(document.chunks):>5} chunks "
            f"{labels:>5} citable units   {document.edition}"
        )
    if result.failures:
        print(f"\n{len(result.failures)} authorities could not be ingested:", file=sys.stderr)
        for document_id, reason in result.failures.items():
            print(f"  {document_id}: {reason}", file=sys.stderr)
    if not coverage.complete:
        print(
            f"\nincomplete: {len(coverage.missing)} of {len(MANIFEST)} "
            "Appendix B authorities are missing",
            file=sys.stderr,
        )
    return (0 if coverage.complete else 1), result


async def _ingest(args: argparse.Namespace) -> int:
    status, result = await _build(args)

    version = args.version or version_label(result, args.prefix)
    conn = await asyncpg.connect(_database_url(args))
    try:
        await store.write(conn, version, result, EMBEDDING_MODEL, notes=args.notes)
        print(f"\nwrote corpus version {version}")
        if args.seal:
            try:
                await store.seal(conn, version, result, force=args.force)
            except store.SealError as exc:
                print(f"\nnot sealed: {exc}", file=sys.stderr)
                return 1
            print(f"sealed corpus version {version}")
            return 0
        print("not sealed. Retrieval reads the newest sealed version only.")
    finally:
        await conn.close()
    return status


async def _versions(args: argparse.Namespace) -> int:
    conn = await asyncpg.connect(_database_url(args))
    try:
        rows = await store.summary(conn)
    finally:
        await conn.close()

    if not rows:
        print("no corpus versions. Run `python -m corpus ingest --seal`.")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    for row in rows:
        state = "sealed" if row["sealed_at"] else "open"
        print(f"  {row['version']}  {state}")
        print(
            f"      {row['documents_now']} documents, {row['chunks_now']} chunks, "
            f"{row['chunks_embedded']} embedded ({row['embedding_model']})"
        )
        if row["sealed_at"]:
            print(f"      sealed {row['sealed_at']}  content {row['content_sha256'][:16]}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m corpus",
        description="Build and version the Appendix B statute corpus.",
    )
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--database-url", default=None, help="overrides DATABASE_URL")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("manifest", help="print the Appendix B manifest")
    sub.add_parser("check", help="compare the manifest with docs/methodology.md")

    for name, help_text in (
        ("build", "fetch, parse and chunk without writing anything"),
        ("ingest", "build, then write a corpus version"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--no-cache", action="store_true", help="ignore the on-disk cache")
        p.add_argument("--refresh", action="store_true", help="refetch even when cached")
        if name == "ingest":
            p.add_argument("--version", default=None, help="override the version name")
            p.add_argument("--prefix", default="appendix-b", help="version name prefix")
            p.add_argument("--notes", default="", help="recorded on the version row")
            p.add_argument("--seal", action="store_true", help="seal once complete")
            p.add_argument(
                "--force",
                action="store_true",
                help="seal a corpus that does not cover the whole manifest",
            )

    versions = sub.add_parser("versions", help="what the database holds")
    versions.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s %(message)s")

    if args.command == "manifest":
        return cmd_manifest(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "build":
        status, _ = asyncio.run(_build(args))
        return status
    if args.command == "ingest":
        return asyncio.run(_ingest(args))
    return asyncio.run(_versions(args))


if __name__ == "__main__":
    sys.exit(main())
