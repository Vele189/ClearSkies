"""CI and `make test-spatial` must run the same database-backed tests.

The tests that need PostGIS and pgvector skip everywhere else, so the only two
places they ever run are the database job and that target. The two lists were
kept by hand and drifted: `test_retrieval_sql.py` ran only locally and
`test_hex_detail_sql.py` only in CI, which means each was, in practice, run by
whoever happened to be looking. Cheap to check here, rather than by noticing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPATIAL = re.compile(r"tests/(test_\w+_sql\.py)")


def ci_workflow() -> dict[str, Any]:
    path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip(".github/workflows/ci.yml is not in this tree")
    return yaml.safe_load(path.read_text())  # type: ignore[no-any-return]


def makefile_recipe(target: str) -> str:
    path = REPO_ROOT / "Makefile"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("Makefile is not in this tree")
    _, _, rest = path.read_text().partition(f"\n{target}:")
    assert rest, f"the Makefile has no {target} target"
    lines: list[str] = []
    for line in rest.splitlines()[1:]:
        if not line.startswith("\t"):
            break
        lines.append(line)
    return "\n".join(lines)


def test_the_database_job_and_test_spatial_run_the_same_files() -> None:
    steps = ci_workflow()["jobs"]["database"]["steps"]
    in_ci = {name for step in steps for name in SPATIAL.findall(str(step.get("run", "")))}
    in_make = set(SPATIAL.findall(makefile_recipe("test-spatial")))

    assert in_ci == in_make
    assert in_ci == {p.name for p in (REPO_ROOT / "api" / "tests").glob("test_*_sql.py")}
