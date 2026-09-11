"""Read Appendix B out of the methodology paper.

The paper is the manifest of record and `manifest.py` is a restatement of it.
Something has to compare them or the restatement drifts, and comparing them
means parsing three Markdown tables out of a document written for people.

Deliberately strict. Every failure mode here is "the appendix is not shaped the
way this parser expects", and every one of those is either a change to the
appendix that ought to be noticed or a typo in it. Returning a short list and
letting the comparison fail with "the manifest has an authority the appendix
does not" would be a much worse error message than "section B.2 is missing".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

METHODOLOGY = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"

# The three tables, by the heading that introduces each.
SECTIONS = {
    "federal": "### B.1 Federal statutes",
    "louisiana": "### B.2 Louisiana authorities",
    "case_law": "### B.3 Bounded case law",
}

APPENDIX_B = "## Appendix B — Statute corpus manifest"

# A table row: | cell | cell | cell |. Separator rows are dropped by the caller.
ROW = re.compile(r"^\|(?P<body>.+)\|\s*$")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|\s*$")


class AppendixError(RuntimeError):
    """Appendix B is not shaped the way the manifest comparison needs."""


@dataclass(frozen=True)
class AppendixRow:
    """One row of one Appendix B table, verbatim.

    Three columns in every table. B.1 and B.2 head them Authority, Citation and
    Relevance; B.3 heads them Case, Citation and "Why it is here". The headings
    differ and the shape does not, so the row does not record which it was.
    """

    jurisdiction: str
    name: str
    citation: str
    relevance: str


def _tables(text: str) -> dict[str, list[str]]:
    """The lines of each B.n section, keyed by jurisdiction."""
    if APPENDIX_B not in text:
        raise AppendixError(f"{METHODOLOGY.name} has no {APPENDIX_B!r} heading")

    body = text[text.index(APPENDIX_B) :]
    starts: dict[str, int] = {}
    for key, heading in SECTIONS.items():
        if heading not in body:
            raise AppendixError(f"Appendix B has no {heading!r} section")
        starts[key] = body.index(heading)

    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    out: dict[str, list[str]] = {}
    for i, (key, start) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(body)
        out[key] = body[start:end].splitlines()
    return out


def parse(path: Path = METHODOLOGY) -> tuple[AppendixRow, ...]:
    """Every row of Appendix B tables B.1, B.2 and B.3, in document order."""
    text = path.read_text(encoding="utf-8")
    rows: list[AppendixRow] = []

    for jurisdiction, lines in _tables(text).items():
        seen_header = False
        for line in lines:
            if SEPARATOR.match(line):
                seen_header = True
                continue
            matched = ROW.match(line)
            if matched is None:
                continue
            cells = [c.strip() for c in matched["body"].split("|")]
            if not seen_header:
                # The header row. Three columns, whatever they are called.
                if len(cells) != 3:
                    raise AppendixError(
                        f"Appendix B.{jurisdiction} header has {len(cells)} columns, expected 3"
                    )
                continue
            if len(cells) != 3:
                raise AppendixError(
                    f"Appendix B row {cells[0]!r} has {len(cells)} columns, expected 3"
                )
            rows.append(AppendixRow(jurisdiction, *cells))

        if not any(r.jurisdiction == jurisdiction for r in rows):
            raise AppendixError(f"Appendix B.{jurisdiction} table has no rows")

    return tuple(rows)


def rules(path: Path = METHODOLOGY) -> tuple[str, ...]:
    """The numbered rules of Appendix B.4, in order.

    Read so a test can assert the five the code implements are still the five
    the paper states. A sixth rule appearing here and nowhere else is a rule
    nothing enforces.
    """
    text = path.read_text(encoding="utf-8")
    if "### B.4 Corpus rules" not in text:
        raise AppendixError("Appendix B has no B.4 Corpus rules section")
    body = text[text.index("### B.4 Corpus rules") :]
    found = re.findall(r"^\d+\.\s+(.+?)(?=\n\d+\.\s|\n##|\Z)", body, re.M | re.S)
    return tuple(" ".join(rule.split()) for rule in found)
