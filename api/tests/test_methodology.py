"""The methodology version the service reports must be the one the paper is at.

Section 17: every published score carries the version that produced it, and
historical scores are not silently recomputed under a new one. That only means
anything if the string the code reports is the string the document is actually
at. These two had already drifted once, the paper at 0.1.2 and `/indicators`
still answering 0.1.0, which is how a score gets stamped with rules it was not
produced under.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.methodology import METHODOLOGY_VERSION

CHANGELOG_ENTRY = re.compile(r"^### v(\d+\.\d+\.\d+)\b", re.MULTILINE)


def changelog_versions() -> list[str]:
    """Every version heading in section 18, newest first as the document lists them."""
    path = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("docs/methodology.md is not in this tree")

    text = path.read_text()
    _, _, changelog = text.partition("## 18. Changelog")
    assert changelog, "section 18 is missing from docs/methodology.md"
    return CHANGELOG_ENTRY.findall(changelog)


def test_the_declared_version_is_the_newest_changelog_entry() -> None:
    versions = changelog_versions()

    assert versions, "section 18 lists no versions"
    assert METHODOLOGY_VERSION == versions[0]


def test_the_changelog_is_ordered_newest_first() -> None:
    # The test above takes the first heading as current, so the ordering it
    # assumes is worth asserting rather than trusting.
    versions = changelog_versions()
    parsed = [tuple(int(part) for part in v.split(".")) for v in versions]

    assert parsed == sorted(parsed, reverse=True)


def test_the_endpoint_reports_the_declared_version(client: TestClient) -> None:
    body = client.get("/indicators").json()

    assert body["methodology_version"] == METHODOLOGY_VERSION


def test_the_version_is_not_hardcoded_anywhere_in_the_router() -> None:
    # The literal is what drifted last time. A reader changing the paper should
    # have exactly one place to change in the service.
    source = (Path(__file__).resolve().parents[1] / "app" / "routers" / "meta.py").read_text()

    assert "0.1." not in source
