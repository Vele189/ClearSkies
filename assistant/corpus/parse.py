"""Turn a source document into sections, keeping the hierarchy inside them.

A *section* here is the citable unit a draft names when it says where a
proposition comes from: 42 U.S.C. § 7412, 40 C.F.R. § 7.35, or an opinion.

Sections are returned as a list of blocks rather than as a wall of text, and
that is not a tidiness decision. Statutes are nested, the nesting is part of the
citation, and flattening it produces citations that are wrong in the most
dangerous available way. § 7412(a) has paragraphs (1), (2), (3) inside it; read
flat, those look like subsections of the section, and text from § 7412(a)(1)
gets labelled § 7412(1) — a subdivision that does not exist, attached to a
section that does. The existence half of CS-305 would pass it. So depth is
carried out of the parser, and `chunking` composes the label from the path.

What gets dropped is deliberate and the same in each parser: editorial
apparatus. The US Code's source credits, amendment notes and editorial notes are
not the statute, and a model shown them alongside the statute will quote a
committee note as though Congress enacted it. The Caselaw Access Project's
headnotes are a publisher's summary and not the court's words. Dropping both
costs a little recall and removes a class of citation that looks right and is
not.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from corpus.fetch import Fetched


@dataclass(frozen=True)
class Block:
    """One paragraph of a section, at a known depth in its hierarchy.

    `marker` is the subdivision letter or number without its parentheses, or
    None for prose that carries no marker of its own and belongs to whatever
    subdivision is open above it.

    `citable` says whether the marker is trustworthy enough to put in a
    citation. It is True when the publisher marked the subdivision explicitly,
    and False when the depth had to be inferred from the marker style deep
    inside a run of body text. An uncitable marker still delimits the text; it
    just does not lend its letter to the label, so the chunk is cited against
    the nearest subdivision that was marked. A slightly broader citation is
    always safe. A precise one that names a subdivision the statute does not
    have is the failure this whole phase is built to prevent.
    """

    depth: int
    marker: str | None
    text: str
    citable: bool = True


@dataclass(frozen=True)
class Section:
    """One citable unit of one authority."""

    number: str
    heading: str
    blocks: tuple[Block, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


class ParseError(RuntimeError):
    """A source document did not contain what its parser expected."""


# ---- Shared helpers -----------------------------------------------------

TAG = re.compile(r"<[^>]+>")
COMMENT = re.compile(r"<!--.*?-->", re.S)
BLANKS = re.compile(r"\n{3,}")

# "(a)", "(1)", "(iii)", "(A)" at the start of a paragraph.
MARKER = re.compile(r"^\((?P<marker>[A-Za-z0-9]{1,4})\)(?=\s|$)")


def _plain(fragment: str) -> str:
    """Markup to text, keeping paragraph breaks and losing everything else."""
    text = COMMENT.sub("", fragment)
    text = re.sub(r"(?i)</(p|h[1-6]|div|li|tr)>", "\n\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return BLANKS.sub("\n\n", "\n".join(lines)).strip()


def _marker_rank(marker: str) -> tuple[int, ...]:
    """Which depths a marker could plausibly sit at, best guess first.

    The US Code and the CFR both nest (a), (1), (A), (i), (I). The awkward case
    is that "i" is both a letter and a roman numeral and "I" is both, so the
    style alone cannot always decide. The caller resolves it with the stack it
    already has; this returns the candidates in conventional order.
    """
    if marker.isdigit():
        return (1,)
    roman = set(marker.lower()) <= set("ivxlcdm")
    if marker.islower():
        if roman and len(marker) > 1:
            return (3,)
        return (3, 0) if roman else (0, 3)
    if roman and len(marker) > 1:
        return (4,)
    return (4, 2) if roman else (2, 4)


ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
# The first marker of each sequence. A marker that opens a subdivision is one of
# these; anything else has to continue a sequence already running.
FIRST_MARKERS = {"a", "1", "A", "i", "I"}


def _roman_value(marker: str) -> int | None:
    lowered = marker.lower()
    if not lowered or set(lowered) - set(ROMAN_VALUES):
        return None
    total = 0
    previous = 0
    for char in reversed(lowered):
        value = ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total


def _letter_value(marker: str) -> int | None:
    """The position of a letter marker in the a, b, ... z, aa, bb sequence."""
    if not marker.isalpha() or len(set(marker.lower())) != 1:
        return None
    base = ord(marker.lower()[0]) - ord("a") + 1
    return base + 26 * (len(marker) - 1)


def _succeeds(marker: str, previous: str) -> bool:
    """True when `marker` is the next one after `previous` in its own sequence.

    Sequence position rather than style is what decides which level a marker
    belongs to, and the difference is not academic. Style alone cannot tell
    subsection (i) of § 7412 from clause (i) inside § 7412(c)(9)(B), because
    "i" is both the ninth letter and the first roman numeral. Worse, the letters
    c, d, l and m are *also* roman numerals, so a style comparison happily reads
    clause (i) as continuing subsection (c) and files a clause four levels deep
    as a subsection of the section. That produced a chunk of § 7412(c)(9)(B)(i)
    labelled § 7412(i), which is a real subsection about a different subject:
    a citation that exists, that a reader can look up, and that does not say
    what the draft says it says.

    Succession is unambiguous: (i) follows (h), and (i) does not follow (c).
    """
    if marker.isdigit() and previous.isdigit():
        return int(marker) == int(previous) + 1
    if marker.isdigit() != previous.isdigit():
        return False
    if marker.islower() != previous.islower():
        return False

    letter, previous_letter = _letter_value(marker), _letter_value(previous)
    if letter is not None and previous_letter is not None and letter == previous_letter + 1:
        return True
    roman, previous_roman = _roman_value(marker), _roman_value(previous)
    return roman is not None and previous_roman is not None and roman == previous_roman + 1


def _infer_depth(marker: str, stack: list[str | None]) -> int:
    """The depth a marker belongs at, given the subdivisions currently open.

    Three rules, in order. A marker that continues an open sequence sits at that
    sequence's depth. A marker that opens a sequence sits one below the deepest
    thing open. Anything else falls back to the conventional depth for its
    style, which is a guess, and is only reached by documents that number
    themselves unconventionally.
    """
    for depth in range(len(stack) - 1, -1, -1):
        current = stack[depth]
        if current is not None and _succeeds(marker, current):
            return depth

    deepest = max((d for d, m in enumerate(stack) if m is not None), default=-1)
    if marker in FIRST_MARKERS:
        return deepest + 1

    preferred = _marker_rank(marker)[0]
    return preferred if preferred > deepest else deepest + 1


def _blocks_from_markers(paragraphs: list[str], max_citable_depth: int = 1) -> tuple[Block, ...]:
    """Depth-annotated blocks for a source that encodes nesting only in the text.

    Used for the eCFR, whose XML is a flat run of <P> elements with the
    subdivision marker written inline, and as the fallback anywhere else.

    `max_citable_depth` bounds how deep an inferred marker may appear in a
    citation. With no markup to confirm it, inference is dependable for the
    first two levels of a shallow part like 40 C.F.R. Part 7 and increasingly
    speculative below that, so deeper markers still delimit text but do not
    lend their letters to a label.
    """
    blocks: list[Block] = []
    stack: list[str | None] = []
    for para in paragraphs:
        matched = MARKER.match(para)
        if matched is None:
            depth = max((d for d, m in enumerate(stack) if m is not None), default=0)
            blocks.append(Block(depth=depth, marker=None, text=para))
            continue
        marker = matched["marker"]
        depth = _infer_depth(marker, stack)
        while len(stack) <= depth:
            stack.append(None)
        stack[depth] = marker
        del stack[depth + 1 :]
        blocks.append(
            Block(
                depth=depth,
                marker=marker,
                text=para,
                citable=depth <= max_citable_depth,
            )
        )
    return tuple(blocks)


# ---- United States Code (govinfo) ---------------------------------------
#
# govinfo marks the structure of a chapter document twice over: HTML comments
# delimit the fields of a section (head, statute, sourcecredit, notes), and the
# class on each element inside the statute field gives its depth. Both are used.
# The comments say which text is the law, and the classes say how it nests, so
# neither has to be guessed at from the prose.

FIELD = r"<!-- field-start:{0} -->(.*?)<!-- field-end:{0} -->"
HEAD_FIELD = re.compile(FIELD.format("head"), re.S)
SECTION_BLOCK = re.compile(
    r"<!-- field-start:head -->(?P<head>.*?)<!-- field-end:head -->"
    r"(?P<rest>.*?)(?=<!-- field-start:head -->|\Z)",
    re.S,
)
STATUTE_FIELD = re.compile(FIELD.format("statute"), re.S)

# The class on a heading or paragraph, and the depth it means.
HEAD_DEPTH = {
    "subsection-head": 0,
    "paragraph-head": 1,
    "subparagraph-head": 2,
    "clause-head": 3,
    "subclause-head": 4,
    "item-head": 5,
}
ELEMENT = re.compile(
    r"<(?P<tag>h[1-6]|p)\s+class=\"(?P<cls>[a-z0-9-]+)\"[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S,
)

# "§7412. Hazardous air pollutants", and the repealed and omitted variants.
#
# The dash in a suffixed number is an EN DASH in what govinfo serves, not a
# hyphen. Matching only the hyphen does not fail, it truncates: every section of
# Title VI parses as "2000d" with the rest of its number pushed into the
# heading, and nine distinct authorities end up sharing one citation. A citation
# that names a real section which does not say what the draft claims is exactly
# the failure CS-305 exists to catch, so the character class is wide and
# `_normalise_number` puts the result back into the hyphen form that citations
# and govinfo's own link service use.
DASHES = "‐‑‒–—−-"
SECTION_HEAD = re.compile(
    rf"§+\s*(?P<number>\d+[A-Za-z]*(?:[{DASHES}]\d+[A-Za-z]*)*)\.?\s*(?P<heading>.*)",
    re.S,
)


def _normalise_number(number: str) -> str:
    """Typographic dashes to the plain hyphen a citation is written with."""
    for dash in DASHES[:-1]:
        number = number.replace(dash, "-")
    return number


def _us_code_blocks(statute_html: str) -> tuple[Block, ...]:
    """Depth-annotated blocks from one statute field.

    Depth comes from the element class. A heading class names its level
    outright; a body class carries its indentation in ems, which govinfo uses
    consistently enough to key on and which is the only signal for the many
    paragraphs that have no heading of their own.
    """
    blocks: list[Block] = []
    stack: list[str | None] = []
    for element in ELEMENT.finditer(statute_html):
        text = _plain(element["body"])
        if not text:
            continue
        cls = element["cls"]

        if cls in HEAD_DEPTH:
            depth = HEAD_DEPTH[cls]
            matched = MARKER.match(text)
            marker = matched["marker"] if matched else None
            while len(stack) <= depth:
                stack.append(None)
            stack[depth] = marker
            del stack[depth + 1 :]
            blocks.append(Block(depth=depth, marker=marker, text=text))
            continue

        # A body paragraph, a table, or anything else govinfo puts inside the
        # statute field. Depth comes from the marker style resolved against the
        # subdivisions currently open, NOT from the em indentation in the class.
        #
        # The indentation is tempting and wrong. govinfo indents relative to the
        # nearest heading, so "(A)" under a paragraph head "(3)" is written
        # statutory-body-1em, the same class as "(1)" under a subsection head.
        # Reading the em as the depth puts (3)(A) at the same level as (1), and
        # the citation comes out as § 7412(b)(A): a subdivision that does not
        # exist, on a section that does.
        matched = MARKER.match(text)
        marker = matched["marker"] if matched else None
        if marker is None:
            depth = max((d for d, m in enumerate(stack) if m is not None), default=0)
            blocks.append(Block(depth=depth, marker=None, text=text))
            continue

        depth = _infer_depth(marker, stack)
        while len(stack) <= depth:
            stack.append(None)
        stack[depth] = marker
        del stack[depth + 1 :]
        blocks.append(Block(depth=depth, marker=marker, text=text, citable=False))

    return tuple(blocks)


def us_code(fetched: Fetched) -> tuple[Section, ...]:
    """Every section of a US Code chapter or subchapter document."""
    body = fetched.text
    if not HEAD_FIELD.search(body):
        raise ParseError(
            f"{fetched.url}: no field-start:head markers. govinfo has changed the "
            "HTML it serves, and this parser must be updated rather than guessed at."
        )

    sections: list[Section] = []
    for block in SECTION_BLOCK.finditer(body):
        head = _plain(block["head"])
        matched = SECTION_HEAD.match(head)
        if matched is None:
            # Structural heads: "SUBCHAPTER I - PROGRAMS AND ACTIVITIES". Not a
            # citable unit and carrying no operative text.
            continue

        statute = STATUTE_FIELD.search(block["rest"])
        if statute is None:
            # Repealed, omitted, or transferred. Appendix B is a corpus of what
            # the law says, and a section with no text says nothing.
            continue

        blocks = _us_code_blocks(statute.group(1))
        if not blocks:
            continue
        sections.append(
            Section(
                number=_normalise_number(matched["number"]),
                heading=" ".join(matched["heading"].split()),
                blocks=blocks,
            )
        )

    if not sections:
        raise ParseError(f"{fetched.url}: parsed no sections")
    return tuple(sections)


# ---- Code of Federal Regulations (eCFR) ---------------------------------
#
# The versioner API serves XML whose DIV8 elements are sections. Inside one,
# paragraphs are a flat run of <P> with the marker written inline, so nesting is
# inferred from the markers rather than read off the markup.

CFR_SECTION = re.compile(
    r'<DIV8[^>]*\bN="(?P<number>[^"]+)"[^>]*\bTYPE="SECTION"[^>]*>(?P<body>.*?)</DIV8>',
    re.S,
)
CFR_HEAD = re.compile(r"<HEAD>(?P<head>.*?)</HEAD>", re.S)
CFR_PARAGRAPH = re.compile(r"<P[^>]*>(?P<body>.*?)</P>", re.S)


def ecfr(fetched: Fetched) -> tuple[Section, ...]:
    """Every section of one eCFR part."""
    body = fetched.text
    matches = list(CFR_SECTION.finditer(body))
    if not matches:
        raise ParseError(f"{fetched.url}: no DIV8 SECTION elements. The eCFR schema has changed.")

    sections: list[Section] = []
    for match in matches:
        inner = match["body"]
        head_match = CFR_HEAD.search(inner)
        heading = _plain(head_match["head"]) if head_match else ""
        heading = re.sub(r"^§+\s*[\d.]+\s*", "", heading).strip()

        paragraphs = [
            text for text in (_plain(p["body"]) for p in CFR_PARAGRAPH.finditer(inner)) if text
        ]
        if not paragraphs:
            continue
        number = _normalise_number(match["number"].replace("§", "").strip())
        sections.append(
            Section(
                number=number,
                heading=heading,
                blocks=_blocks_from_markers(paragraphs),
            )
        )

    if not sections:
        raise ParseError(f"{fetched.url}: parsed no sections")
    return tuple(sections)


# ---- Case law (Caselaw Access Project) ----------------------------------


def caselaw(fetched: Fetched) -> tuple[Section, ...]:
    """One opinion, as a single section with no internal subdivisions.

    Flat on purpose. An opinion has no subsections, and inventing labels for its
    paragraphs would produce citable units that are not citable: there is no
    such thing as "paragraph 14 of Sandoval" in a citation a reader can check.
    The whole opinion carries one label, the reporter citation, and CS-305
    checks propositions against the opinion as a whole.
    """
    try:
        payload = json.loads(fetched.text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"{fetched.url}: not JSON: {exc}") from exc

    opinions = payload.get("casebody", {}).get("opinions") or []
    parts = [op.get("text", "") for op in opinions if op.get("text")]
    if not parts:
        raise ParseError(f"{fetched.url}: the record carries no opinion text")

    name = payload.get("name_abbreviation") or payload.get("name") or ""
    blocks = tuple(Block(depth=0, marker=None, text=" ".join(part.split())) for part in parts)
    return (Section(number="", heading=name, blocks=blocks),)
