"""Build a corpus version from the manifest.

The whole of CS-301 in one pass: read Appendix B, fetch each authority from its
publisher, split it into citable sections, chunk those without crossing a
section boundary, and write the result as a new corpus version.

Two properties are worth stating because they are what make this a build rather
than a script somebody ran once.

It is repeatable. Every input is pinned: the US Code edition year, the eCFR
as-of date, the reporter volume and file name of each opinion. Running it twice
against the same manifest produces the same documents, the same chunk
boundaries, and therefore the same content hash. `--refresh` is the only way to
go back to the network for something already cached, and it exists for checking
whether an upstream document has changed, not for normal use.

It refuses to seal an incomplete corpus. If an authority in Appendix B could not
be fetched, the version stays open and unusable rather than becoming a corpus
that is quietly missing the Louisiana public trust provision. A drafting
assistant that cannot cite state law is not a slightly worse drafting assistant
for a Louisiana pilot; it is one that would write the wrong document.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from corpus import parse
from corpus.chunking import Chunk, chunk_section
from corpus.fetch import Cache, FetchError, fetch
from corpus.manifest import (
    MANIFEST,
    Authority,
    CaselawOpinion,
    Coverage,
    ECFRPart,
    LouisianaWeb,
    USCodeUnit,
    manifest_sha256,
)

log = logging.getLogger(__name__)


@dataclass
class Document:
    """One authority, ingested: the row and the chunks under it."""

    document_id: str
    authority: str
    citation: str
    jurisdiction: str
    edition: str
    source_url: str
    retrieved_at: datetime
    full_text: str
    may_reason_from: bool
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class Build:
    """The result of one ingestion pass."""

    documents: list[Document] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def coverage(self) -> Coverage:
        present = tuple(d.document_id for d in self.documents)
        missing = tuple(a.document_id for a in MANIFEST if a.document_id not in set(present))
        return Coverage(present=present, missing=missing)

    @property
    def chunk_count(self) -> int:
        return sum(len(d.chunks) for d in self.documents)

    def content_sha256(self) -> str:
        """A hash over every chunk in the build, order-independent by construction.

        Sorted by (document, label, ordinal) rather than by insertion, so two
        builds that fetched the manifest in a different order still hash the
        same. What it covers is the text the model can be shown, which is what a
        reader of a draft would want to know had not changed underneath them.
        """
        digest = hashlib.sha256()
        rows = sorted(
            (d.document_id, c.section_label, c.ordinal, c.text)
            for d in self.documents
            for c in d.chunks
        )
        for document_id, label, ordinal, text in rows:
            digest.update(f"{document_id}\x1f{label}\x1f{ordinal}\x1f".encode())
            digest.update(text.encode("utf-8"))
            digest.update(b"\x1e")
        return digest.hexdigest()


# ---- Citation labels ----------------------------------------------------


def _us_code_citation(title: int, number: str) -> str:
    return f"{title} U.S.C. § {number}"


def _cfr_citation(title: int, number: str) -> str:
    return f"{title} C.F.R. § {number}"


# ---- One authority at a time --------------------------------------------


async def ingest_authority(
    client: httpx.AsyncClient,
    authority: Authority,
    cache: Cache | None,
    refresh: bool = False,
) -> Document:
    """Fetch, parse and chunk one row of Appendix B."""
    plan = authority.plan
    fetched = await fetch(client, plan.url, cache=cache, refresh=refresh)

    if isinstance(plan, USCodeUnit):
        sections = parse.us_code(fetched)
        if authority.sections:
            wanted = set(authority.sections)
            sections = tuple(s for s in sections if s.number in wanted)
            if not sections:
                raise FetchError(
                    f"{authority.document_id}: none of the sections "
                    f"{sorted(wanted)} are in {plan.url}"
                )
        title = plan.title

        def cite(section: parse.Section) -> str:
            return _us_code_citation(title, section.number)
    elif isinstance(plan, ECFRPart):
        sections = parse.ecfr(fetched)
        title = plan.title

        def cite(section: parse.Section) -> str:
            return _cfr_citation(title, section.number)
    elif isinstance(plan, CaselawOpinion):
        sections = parse.caselaw(fetched)
        citation = authority.citation

        def cite(section: parse.Section) -> str:
            return citation
    elif isinstance(plan, LouisianaWeb):
        # No parser. The Louisiana publishers serve a session-stateful ASP.NET
        # application and a PDF, neither of which this project has been able to
        # reach, so writing a parser against a document nobody here has seen
        # would be writing fiction. docs/corpus.md records what is needed.
        raise FetchError(
            f"{authority.document_id}: no parser for a Louisiana source document. "
            "See docs/corpus.md section 4."
        )
    else:  # pragma: no cover - the union is closed
        raise FetchError(f"{authority.document_id}: unknown fetch plan")

    chunks: list[Chunk] = []
    texts: list[str] = []
    for section in sections:
        base = cite(section)
        texts.append(f"{base}. {section.heading}\n\n{section.text}".strip())
        chunks.extend(chunk_section(section, base))

    if not chunks:
        raise FetchError(f"{authority.document_id}: produced no chunks")

    return Document(
        document_id=authority.document_id,
        authority=authority.appendix_name,
        citation=authority.citation,
        jurisdiction=authority.jurisdiction,
        edition=plan.edition_label,
        source_url=plan.url,
        retrieved_at=fetched.retrieved_at,
        full_text="\n\n".join(texts),
        may_reason_from=authority.may_reason_from,
        chunks=chunks,
    )


async def build(
    client: httpx.AsyncClient,
    authorities: tuple[Authority, ...] = MANIFEST,
    cache: Cache | None = None,
    refresh: bool = False,
) -> Build:
    """Ingest every authority, carrying failures rather than raising on the first.

    Sequential rather than concurrent. These are four public services and the
    whole job is a dozen requests; a burst of parallel multi-megabyte downloads
    would be rude and would save a minute that nobody is waiting for.
    """
    result = Build()
    for authority in authorities:
        try:
            document = await ingest_authority(client, authority, cache, refresh)
        except (FetchError, parse.ParseError) as exc:
            log.error("%s: %s", authority.document_id, exc)
            result.failures[authority.document_id] = str(exc)
            continue
        log.info(
            "%s: %d sections worth %d chunks",
            authority.document_id,
            len({c.section_label.split("(")[0] for c in document.chunks}),
            len(document.chunks),
        )
        result.documents.append(document)
    return result


def version_label(build_result: Build, prefix: str) -> str:
    """A version name that identifies what is in it.

    The manifest hash, short, rather than a date or a counter. Two builds of the
    same manifest are the same corpus and should collide rather than accumulate;
    a build of a changed manifest gets a different name without anybody choosing
    one, which is the failure mode versioning schemes usually have.
    """
    return f"{prefix}-{manifest_sha256()[:12]}"
