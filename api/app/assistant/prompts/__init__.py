"""Versioned prompts, loaded from the repository and checksummed.

A prompt is part of how a document was produced, in the same way the methodology
version is part of how a score was produced. Section 17 makes that argument for
scores; it applies with more force to a document somebody may have filed with an
agency. So every generated draft records the prompt version behind it, and a
released version is frozen.

Frozen is enforced rather than asked for. `CHECKSUMS` below records the SHA-256
of every file in every released version, and `verify()` fails when one has
changed. Editing v1 to fix a phrase would otherwise leave every past draft
stamped "v1" while v1 now says something else — an audit trail that reads as
precise and is wrong, which is worse than one that is missing. Changing a prompt
means adding a version.

The text lives in Markdown files rather than in Python string literals so that a
change to what the model is told shows up in a diff as prose, reviewable by
somebody who does not read Python. The safety rules in `system.md` are the point
of this whole module and they should be readable by whoever is responsible for
them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

# The version used unless a caller pins an older one. Bumping this is a
# deliberate act: drafts generated before and after are not comparable, and
# CS-306 treats a prompt revision as a cache invalidation.
CURRENT_VERSION = "v3"

SYSTEM_FILE = "system.md"


class PromptError(RuntimeError):
    """A prompt version is missing, incomplete, or has been edited."""


@dataclass(frozen=True)
class Prompt:
    """The instructions for one document type at one version."""

    version: str
    document_type: str
    system: str
    guidance: str

    @property
    def text(self) -> str:
        """What the model is actually instructed with.

        The shared rules first and the type-specific guidance second, so the
        prohibitions are established before the document is described. A model
        told how to write a complaint and only then told what it may not claim
        has already been given a shape to fill.
        """
        return f"{self.system}\n\n---\n\n{self.guidance}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def versions() -> list[str]:
    """Every prompt version in the repository, oldest first."""
    return sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and p.name.startswith("v"))


def load(document_type: str, version: str = CURRENT_VERSION) -> Prompt:
    """The prompt for one document type, at one version."""
    directory = PROMPTS_DIR / version
    if not directory.is_dir():
        raise PromptError(
            f"no prompt version {version!r}; the repository has {', '.join(versions())}"
        )

    system_path = directory / SYSTEM_FILE
    guidance_path = directory / f"{document_type}.md"
    for path in (system_path, guidance_path):
        if not path.is_file():
            raise PromptError(f"prompt version {version} has no {path.name}")

    return Prompt(
        version=version,
        document_type=document_type,
        system=system_path.read_text(encoding="utf-8").strip(),
        guidance=guidance_path.read_text(encoding="utf-8").strip(),
    )


def file_checksums(version: str) -> dict[str, str]:
    """The hash of every file in one version, by file name."""
    directory = PROMPTS_DIR / version
    if not directory.is_dir():
        raise PromptError(f"no prompt version {version!r}")
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("*.md"))
    }


# The released versions, frozen. Regenerate deliberately when adding a version,
# never to make a failing test pass: a checksum that moved means a released
# prompt was edited, and the fix is a new version.
CHECKSUMS: dict[str, dict[str, str]] = {
    "v1": {
        "agency_complaint_draft.md": (
            "024b297adc3bfea406e80955398e02cbdf07f58357b5488f0e674fbbf9b79502"
        ),
        "community_briefing_sheet.md": (
            "cc0655c906fd8b260cb4b70ec6547ddbc94584d48d18c8bb7e480044692a345f"
        ),
        "journalist_fact_sheet.md": (
            "048625f4778f856aecdffd4733a01eee0b2c0b02431fcb63dc46f81291eb9e54"
        ),
        "public_comment_letter.md": (
            "4367216db944562aa9423d2f34878b0bd6b5044c4ca571d86a4d274542c70615"
        ),
        "system.md": ("b3c921d414929516a17b32fba051737e8521754cd26e3024d060b59c77001997"),
    },
    "v2": {
        "agency_complaint_draft.md": (
            "024b297adc3bfea406e80955398e02cbdf07f58357b5488f0e674fbbf9b79502"
        ),
        "community_briefing_sheet.md": (
            "cc0655c906fd8b260cb4b70ec6547ddbc94584d48d18c8bb7e480044692a345f"
        ),
        "journalist_fact_sheet.md": (
            "048625f4778f856aecdffd4733a01eee0b2c0b02431fcb63dc46f81291eb9e54"
        ),
        "public_comment_letter.md": (
            "4367216db944562aa9423d2f34878b0bd6b5044c4ca571d86a4d274542c70615"
        ),
        "system.md": ("dbb2ae8830b5f45a2954f2ad9a72fcd05f2ed29aeee560b3f9edc9a36f66f6ca"),
    },
    "v3": {
        "agency_complaint_draft.md": (
            "024b297adc3bfea406e80955398e02cbdf07f58357b5488f0e674fbbf9b79502"
        ),
        "community_briefing_sheet.md": (
            "cc0655c906fd8b260cb4b70ec6547ddbc94584d48d18c8bb7e480044692a345f"
        ),
        "journalist_fact_sheet.md": (
            "048625f4778f856aecdffd4733a01eee0b2c0b02431fcb63dc46f81291eb9e54"
        ),
        "public_comment_letter.md": (
            "4367216db944562aa9423d2f34878b0bd6b5044c4ca571d86a4d274542c70615"
        ),
        "system.md": ("3fe0566599b665693a2ad160fd604206801ede309d27d21a82c2dddefc2210ea"),
    },
}


def verify(version: str = CURRENT_VERSION) -> list[str]:
    """Ways a released prompt version has stopped matching its record."""
    expected = CHECKSUMS.get(version)
    if expected is None:
        return [f"prompt version {version} has no recorded checksums"]

    actual = file_checksums(version)
    problems: list[str] = []
    for name, digest in sorted(expected.items()):
        if name not in actual:
            problems.append(f"{version}/{name} is recorded but missing")
        elif digest and actual[name] != digest:
            problems.append(
                f"{version}/{name} has been edited since it was released; "
                "add a new prompt version rather than changing a released one"
            )
    for name in sorted(set(actual) - set(expected)):
        problems.append(f"{version}/{name} is in the repository but not recorded")
    return problems
