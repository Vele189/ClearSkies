"""The manifest against the paper, and the properties the corpus rules require.

The first test here is the load-bearing one. Appendix B.4 rule 4 says adding an
authority requires a manifest entry in the paper first, and the only thing that
can hold a rule like that in place is a check that fails when it is broken.
"""

from __future__ import annotations

import pytest

from corpus import appendix
from corpus.manifest import (
    CASE_LAW,
    FEDERAL,
    LOUISIANA,
    MANIFEST,
    Authority,
    USCodeUnit,
    by_id,
    manifest_sha256,
)


def test_the_manifest_and_appendix_b_hold_the_same_authorities() -> None:
    """Rule 4, enforced.

    Both directions matter and they fail for different reasons. An authority in
    the code and not in the paper is a corpus that grew without the methodology
    saying so. One in the paper and not in the code is a methodology promising
    an authority the assistant cannot cite, which is the quieter failure: every
    draft is simply a little worse and nothing reports it.
    """
    paper = {(row.name, row.citation) for row in appendix.parse()}
    code = {(a.appendix_name, a.citation) for a in MANIFEST}

    assert paper == code, (
        f"in the paper only: {sorted(paper - code)}\nin the manifest only: {sorted(code - paper)}"
    )


def test_every_appendix_row_is_in_the_section_the_paper_files_it_under() -> None:
    by_citation = {a.citation: a for a in MANIFEST}
    for row in appendix.parse():
        authority = by_citation[row.citation]
        assert authority.jurisdiction == row.jurisdiction, row.name


def test_the_paper_still_states_the_five_rules_the_code_implements() -> None:
    """A sixth rule would be a requirement nothing here has been built to meet."""
    assert len(appendix.rules()) == 5


def test_bounded_case_law_may_be_cited_but_not_reasoned_from() -> None:
    """Appendix B.3, carried as a column rather than as a sentence in a prompt.

    CS-305 reads this flag. A prompt can be talked out of a distinction; a
    boolean on the row cannot.
    """
    assert [a.may_reason_from for a in CASE_LAW] == [False, False]
    assert all(a.may_reason_from for a in FEDERAL + LOUISIANA)


def test_sandoval_is_in_the_corpus() -> None:
    """Named explicitly because of why it is there.

    Appendix B.3 keeps Sandoval so the assistant gets the procedural posture of
    a Title VI disparate-impact claim right: an administrative complaint to EPA,
    not a lawsuit. Dropping it would not fail any other test here, and the
    drafts would get quietly worse in exactly the way that matters most.
    """
    sandoval = by_id("case-alexander-v-sandoval-2001")
    assert sandoval.citation == "532 U.S. 275 (2001)"
    assert not sandoval.may_reason_from


def test_every_authority_has_a_distinct_document_id() -> None:
    ids = [a.document_id for a in MANIFEST]
    assert len(ids) == len(set(ids))


def test_every_authority_names_a_source_and_an_edition() -> None:
    """Rule 1: full text, an edition or amendment date, and where it came from."""
    for authority in MANIFEST:
        assert authority.plan.url.startswith("https://"), authority.document_id
        assert authority.plan.edition_label, authority.document_id


def test_subentries_point_at_a_parent_that_exists() -> None:
    for authority in MANIFEST:
        if authority.parent is None:
            continue
        assert by_id(authority.parent).document_id == authority.parent


def test_a_subentry_is_written_the_way_the_paper_writes_it() -> None:
    for authority in MANIFEST:
        if authority.parent is not None:
            assert authority.is_subentry, authority.document_id


def test_the_manifest_hash_changes_when_an_edition_changes() -> None:
    """The hash covers what was fetched, not only which authorities were named.

    Two corpora built from the same list of authorities against different
    editions of the US Code are different corpora, and a version stamp that
    called them the same would make the audit trail useless in precisely the
    case it exists for.
    """
    before = manifest_sha256()

    original = by_id("usc-42-chap85")
    moved = Authority(
        document_id=original.document_id,
        appendix_name=original.appendix_name,
        citation=original.citation,
        relevance=original.relevance,
        jurisdiction=original.jurisdiction,
        plan=USCodeUnit(title=42, unit="chap85", edition=2023),
    )
    changed = tuple(moved if a is original else a for a in MANIFEST)

    assert manifest_sha256(changed) != before


def test_the_manifest_hash_does_not_depend_on_ordering() -> None:
    assert manifest_sha256(tuple(reversed(MANIFEST))) == manifest_sha256(MANIFEST)


def test_by_id_rejects_an_unknown_authority() -> None:
    with pytest.raises(KeyError, match="not in the Appendix B manifest"):
        by_id("usc-42-9999")
