"""Loads modules from the `api` distribution off disk.

`api` and `scoring` are separate distributions with separate dependency sets,
which is what lets this package declare none. The cost is that a few tables and
constants exist in two places, so the guards read the registry of record from
the file rather than importing it. Reading the file is the point, not a
workaround.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def api_module(name: str) -> Any:
    """Import `api/app/<name>.py` under its own name, without installing `api`."""
    path = REPO_ROOT / "api" / "app" / f"{name}.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip(f"api/app/{name}.py is not in this tree")

    spec = importlib.util.spec_from_file_location(f"clearskies_api_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def api_registry() -> Any:
    """The indicator registry of record, `api/app/indicators.py`."""
    return api_module("indicators")
