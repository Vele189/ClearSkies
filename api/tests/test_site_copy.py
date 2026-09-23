"""The prohibited-language scan, over the site's own copy (CS-407).

The red-team scan reads generated drafts. Nothing read the copy the project
writes by hand, which is the copy a reader sees first and the copy no model is
ever asked to justify. A page that asserted what a draft may not assert would
be the same failure with a longer half-life, because a draft is reviewed before
it is used and a page ships once.

**What this cannot decide.** Every category here fires on the caveats
themselves -- "not a finding of wrongdoing" contains *wrongdoing* -- and that
over-flagging is the scan working as designed. So the rule is not "no matches";
it is that every match sits inside a negation, and the list below is the
reviewed set. A new match fails until somebody reads it and adds it, which is
the review being repeated rather than remembered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.assistant.redteam import scan

WEB = Path(__file__).resolve().parents[2] / "web" / "src"

#: Phrases the 2026-09-23 pass read and accepted, with why each one is allowed.
#: Keyed by file, so moving copy between pages re-opens the question of whether
#: it still reads the same way in its new home.
#:
#: Two kinds, and the difference is the whole point of the review:
#:
#: * ``caveat`` -- the word appears inside the denial of the thing it names.
#:   "not a finding of wrongdoing" contains *wrongdoing*. Checked below: if the
#:   sentence loses its negation the phrase is asserting what it used to deny.
#: * ``self`` -- the sentence is about a decision **this project** made, not
#:   about what a facility or operator intended. "This is deliberate" describes
#:   the methodology choosing not to score race. The prohibition is on claims
#:   about an operator's state of mind; the project is entitled to describe its
#:   own.
REVIEWED: dict[str, tuple[tuple[str, str], ...]] = {
    "components/Footer.tsx": (("wrongdoing", "caveat"),),
    "components/HexPanel.tsx": (("wrongdoing", "caveat"),),
    "components/DraftPanel.tsx": (("lawsuit", "caveat"),),
    "pages/AboutPage.tsx": (("wrongdoing", "caveat"),),
    "pages/MethodologyPage.tsx": (
        ("wrongdoing", "caveat"),
        # "Race is recorded and never scored. This is deliberate."
        ("deliberate", "self"),
    ),
    "pages/ModelCardPage.tsx": (
        ("lawsuit", "caveat"),
        ("federal court", "caveat"),
        ("sue", "caveat"),
        # The guardrails are "deliberately in different places"; the verifier is
        # checked with "deliberate traps". Both are about this system.
        ("deliberate", "self"),
    ),
}

#: The negations a ``caveat`` phrase has to sit inside.
NEGATED = re.compile(r"\b(not|never|no|cannot|does not|is not|are not|without)\b", re.IGNORECASE)

#: Where the clause holding a phrase begins. The scan's own 90-character window
#: is far too generous for this question -- over that much prose almost any
#: sentence contains a "not" somewhere, so a phrase that had lost its negation
#: would still find one belonging to the sentence next door. The negation has to
#: be in the same clause, and this is where the clause starts. Not a newline:
#: the copy is wrapped to a line length, so "They are not / findings of
#: wrongdoing" is one clause split across two lines and treating the break as a
#: boundary would report every wrapped caveat as a bare assertion.
CLAUSE_START = re.compile(r"[.;:!?>{}]")


def negated_in_clause(text: str, phrase: str) -> list[str]:
    """Occurrences of `phrase` whose own clause carries no negation."""
    naked: list[str] = []
    for match in re.finditer(re.escape(phrase), text, re.IGNORECASE):
        before = text[: match.start()]
        boundaries = [m.end() for m in CLAUSE_START.finditer(before)]
        clause = before[boundaries[-1] :] if boundaries else before
        if not NEGATED.search(clause):
            naked.append((clause + match.group(0)).strip()[-100:])
    return naked


def reviewed_for(key: str) -> tuple[tuple[str, str], ...]:
    return REVIEWED.get(key, ())


def copy_files() -> list[Path]:
    if not WEB.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("the frontend is not in this tree")
    return sorted(path for path in WEB.rglob("*.tsx") if ".test." not in path.name)


def test_every_flagged_phrase_in_the_site_copy_has_been_read() -> None:
    unreviewed: list[str] = []

    for path in copy_files():
        key = str(path.relative_to(WEB))
        allowed = reviewed_for(key)
        for flag in scan(path.read_text()):
            if any(phrase.lower() in flag.phrase.lower() for phrase, _ in allowed):
                continue
            unreviewed.append(f"{key}: {flag.category}: {flag.phrase!r} in {flag.context!r}")

    assert not unreviewed, (
        "New prohibited-vocabulary matches in the site copy. Read each one and "
        "either rewrite it or add it to REVIEWED with the reason:\n  " + "\n  ".join(unreviewed)
    )


def test_each_reviewed_phrase_still_sits_inside_a_negation() -> None:
    """A ``caveat`` exemption is not a permanent exemption for the word.

    It records that a phrase was read as the denial of the thing it names. If
    the sentence around it loses its negation, the phrase is asserting what it
    used to deny and the exemption has to be re-earned. ``self`` exemptions are
    not checked this way: they are about the project's own decisions and have
    nothing to negate.
    """
    naked: list[str] = []

    for path in copy_files():
        key = str(path.relative_to(WEB))
        text = path.read_text()
        for phrase, kind in reviewed_for(key):
            if kind != "caveat":
                continue
            naked.extend(f"{key}: ...{clause!r}" for clause in negated_in_clause(text, phrase))

    assert not naked, "A reviewed phrase is no longer inside a negation:\n  " + "\n  ".join(naked)


def test_there_is_no_send_submit_or_publish_path() -> None:
    """CS-407's last criterion, asserted rather than remembered.

    The only POST the frontend makes is /draft, which asks the API to write a
    document and return it. Anything that posted somewhere else, opened a mail
    client or submitted a form would be a way for a draft to leave the system
    without a person having read it, which the project says twice on every page
    that it does not have.
    """
    offenders: list[str] = []
    outward = re.compile(r"mailto:|<form\b|method=\"POST\"|navigator\.share", re.IGNORECASE)

    for path in sorted(WEB.rglob("*.ts")) + copy_files():
        if ".test." in path.name:
            continue
        text = path.read_text()
        for match in outward.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(WEB)}:{line}: {match.group(0)}")

    # api.ts posts to /draft. That is the generation call, and the endpoint
    # returns the document to the caller rather than sending it anywhere.
    allowed = {"lib/api.ts"}
    unexpected = [o for o in offenders if o.split(":")[0] not in allowed]

    assert not unexpected, "An outward path the project says does not exist:\n  " + "\n  ".join(
        unexpected
    )
