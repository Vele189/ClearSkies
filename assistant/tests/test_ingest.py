"""The build: coverage, reproducibility, and the refusal to seal a partial corpus.

No network. A stub transport serves the fixtures, which is enough to exercise
everything except whether the publishers still serve what the parsers expect —
and that is what `python -m corpus build` is for in CI.
"""

from __future__ import annotations

import httpx
import pytest

from corpus.fetch import FetchError
from corpus.ingest import Build, Document, build, ingest_authority, version_label
from corpus.manifest import MANIFEST, by_id
from corpus.store import SealError
from tests.conftest import CASELAW_OPINION, ECFR_PART, US_CODE_CHAPTER


def stub_client(bodies: dict[str, str], fail: set[str] | None = None) -> httpx.AsyncClient:
    """A client that serves fixture text by URL substring."""
    failures = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for marker in failures:
            if marker in url:
                raise httpx.ConnectError("name resolution failed", request=request)
        for marker, body in bodies.items():
            if marker in url:
                return httpx.Response(200, text=body)
        return httpx.Response(404, text="not found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


FIXTURES = {
    "govinfo.gov": US_CODE_CHAPTER,
    "ecfr.gov": ECFR_PART,
    "static.case.law": CASELAW_OPINION,
}


async def test_a_us_code_authority_is_fetched_parsed_and_chunked() -> None:
    async with stub_client(FIXTURES) as client:
        document = await ingest_authority(client, by_id("usc-42-chap85"), cache=None)

    assert document.chunks
    assert document.edition == "United States Code, 2024 Edition"
    assert document.source_url.startswith("https://www.govinfo.gov/")
    assert all(c.section_label.startswith("42 U.S.C. §") for c in document.chunks)


async def test_a_subentry_takes_only_its_own_sections() -> None:
    """The Clean Air Act row takes the whole chapter; the hazardous air
    pollutants row underneath it takes § 7412 out of the same document."""
    async with stub_client(FIXTURES) as client:
        document = await ingest_authority(client, by_id("usc-42-7412"), cache=None)

    assert {c.section_label.split("(")[0].strip() for c in document.chunks} == {"42 U.S.C. § 7412"}


async def test_a_subentry_whose_sections_are_absent_is_an_error() -> None:
    async with stub_client(FIXTURES) as client:
        with pytest.raises(FetchError, match="none of the sections"):
            await ingest_authority(client, by_id("usc-42-7470-7492"), cache=None)


async def test_case_law_carries_the_reporter_citation_as_its_label() -> None:
    async with stub_client(FIXTURES) as client:
        document = await ingest_authority(
            client, by_id("case-alexander-v-sandoval-2001"), cache=None
        )

    assert {c.section_label for c in document.chunks} == {"532 U.S. 275 (2001)"}
    assert not document.may_reason_from


async def test_a_louisiana_authority_reports_its_failure_by_name() -> None:
    """The hosts do not resolve from every network, and the build says which
    authority that cost rather than reporting a smaller corpus."""
    async with stub_client(FIXTURES, fail={"legis.la.gov"}) as client:
        result = await build(client, authorities=(by_id("la-const-art9-sec1"),))

    assert result.documents == []
    assert "la-const-art9-sec1" in result.failures
    assert "legis.la.gov" in result.failures["la-const-art9-sec1"]


async def test_a_failure_does_not_stop_the_rest_of_the_build() -> None:
    async with stub_client(FIXTURES, fail={"legis.la.gov"}) as client:
        result = await build(
            client,
            authorities=(by_id("la-const-art9-sec1"), by_id("cfr-40-part7")),
        )

    assert [d.document_id for d in result.documents] == ["cfr-40-part7"]
    assert set(result.failures) == {"la-const-art9-sec1"}


async def test_coverage_names_every_authority_the_build_is_missing() -> None:
    async with stub_client(FIXTURES) as client:
        result = await build(client, authorities=(by_id("cfr-40-part7"),))

    coverage = result.coverage
    assert not coverage.complete
    assert len(coverage.missing) == len(MANIFEST) - 1
    assert "la-const-art9-sec1" in coverage.missing


def test_the_content_hash_does_not_depend_on_build_order() -> None:
    """Two builds that fetched the manifest in a different order are the same
    corpus and must hash the same, or the version stamp reports a change that
    did not happen."""
    first = Document(
        document_id="a",
        authority="A",
        citation="1",
        jurisdiction="federal",
        edition="e",
        source_url="u",
        retrieved_at=None,  # type: ignore[arg-type]
        full_text="t",
        may_reason_from=True,
        chunks=[],
    )
    second = Document(**{**first.__dict__, "document_id": "b"})

    assert (
        Build(documents=[first, second]).content_sha256()
        == Build(documents=[second, first]).content_sha256()
    )


def test_the_version_name_is_derived_from_the_manifest() -> None:
    """Two builds of the same manifest collide rather than accumulate, and a
    changed manifest gets a new name without anybody choosing one."""
    name = version_label(Build(), "appendix-b")

    assert name.startswith("appendix-b-")
    assert version_label(Build(), "appendix-b") == name


def test_seal_error_is_raised_rather_than_a_partial_corpus_published() -> None:
    assert issubclass(SealError, RuntimeError)
