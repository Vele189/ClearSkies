#!/usr/bin/env python3
"""Fail when api/requirements.txt drifts from api/pyproject.toml.

The API service is deployed by Railpack, which installs Python dependencies
only when it finds requirements.txt, uv.lock, poetry.lock, pdm.lock or a
Pipfile. A bare pyproject.toml is enough for it to detect Python and choose a
start command, so the build succeeds and the container comes up with none of
the dependencies in it. That failure is silent until the health check has
burned its whole retry window.

So api/requirements.txt has to exist, and it has to say the same thing as the
[project] dependencies in pyproject.toml. Nothing keeps two hand-written lists
in agreement except a check that reads both, which is this file.

Run directly, or via `make check`. No arguments, no dependencies beyond the
standard library.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "api" / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "api" / "requirements.txt"


def normalize(spec: str) -> str:
    """Compare requirements ignoring only whitespace and case.

    Version specifiers are deliberately part of the comparison. A floor that
    matches in one file and not the other is exactly the drift worth catching.
    """
    return "".join(spec.split()).lower()


def read_pyproject_dependencies() -> list[str]:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return list(data.get("project", {}).get("dependencies", []))


def read_requirements() -> list[str]:
    lines = REQUIREMENTS.read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main() -> int:
    if not REQUIREMENTS.exists():
        print(f"error: {REQUIREMENTS.relative_to(REPO_ROOT)} is missing.")
        print("Railpack installs nothing without it and the deploy comes up empty.")
        return 1

    declared = read_pyproject_dependencies()
    pinned = read_requirements()

    by_norm_declared = {normalize(d): d for d in declared}
    by_norm_pinned = {normalize(p): p for p in pinned}

    missing = [by_norm_declared[k] for k in by_norm_declared.keys() - by_norm_pinned.keys()]
    extra = [by_norm_pinned[k] for k in by_norm_pinned.keys() - by_norm_declared.keys()]

    if not missing and not extra:
        print(f"api/requirements.txt matches pyproject.toml ({len(declared)} dependencies).")
        return 0

    print("api/requirements.txt and api/pyproject.toml disagree.\n")
    for dep in sorted(missing):
        print(f"  in pyproject.toml but not requirements.txt: {dep}")
    for dep in sorted(extra):
        print(f"  in requirements.txt but not pyproject.toml: {dep}")
    print("\npyproject.toml is the source of truth. Copy its [project] dependencies")
    print("into api/requirements.txt verbatim, keeping the version specifiers.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
