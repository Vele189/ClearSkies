"""Appendix B, as something a program can execute.

`docs/methodology.md` Appendix B is the manifest of record. It is prose in a
table, which is the right form for the document it lives in and the wrong form
for an ingestion script, so this module restates it as data and
`tests/test_manifest.py` asserts the two agree row for row, in both directions.

That test is rule 4 made structural. The rule says adding an authority requires
a manifest entry in Appendix B first, and a rule like that decays into a
convention the moment the only thing enforcing it is everybody remembering. With
the test in place, a fetch plan added here and not to the paper fails CI, and so
does a row added to the paper that nothing ingests. The corpus cannot quietly
acquire an authority, and the paper cannot quietly promise one.

What is *not* here is anything about relevance or interpretation. The Relevance
column is carried verbatim so the comparison can be made, and is never shown to
the model: it is an editor's note about why an authority is in scope, and a
model reading "the basis for most air toxics arguments" as context would be
reading an instruction to make that argument.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

Jurisdiction = Literal["federal", "louisiana", "case_law"]


# ---- Fetch plans --------------------------------------------------------
#
# One class per authoritative publisher rather than one per authority, because
# the thing that varies between two US Code chapters is two numbers and the
# thing that varies between the US Code and the eCFR is everything.


@dataclass(frozen=True)
class USCodeUnit:
    """A chapter or subchapter of the United States Code, from govinfo.

    govinfo publishes the whole unit as one HTML document with the section
    boundaries marked in it, so a chapter is one request rather than one request
    per section plus a way to find out which sections exist. That matters beyond
    politeness to the GPO: a list of section numbers maintained by hand is a
    list that goes stale silently when Congress adds a section, and the corpus
    would then be missing an authority while reporting itself complete.

    `edition` is the US Code edition year, which is the amendment date Appendix
    B rule 1 asks for. It is pinned rather than derived from today, so
    re-running ingestion reproduces the same corpus.
    """

    title: int
    unit: str
    edition: int = 2024

    @property
    def package(self) -> str:
        return f"USCODE-{self.edition}-title{self.title}"

    @property
    def url(self) -> str:
        return (
            f"https://www.govinfo.gov/content/pkg/{self.package}"
            f"/html/{self.package}-{self.unit}.htm"
        )

    @property
    def edition_label(self) -> str:
        return f"United States Code, {self.edition} Edition"


@dataclass(frozen=True)
class ECFRPart:
    """One part of the Code of Federal Regulations, from the eCFR versioner API.

    `as_of` pins the date the regulation is read as of. The eCFR serves the text
    in force on a given day and that is the whole reason to use it rather than
    the annual print edition, but a corpus built "as of today" is a corpus that
    is a different corpus tomorrow, which defeats versioning.
    """

    title: int
    part: int
    as_of: str

    @property
    def url(self) -> str:
        return (
            f"https://www.ecfr.gov/api/versioner/v1/full/{self.as_of}"
            f"/title-{self.title}.xml?part={self.part}"
        )

    @property
    def edition_label(self) -> str:
        return f"e-CFR as of {self.as_of}"


@dataclass(frozen=True)
class CaselawOpinion:
    """One opinion from the Caselaw Access Project static archive.

    Identified by reporter, volume and the archive's own file name rather than
    by case name. A name match would be a search, and a search that silently
    returns the wrong opinion is the failure the verifier exists to prevent
    happening upstream of the verifier.
    """

    reporter: str
    volume: int
    file_name: str
    decided: str

    @property
    def url(self) -> str:
        return f"https://static.case.law/{self.reporter}/{self.volume}/cases/{self.file_name}.json"

    @property
    def edition_label(self) -> str:
        return f"decided {self.decided}"


@dataclass(frozen=True)
class LouisianaWeb:
    """A Louisiana authority, from the state's own publisher.

    The state publishes its constitution and revised statutes on legis.la.gov
    and the Administrative Code on the Division of Administration's site. Both
    are the authoritative publisher, and neither offers a bulk or versioned API,
    so `url` is a document URL and `edition_label` records what the page states
    about currency.

    These are the authorities this project has not been able to ingest from a
    machine that cannot resolve those hosts. See `docs/corpus.md`; the fetcher
    reports the failure by name and the corpus refuses to seal without them,
    which is the intended behaviour rather than a gap to work around.
    """

    url_: str
    edition: str

    @property
    def url(self) -> str:
        return self.url_

    @property
    def edition_label(self) -> str:
        return self.edition


FetchPlan = USCodeUnit | ECFRPart | CaselawOpinion | LouisianaWeb


# ---- Authorities --------------------------------------------------------


@dataclass(frozen=True)
class Authority:
    """One row of Appendix B, plus how to go and get it.

    `document_id` is the stable key a citation resolves against. It never
    changes for a given authority, across corpus versions, because a draft
    written last year cites by it.

    `sections` narrows a fetched unit to the sections this row is actually
    about. The Clean Air Act row takes the whole of chapter 85 and leaves this
    empty; the hazardous air pollutants row underneath it takes section 7412 out
    of the same chapter. One fetch, four rows, and the chapter is downloaded
    once because the fetcher caches by URL.
    """

    document_id: str
    appendix_name: str
    citation: str
    relevance: str
    jurisdiction: Jurisdiction
    plan: FetchPlan
    sections: tuple[str, ...] = ()
    may_reason_from: bool = True
    parent: str | None = None

    @property
    def is_subentry(self) -> bool:
        """True for the rows Appendix B writes with a leading em dash."""
        return self.appendix_name.startswith("—")


CLEAN_AIR_ACT = USCodeUnit(title=42, unit="chap85")
CLEAN_WATER_ACT = USCodeUnit(title=33, unit="chap26")
RCRA = USCodeUnit(title=42, unit="chap82")
EPCRA = USCodeUnit(title=42, unit="chap116")
TITLE_VI = USCodeUnit(title=42, unit="chap21-subchapV")

# The date 40 C.F.R. Part 7 is read as of. Pinned so the build is reproducible;
# bumping it is a new corpus version, which is the point.
ECFR_AS_OF = "2025-01-01"


# Appendix B.1 — federal statutes.
FEDERAL: tuple[Authority, ...] = (
    Authority(
        document_id="usc-42-chap85",
        appendix_name="Clean Air Act",
        citation="42 U.S.C. §§ 7401–7671q",
        relevance="Framework statute",
        jurisdiction="federal",
        plan=CLEAN_AIR_ACT,
    ),
    Authority(
        document_id="usc-42-7412",
        appendix_name="— Hazardous air pollutants",
        citation="42 U.S.C. § 7412",
        relevance="NESHAP standards; the basis for most air toxics arguments",
        jurisdiction="federal",
        plan=CLEAN_AIR_ACT,
        sections=("7412",),
        parent="usc-42-chap85",
    ),
    Authority(
        document_id="usc-42-7410",
        appendix_name="— State implementation plans",
        citation="42 U.S.C. § 7410",
        relevance="State obligations and adequacy",
        jurisdiction="federal",
        plan=CLEAN_AIR_ACT,
        sections=("7410",),
        parent="usc-42-chap85",
    ),
    Authority(
        document_id="usc-42-7470-7492",
        appendix_name="— Prevention of significant deterioration",
        citation="42 U.S.C. §§ 7470–7492",
        relevance="New and modified major source review",
        jurisdiction="federal",
        plan=CLEAN_AIR_ACT,
        sections=tuple(str(n) for n in range(7470, 7493)),
        parent="usc-42-chap85",
    ),
    Authority(
        document_id="usc-42-7661-7661f",
        appendix_name="— Operating permits",
        citation="42 U.S.C. §§ 7661–7661f",
        relevance="Title V permits and the public comment right they carry",
        jurisdiction="federal",
        plan=CLEAN_AIR_ACT,
        sections=("7661", "7661a", "7661b", "7661c", "7661d", "7661e", "7661f"),
        parent="usc-42-chap85",
    ),
    Authority(
        document_id="usc-33-chap26",
        appendix_name="Clean Water Act",
        citation="33 U.S.C. §§ 1251 et seq.; § 1342",
        relevance="Discharge permitting",
        jurisdiction="federal",
        plan=CLEAN_WATER_ACT,
    ),
    Authority(
        document_id="usc-42-chap82",
        appendix_name="Resource Conservation and Recovery Act",
        citation="42 U.S.C. §§ 6901 et seq.",
        relevance="Hazardous waste handling",
        jurisdiction="federal",
        plan=RCRA,
    ),
    Authority(
        document_id="usc-42-chap116",
        appendix_name="Emergency Planning and Community Right-to-Know Act",
        citation="42 U.S.C. §§ 11001 et seq.; § 11023",
        relevance="The reporting requirement that produces TRI",
        jurisdiction="federal",
        plan=EPCRA,
    ),
    Authority(
        document_id="usc-42-2000d",
        appendix_name="Civil Rights Act, Title VI",
        citation="42 U.S.C. §§ 2000d–2000d-7",
        relevance="Discrimination by recipients of federal funds",
        jurisdiction="federal",
        plan=TITLE_VI,
    ),
    Authority(
        document_id="cfr-40-part7",
        appendix_name="EPA Title VI implementing regulations",
        citation="40 C.F.R. Part 7",
        relevance="Disparate-impact standard and the administrative complaint process",
        jurisdiction="federal",
        plan=ECFRPart(title=40, part=7, as_of=ECFR_AS_OF),
    ),
)


# Appendix B.2 — Louisiana authorities.
LOUISIANA: tuple[Authority, ...] = (
    Authority(
        document_id="la-const-art9-sec1",
        appendix_name="Louisiana Constitution, natural resources",
        citation="La. Const. art. IX, § 1",
        relevance="Public trust duty over the environment",
        jurisdiction="louisiana",
        plan=LouisianaWeb(
            url_="https://legis.la.gov/legis/Law.aspx?d=206130",
            edition="Constitution of 1974, as amended",
        ),
    ),
    Authority(
        document_id="la-rs-30-2001",
        appendix_name="Louisiana Environmental Quality Act",
        citation="La. R.S. 30:2001 et seq.",
        relevance="State framework statute",
        jurisdiction="louisiana",
        plan=LouisianaWeb(
            url_="https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent",
            edition="Revised Statutes, current through the 2025 Regular Session",
        ),
    ),
    Authority(
        document_id="la-rs-30-2051",
        appendix_name="Louisiana Air Control Law",
        citation="La. R.S. 30:2051 et seq.",
        relevance="State air permitting authority",
        jurisdiction="louisiana",
        plan=LouisianaWeb(
            url_="https://legis.la.gov/legis/Laws_Toc.aspx?folder=75&level=Parent",
            edition="Revised Statutes, current through the 2025 Regular Session",
        ),
    ),
    Authority(
        document_id="lac-33-iii",
        appendix_name="Louisiana Administrative Code, Title 33, Part III",
        citation="LAC 33:III",
        relevance="Air quality regulations",
        jurisdiction="louisiana",
        plan=LouisianaWeb(
            url_="https://www.doa.la.gov/media/nlanblmd/33v03.pdf",
            edition="LAC Title 33 Part III, as published by the Office of the State Register",
        ),
    ),
)


# Appendix B.3 — bounded case law.
#
# may_reason_from is False for both, which is not a style preference. Appendix
# B.3 permits citation and forbids reasoning to a legal conclusion, and CS-305
# checks the flag rather than trusting the prompt to have carried the
# distinction.
CASE_LAW: tuple[Authority, ...] = (
    Authority(
        document_id="case-save-ourselves-1984",
        appendix_name=("*Save Ourselves, Inc. v. Louisiana Environmental Control Commission*"),
        citation="452 So. 2d 1152 (La. 1984)",
        relevance=(
            "Establishes the state agency's affirmative public trust duty and the "
            "balancing questions a permitting decision must address"
        ),
        jurisdiction="case_law",
        plan=CaselawOpinion(reporter="so2d", volume=452, file_name="1152-01", decided="1984-05-14"),
        may_reason_from=False,
    ),
    Authority(
        document_id="case-alexander-v-sandoval-2001",
        appendix_name="*Alexander v. Sandoval*",
        citation="532 U.S. 275 (2001)",
        relevance=(
            "Holds there is no private right of action to enforce disparate-impact "
            "regulations under Title VI"
        ),
        jurisdiction="case_law",
        plan=CaselawOpinion(reporter="us", volume=532, file_name="0275-01", decided="2001-04-24"),
        may_reason_from=False,
    ),
)


MANIFEST: tuple[Authority, ...] = FEDERAL + LOUISIANA + CASE_LAW


def by_id(document_id: str) -> Authority:
    for authority in MANIFEST:
        if authority.document_id == document_id:
            return authority
    raise KeyError(f"{document_id!r} is not in the Appendix B manifest")


def manifest_sha256(authorities: tuple[Authority, ...] = MANIFEST) -> str:
    """A hash of what the corpus is supposed to contain.

    Stamped on the corpus version, so "was this corpus built from the manifest
    the repository now holds" is a string comparison rather than an argument.
    The fetch plan is included: the same authority pulled from a different
    edition is a different corpus, and a hash that ignored the edition would
    report the two as identical.
    """
    payload = [
        {
            "document_id": a.document_id,
            "appendix_name": a.appendix_name,
            "citation": a.citation,
            "jurisdiction": a.jurisdiction,
            "sections": list(a.sections),
            "may_reason_from": a.may_reason_from,
            "url": a.plan.url,
            "edition": a.plan.edition_label,
        }
        for a in sorted(authorities, key=lambda a: a.document_id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Coverage:
    """What a build got, against what the manifest asked for."""

    present: tuple[str, ...] = field(default_factory=tuple)
    missing: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        return not self.missing
