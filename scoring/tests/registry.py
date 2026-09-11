"""Loads `api/app/indicators.py`, the registry of record, off disk.

Shared by the drift guard and the section 14 guard. `api` and `scoring` are
separate distributions, so the registry cannot simply be imported; reading the
file is the point rather than a workaround.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest


def api_registry() -> Any:
    path = Path(__file__).resolve().parents[2] / "api" / "app" / "indicators.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("api/app/indicators.py is not in this tree")

    spec = importlib.util.spec_from_file_location("clearskies_indicators", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
