"""CS-403: the uptime check judges what a reader would see, not the status code."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "uptime_check.py"

API = "https://api.example"
WEB = "https://web.example"
TILES = "https://storage.example/tiles/clearskies-run85.pmtiles"


@pytest.fixture(scope="module")
def uptime() -> ModuleType:
    if not SCRIPT.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("scripts/uptime_check.py is not in this tree")
    spec = importlib.util.spec_from_file_location("uptime_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["uptime_check"] = module
    spec.loader.exec_module(module)
    return module


def site(**over: Any) -> Any:
    """A fake fetcher for a healthy site, with any URL's answer overridden."""
    answers: dict[str, tuple[int, bytes]] = {
        f"{API}/health": (
            200,
            json.dumps({"status": "ok", "database": "connected", "scored_hexes": 19881}).encode(),
        ),
        f"{WEB}/": (200, b'<div id="root"></div><script src="/assets/index-abc.js"></script>'),
        f"{WEB}/assets/index-abc.js": (200, f'const t="{TILES}";'.encode()),
        TILES: (206, b"PMTiles"),
    }
    answers.update(over)

    def get(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        return answers.get(url, (404, b""))

    return get


def test_a_healthy_site_passes_every_check(uptime: ModuleType) -> None:
    checks = uptime.run(API, WEB, site())

    assert [c.ok for c in checks] == [True, True, True]


def test_a_degraded_health_is_a_failure_even_with_a_200(uptime: ModuleType) -> None:
    """`/health` degrades rather than failing; the status code alone would pass."""
    degraded = json.dumps({"status": "degraded", "database": "unavailable"}).encode()
    checks = uptime.run(API, WEB, site(**{f"{API}/health": (200, degraded)}))

    assert checks[0].ok is False
    assert "database=unavailable" in checks[0].detail


def test_the_tile_archive_is_read_from_the_bundle_and_must_be_pmtiles(
    uptime: ModuleType,
) -> None:
    checks = uptime.run(API, WEB, site(**{TILES: (200, b"<html>")}))

    assert checks[2].ok is False
    assert "clearskies-run85.pmtiles" in checks[2].detail


def test_a_bundle_with_no_archive_url_fails_the_tile_check(uptime: ModuleType) -> None:
    checks = uptime.run(API, WEB, site(**{f"{WEB}/assets/index-abc.js": (200, b"nothing")}))

    assert checks[2].ok is False
