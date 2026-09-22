"""The two paid harnesses in scripts/, checked for what they claim about a run.

`scripts/run_citation_audit.py` and `scripts/run_redteam.py` call the model and
so never run in CI, which is how both came to stamp their fixture hexagons with
methodology 0.1.4 two releases after the paper moved on, and how the audit came
to exit 0 on a run in which 49 of 50 drafts errored. What those scripts report
about a run can be checked without a key or a database, and this file does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.assistant import audit, cost, retrieval
from app.methodology import METHODOLOGY_VERSION

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    path = SCRIPTS / f"{name}.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip(f"scripts/{name}.py is not in this tree")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def citation_audit() -> ModuleType:
    return load("run_citation_audit")


@pytest.fixture(scope="module")
def red_team() -> ModuleType:
    return load("run_redteam")


def test_the_audit_stamps_its_hexagons_with_the_current_methodology(
    citation_audit: ModuleType,
) -> None:
    context = citation_audit.build_context(audit.PROFILES[0], [], 0)
    assert context.methodology_version == METHODOLOGY_VERSION


def test_the_red_team_stamps_its_hexagon_with_the_current_methodology(
    red_team: ModuleType,
) -> None:
    assert red_team.FIXTURE_HEX.methodology_version == METHODOLOGY_VERSION


def drafts(module: ModuleType, outcomes: list[str], cached: int = 0) -> list[Any]:
    return [
        module.AuditedDraft(
            audit.PROFILES[i % len(audit.PROFILES)],
            "public_comment_letter",
            outcome,
            from_cache=i < cached,
        )
        for i, outcome in enumerate(outcomes)
    ]


def test_a_full_fresh_run_is_not_blocked(citation_audit: ModuleType) -> None:
    results = drafts(citation_audit, ["drafted"] * 3 + ["refused", "unverifiable"])
    assert citation_audit.gate_failures(results, 5, allow_cached=False) == []


def test_one_errored_draft_blocks_the_gate(citation_audit: ModuleType) -> None:
    results = drafts(citation_audit, ["drafted"] * 4 + ["error"])
    [reason] = citation_audit.gate_failures(results, 5, allow_cached=False)
    assert "4 of the 5" in reason


def test_a_schema_rejection_blocks_the_gate_as_the_report_counts_it_an_error(
    citation_audit: ModuleType,
) -> None:
    results = drafts(citation_audit, ["drafted"] * 4 + ["schema_rejected"])
    assert citation_audit.gate_failures(results, 5, allow_cached=False)


def test_a_run_shorter_than_asked_for_blocks_the_gate(citation_audit: ModuleType) -> None:
    results = drafts(citation_audit, ["drafted"] * 4)
    assert citation_audit.gate_failures(results, 5, allow_cached=False)


def test_cached_drafts_block_the_gate_unless_allowed(citation_audit: ModuleType) -> None:
    results = drafts(citation_audit, ["drafted"] * 5, cached=2)
    [reason] = citation_audit.gate_failures(results, 5, allow_cached=False)
    assert "2 drafts were served from the draft cache" in reason
    assert citation_audit.gate_failures(results, 5, allow_cached=True) == []


def test_the_report_says_the_gate_is_not_met_when_blocked(citation_audit: ModuleType) -> None:
    results = drafts(citation_audit, ["drafted"] * 4 + ["error"], cached=1)
    blocked = citation_audit.gate_failures(results, 5, allow_cached=False)
    report = citation_audit.render(results, "gpt-4o", "v", cost.Spend(0.0, 0, 0), blocked)

    assert "**The gate is not met.**" in report
    assert "Zero unverifiable citations reached a shown draft" not in report
    assert "| Of which served from the draft cache | 1 |" in report
    assert f"- Methodology version: `{METHODOLOGY_VERSION}`" in report


class FakeConnection:
    async def fetch(self, _query: str) -> list[dict[str, Any]]:
        return [{"registry_id": "110000350053", "name": "A", "has_title_v": True}]

    async def close(self) -> None:
        return None


async def run_audit(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: str,
    *extra: str,
) -> int:
    """The whole of `main_async`, with the model, the database and the spend
    ledger replaced, so that only the harness's own bookkeeping is under test."""

    async def connect(_url: str) -> FakeConnection:
        return FakeConnection()

    async def active_version(_conn: Any) -> str:
        return "appendix-b-test"

    async def month_to_date(_conn: Any) -> cost.Spend:
        return cost.Spend(0.0, 0, 0)

    async def audit_one(
        _conn: Any, _client: Any, _model: Any, _embedding: str, profile: Any, _ctx: Any, kind: str
    ) -> Any:
        return module.AuditedDraft(profile, kind, outcome)

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(module.asyncpg, "connect", connect)
    monkeypatch.setattr(retrieval, "active_version", active_version)
    monkeypatch.setattr(module.cost, "month_to_date", month_to_date)
    monkeypatch.setattr(module, "audit_one", audit_one)
    monkeypatch.setattr(module, "AsyncOpenAI", lambda: None)
    monkeypatch.setattr(module, "OpenAIChatModel", lambda _name: None)

    args = module.parse_args(["--count", "4", "--out", str(tmp_path / "report.md"), *extra])
    result: int = await module.main_async(args)
    return result


async def test_the_audit_exits_non_zero_when_every_draft_errors(
    citation_audit: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert await run_audit(citation_audit, monkeypatch, tmp_path, "error") == 1


async def test_the_audit_exits_non_zero_when_drafts_are_refused_but_none_produced(
    citation_audit: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert await run_audit(citation_audit, monkeypatch, tmp_path, "refused") == 1


async def test_a_clean_fresh_audit_exits_zero(
    citation_audit: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert await run_audit(citation_audit, monkeypatch, tmp_path, "drafted") == 0
