"""Fixtures shaped like what the publishers actually serve.

Small by design, and hand-written rather than trimmed from a real download, so
that every structural feature in them is there because a test needs it. The one
thing they copy exactly from the real documents is the markup: the field
comments and element classes govinfo emits, the DIV8 and P elements the eCFR
versioner emits, and the casebody shape the Caselaw Access Project emits. A
fixture that tidied those up would pass while the parser broke.

Nothing here reaches the network. The tests that do are marked `live`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from corpus.fetch import Fetched


def make_fetched(body: str, url: str = "https://example.test/doc") -> Fetched:
    raw = body.encode("utf-8")
    return Fetched(
        url=url,
        body=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        retrieved_at=datetime(2026, 9, 11, tzinfo=UTC),
        from_cache=False,
    )


def us_code_section(head: str, statute: str, notes: str = "") -> str:
    """One section, in the field-delimited shape govinfo serves."""
    parts = [
        "<!-- field-start:head -->",
        f'<h3 class="section-head">{head}</h3>',
        "<!-- field-end:head -->",
        "<!-- field-start:statute -->",
        statute,
        "<!-- field-end:statute -->",
        "<!-- field-start:sourcecredit -->",
        '<p class="source-credit">(July 14, 1955, ch. 360, 69 Stat. 322.)</p>',
        "<!-- field-end:sourcecredit -->",
    ]
    if notes:
        parts += [
            "<!-- field-start:notes -->",
            f'<p class="note-body">{notes}</p>',
            "<!-- field-end:notes -->",
        ]
    return "\n".join(parts)


# A chapter with three sections. The second carries the nesting that the depth
# rules exist for; the third is repealed and has no statute field at all.
US_CODE_CHAPTER = (
    "<html><body>"
    + "\n".join(
        [
            us_code_section(
                "&sect;7401. Congressional findings and declaration of purpose",
                "\n".join(
                    [
                        '<h4 class="subsection-head">(a) Findings</h4>',
                        '<p class="statutory-body">The Congress finds&mdash;</p>',
                        '<p class="statutory-body-1em">(1) that air pollution crosses '
                        "boundary lines of local jurisdictions;</p>",
                        '<h4 class="subsection-head">(b) Declaration</h4>',
                        '<p class="statutory-body">The purposes of this subchapter are '
                        "to protect the public health.</p>",
                    ]
                ),
                notes="Amendment notes that are not the statute.",
            ),
            us_code_section(
                "&sect;7412. Hazardous air pollutants",
                "\n".join(
                    [
                        '<h4 class="subsection-head">(c) Source category</h4>',
                        '<h5 class="paragraph-head">(9) Deletions</h5>',
                        '<p class="statutory-body-1em">(B) The Administrator may delete '
                        "a source category.</p>",
                        # The trap: a clause (i) nested under (B), written as an
                        # ordinary indented body paragraph. Read by style it looks
                        # like it continues subsection (c), which would label it
                        # 7412(i) — a real subsection about something else.
                        '<p class="statutory-body-2em">(i) In the case of pollutants '
                        "emitted by sources in the category.</p>",
                        '<p class="statutory-body-2em">(ii) The Administrator shall '
                        "publish the finding.</p>",
                        '<h4 class="subsection-head">(i) Schedule for compliance</h4>',
                        '<p class="statutory-body">This subsection governs timing.</p>",',
                    ]
                ),
            ),
            us_code_section("&sect;7413. Repealed", ""),
        ]
    )
    + "</body></html>"
)

# The repealed section above still needs its statute field removed entirely.
US_CODE_CHAPTER = US_CODE_CHAPTER.replace(
    "<!-- field-start:statute -->\n\n<!-- field-end:statute -->", ""
)


US_CODE_DASHED = (
    "<html><body>"
    + us_code_section(
        # An EN DASH, exactly as govinfo writes it.
        "&sect;2000d–1. Federal authority and financial assistance",
        '<p class="statutory-body">Each Federal department shall issue rules.</p>',
    )
    + "</body></html>"
)


ECFR_PART = """<?xml version="1.0"?>
<DIV5 N="7" TYPE="PART">
<HEAD>PART 7&#x2014;NONDISCRIMINATION</HEAD>
<DIV8 N="7.10" TYPE="SECTION">
<HEAD>&#xA7; 7.10 Purpose of this part.</HEAD>
<P>This part implements Title VI of the Civil Rights Act of 1964.</P>
</DIV8>
<DIV8 N="7.35" TYPE="SECTION">
<HEAD>&#xA7; 7.35 Specific prohibitions.</HEAD>
<P>(a) As to any program receiving EPA assistance, a recipient shall not:</P>
<P>(1) Deny a person any service, aid or other benefit of the program;</P>
<P>(2) Provide a person any service that is different from that provided to others;</P>
<P>(b) A recipient shall not use criteria or methods of administering its program
which have the effect of subjecting individuals to discrimination because of
their race, color, national origin, or sex.</P>
</DIV8>
</DIV5>
"""


CASELAW_OPINION = json.dumps(
    {
        "id": 9301210,
        "name": "James ALEXANDER, Director, Alabama Department of Public Safety, "
        "et al. v. Martha SANDOVAL",
        "name_abbreviation": "Alexander v. Sandoval",
        "decision_date": "2001-04-24",
        "casebody": {
            "headnotes": "A publisher's summary, which is not the court speaking.",
            "opinions": [
                {
                    "type": "majority",
                    "author": "Justice Scalia",
                    "text": "Justice Scalia delivered the opinion of the Court. "
                    "This case presents the question whether private individuals "
                    "may sue to enforce disparate-impact regulations promulgated "
                    "under Title VI of the Civil Rights Act of 1964. We hold that "
                    "there is no private right of action to enforce them.",
                }
            ],
        },
    }
)


@pytest.fixture
def us_code_doc() -> Fetched:
    return make_fetched(US_CODE_CHAPTER, "https://example.test/uscode-chapter.htm")


@pytest.fixture
def us_code_dashed_doc() -> Fetched:
    return make_fetched(US_CODE_DASHED, "https://example.test/uscode-titlevi.htm")


@pytest.fixture
def ecfr_doc() -> Fetched:
    return make_fetched(ECFR_PART, "https://example.test/title-40.xml?part=7")


@pytest.fixture
def caselaw_doc() -> Fetched:
    return make_fetched(CASELAW_OPINION, "https://example.test/0275-01.json")
