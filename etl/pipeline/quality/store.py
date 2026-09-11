"""Where check results are kept, so that a threshold can be argued from history.

Most of the thresholds in `expectations.py` are envelopes: loose enough to catch
a catastrophe and too loose to catch drift, because four of the five adapters
have never run against live upstream and a tight range invented at a keyboard
fails on the first honest night. The way out is not a better guess. It is a
fortnight of observed values, which means every gate run has to write down what
it measured even when everything passed.

So `observed` is persisted for passing checks too. A report that keeps only its
failures can tell you the load was fine; it cannot tell you the ECHO facility
count has fallen four percent a week for a month, which is the failure that
matters and the one nobody notices in a single night's green tick.

**Two shapes, one record.** `JsonQualityStore` writes a directory per run, works
with no database, and is what the nightly job uses today. The `quality_run` and
`quality_check_result` tables in migration 0011 are the durable home; the store
that writes to them lands with the Postgres sink, and `rows_for_sql` below is the
payload it will insert, kept here so the two cannot describe a run differently.

**Manifests travel with the checks.** The acceptance criterion is "alongside the
manifests" and it is not decoration: a row count outside its range means one thing
when the pull was `ok` and another when it was `stale`, and a reader comparing two
nights needs both without joining across two systems.
"""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pipeline.metadata import PullMetadata
from pipeline.quality.results import QualityReport

# One line per check per run. Appended rather than rewritten, because the whole
# value of the file is that it is longer than the run that wrote it.
HISTORY = "history.jsonl"
REPORT = "report.json"
MANIFESTS = "manifests.json"
SUMMARY = "report.md"


@runtime_checkable
class QualityStore(Protocol):
    """Somewhere a run's checks and manifests are kept together."""

    def save(self, report: QualityReport, manifests: Sequence[PullMetadata]) -> None: ...

    def history(self, check: str | None = None) -> list[dict[str, Any]]:
        """Past observations, oldest first, for tuning a threshold from data."""
        ...


class JsonQualityStore:
    """A directory per run, plus one append-only history file across all runs.

    Layout::

        <root>/history.jsonl              every check of every run, one per line
        <root>/<run_id>/report.json       the full report
        <root>/<run_id>/manifests.json    what each adapter said about its pull
        <root>/<run_id>/report.md         the rendered page

    Deliberately files rather than a database. The gate has to be able to run in
    a GitHub Actions job that has no Postgres, and a nightly job that cannot
    record its own quality because the database was the thing that broke is not
    much of a gate.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, run_id: str) -> Path:
        return self.root / run_id

    def save(self, report: QualityReport, manifests: Sequence[PullMetadata] = ()) -> None:
        run_dir = self.path_for(report.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / REPORT).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / MANIFESTS).write_text(
            json.dumps([m.model_dump(mode="json") for m in manifests], indent=2),
            encoding="utf-8",
        )
        (run_dir / SUMMARY).write_text(report.markdown(), encoding="utf-8")

        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / HISTORY).open("a", encoding="utf-8") as handle:
            for row in rows_for_sql(report):
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def history(self, check: str | None = None) -> list[dict[str, Any]]:
        path = self.root / HISTORY
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if check is None:
            return rows
        return [row for row in rows if row["check"] == check]

    def observations(self, check: str, *, scope: str | None = None) -> list[float]:
        """Every value one check has measured, for deciding where its bound belongs."""
        return [
            row["observed"]
            for row in self.history(check)
            if row["observed"] is not None and (scope is None or row["scope"] == scope)
        ]


def rows_for_sql(report: QualityReport) -> list[dict[str, Any]]:
    """One flat row per check, matching `quality_check_result` in migration 0011.

    Flat on purpose. The question this table exists to answer is "what has this
    check measured over the last thirty runs", and that is a `WHERE check = ...
    ORDER BY checked_at` against one table, not a join through a nested document.
    """
    return [
        {
            "run_id": report.run_id,
            "checked_at": report.checked_at.isoformat(),
            "scope": result.scope,
            "table_name": result.table,
            "check": result.check,
            "field_name": result.field,
            "status": result.status,
            "observed": result.observed,
            "expected": result.expected,
            "detail": result.detail,
        }
        for result in report.results
    ]


def run_row_for_sql(report: QualityReport, *, git_sha: str = "") -> dict[str, Any]:
    """The single `quality_run` row this report belongs to."""
    counts = report.tally()
    return {
        "run_id": report.run_id,
        "checked_at": report.checked_at.isoformat(),
        "verdict": report.status,
        "passed": report.passed,
        "sources": list(report.sources),
        "checks_passed": counts["pass"],
        "checks_warned": counts["warn"],
        "checks_failed": counts["fail"],
        "checks_skipped": counts["skip"],
        "git_sha": git_sha,
    }


def summarise_history(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Per check, the range it has actually observed.

    What a threshold review reads. A check whose observed values have sat between
    13,100 and 13,400 for a month does not need a range of 9,000 to 20,000 any
    more, and this is the evidence for narrowing it.
    """
    seen: dict[str, list[float]] = {}
    for row in rows:
        if row.get("observed") is None:
            continue
        seen.setdefault(f"{row['scope']}/{row['check']}", []).append(float(row["observed"]))
    return {
        key: {
            "runs": float(len(values)),
            "low": min(values),
            "high": max(values),
            "mean": sum(values) / len(values),
        }
        for key, values in sorted(seen.items())
    }


__all__ = [
    "HISTORY",
    "JsonQualityStore",
    "QualityStore",
    "rows_for_sql",
    "run_row_for_sql",
    "summarise_history",
]
