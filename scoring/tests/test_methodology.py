"""The restated methodology version must not drift from the registry of record.

Section 17 makes the version part of what a score means: every published score
carries the version that produced it, and historical scores are not recomputed
under a new one. A scoring package that stamps a different string from the one
the service reports breaks that quietly, and only an auditor trying to reproduce
a score from the paper would ever find out.
"""

from burden.methodology import METHODOLOGY_VERSION
from tests.registry import api_module


def test_the_version_matches_the_api() -> None:
    assert METHODOLOGY_VERSION == api_module("methodology").METHODOLOGY_VERSION


def test_the_version_looks_like_a_semantic_version() -> None:
    # Section 17 versions the document semantically, and the digest of a run
    # embeds this string, so a malformed one travels a long way.
    parts = METHODOLOGY_VERSION.split(".")

    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
