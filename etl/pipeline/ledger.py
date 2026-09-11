"""The record of a whole night, and the one bit that decides what gets served.

`run_adapter` makes a pull atomic: a source that fails halfway leaves last
night's rows in place. `run_gate` judges the night. Neither makes the *night*
atomic, and that gap is the last acceptance criterion of CS-109: a failed run has
to leave the previous dataset intact as a whole, not merely source by source.

The schema already says how. `pipeline_run` in migration 0002 carries a status, an
`is_current` flag, a constraint that only a succeeded run may hold it, and a
partial unique index that permits exactly one holder. Serving reads the current
run. So "a bad night does not become the current one" is not a rollback: every
source's transaction committed hours ago and unwinding four good sources to
punish a fifth would be worse than saying so. It is a promotion that does not
happen. The rows are there, unreferenced, and the map keeps serving the run that
last passed its gate.

This module is that model, file-backed. The Postgres sink does not exist yet, and
a nightly job whose only record of itself lives in the database it is loading is
a job that cannot report the night the database was the thing that broke. So the
ledger writes files, and `row_for_sql` and `source_rows_for_sql` emit exactly the
shapes `pipeline_run` and `pipeline_run_source` take, kept beside the model they
mirror so the two cannot drift into describing a run differently.

It also answers the question `pipeline.schedule` asks: when did this source last
load cleanly? A cadence counts from the last success, so somebody has to remember
it across runs. On a GitHub runner nothing survives a job by default, which is
why the workflow caches this directory. Losing it costs a redundant pull, which
is the harmless direction.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from pipeline.metadata import Frozen, PullMetadata, UtcDatetime

# Mirrors pipeline_run.status in migration 0002, including the constraint that a
# finished run has a finish time and a running one does not.
RunStatus = Literal["running", "succeeded", "failed"]

# Must match the version header in docs/methodology.md. Restated rather than read
# because `etl` ships without the docs tree; `test_ledger.py` reads the document
# off disk and fails if the two disagree, the same guard CS-108 uses to keep the
# indicator groups in step with the API.
METHODOLOGY_VERSION = "0.1.3"

RUNS = "runs.jsonl"
CURRENT = "current.json"


class SourceOutcome(Frozen):
    """What one source contributed to one night.

    `action` is the planner's word for why the source is in this state, and it is
    the field that keeps a carried source from reading as a missing one. A source
    that was not due did not fail; it did not run, and last night's rows are
    still the right rows.
    """

    source: str
    # pull / carry / blocked, from pipeline.schedule.
    action: str
    # The adapter's own verdict, absent when the source was carried or blocked.
    status: str | None = None
    vintage: str | None = None
    records: int = 0
    pulled_at: UtcDatetime | None = None
    reason: str = ""

    @property
    def loaded(self) -> bool:
        """Whether this night put rows in for this source."""
        return self.action == "pull" and self.status in ("ok", "partial", "stale")


class NightlyRun(Frozen):
    """One night, start to verdict."""

    run_id: str
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    status: RunStatus = "running"
    git_sha: str = ""
    methodology_version: str = METHODOLOGY_VERSION
    sources: tuple[SourceOutcome, ...] = ()
    quality_verdict: str | None = Field(
        default=None, description="The gate's worst status: pass, warn, fail or skip"
    )
    scored_hexes: int | None = None
    notes: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def outcome_for(self, source: str) -> SourceOutcome | None:
        return next((s for s in self.sources if s.source == source), None)

    def summary(self) -> str:
        pulled = sum(1 for s in self.sources if s.action == "pull")
        carried = sum(1 for s in self.sources if s.action == "carry")
        return (
            f"run {self.run_id}: {self.status}, {pulled} pulled, {carried} carried, "
            f"gate {self.quality_verdict or 'not run'}"
        )


class RunLedger:
    """Every night this pipeline has run, and which one is being served.

    Layout::

        <root>/runs.jsonl     one line per run, appended, oldest first
        <root>/current.json   the run the map serves

    Append-only for the same reason the quality history is: the value of the file
    is that it is longer than the run that wrote it. A cadence needs a date from
    last week and a threshold review needs a month.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    # ---- writing -------------------------------------------------------

    def record(self, run: NightlyRun) -> None:
        """Append a finished run. Does not promote it; see `promote`."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / RUNS).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run.model_dump(mode="json"), sort_keys=True) + "\n")

    def promote(self, run: NightlyRun) -> bool:
        """Make this the run the map serves. Returns whether it was promoted.

        Refuses anything that did not succeed, which is the whole point: this is
        `pipeline_run_current_must_have_succeeded` from migration 0002, enforced
        here so the file-backed ledger cannot express a state the table would
        reject. A refusal is not an error, it is the failed night behaving
        correctly, so the caller gets `False` rather than an exception.
        """
        if not run.succeeded:
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / CURRENT).write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return True

    # ---- reading -------------------------------------------------------

    def runs(self) -> list[NightlyRun]:
        path = self.root / RUNS
        if not path.exists():
            return []
        return [
            NightlyRun.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def unique_run_id(self, base: str) -> str:
        """`base`, or `base-2`, `base-3`... if the ledger already holds it.

        Run ids are timestamps to the second, which reads well and is unique for
        a job that runs once a night. It is not unique for two `workflow_dispatch`
        clicks in the same second, for a test, or for a re-run triggered by hand
        while the scheduled one is still finishing. A ledger keyed on a duplicate
        id cannot say which run is current, and the quality store would file two
        reports in one directory, so the collision is resolved here rather than
        left to whoever reads the file later.
        """
        taken = {run.run_id for run in self.runs()}
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def current(self) -> NightlyRun | None:
        """The run being served, or None before any run has passed its gate."""
        path = self.root / CURRENT
        if not path.exists():
            return None
        return NightlyRun.model_validate_json(path.read_text(encoding="utf-8"))

    def last_success(self) -> dict[str, datetime]:
        """When each source last loaded cleanly, which is what a cadence counts from.

        Read from every recorded run rather than only from promoted ones. A source
        that loaded fine on a night some *other* source failed was still pulled,
        and making it re-pull because of a neighbour's failure would turn one bad
        source into a nightly full refresh of all six.

        `stale` counts as a success on purpose. A stale pull served the last good
        snapshot because upstream was down; the recency term already records that
        (methodology section 6), and re-pulling every night against an upstream
        that is still down buys nothing but requests.
        """
        seen: dict[str, datetime] = {}
        for run in self.runs():
            for outcome in run.sources:
                if not outcome.loaded or outcome.pulled_at is None:
                    continue
                current = seen.get(outcome.source)
                if current is None or outcome.pulled_at > current:
                    seen[outcome.source] = outcome.pulled_at
        return seen


def outcome_from(
    metadata: PullMetadata, *, action: str = "pull", reason: str = ""
) -> SourceOutcome:
    """The ledger's view of a manifest the runner produced."""
    return SourceOutcome(
        source=metadata.source,
        action=action,
        status=metadata.status,
        vintage=metadata.vintage,
        records=metadata.record_count,
        pulled_at=metadata.pulled_at,
        reason=reason,
    )


def carried(source: str, reason: str, *, action: str = "carry") -> SourceOutcome:
    """A source this night deliberately did not pull."""
    return SourceOutcome(source=source, action=action, reason=reason)


def row_for_sql(run: NightlyRun) -> dict[str, Any]:
    """The `pipeline_run` row this night becomes once the Postgres sink lands."""
    return {
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "git_sha": run.git_sha,
        "methodology_version": run.methodology_version,
        "scored_hexes": run.scored_hexes,
        "notes": "; ".join(run.notes) or None,
    }


def source_rows_for_sql(run: NightlyRun) -> list[dict[str, Any]]:
    """One row per source this night read, for `pipeline_run_source`.

    The table joins through `source_snapshot`, which the Postgres sink assigns
    when it writes the snapshot. Until then the vintage and the pull timestamp
    are what identifies the release, which is exactly what the detail panel's
    `data_vintage` map needs.
    """
    return [
        {
            "run_id": run.run_id,
            "source": outcome.source,
            "vintage": outcome.vintage,
            "pulled_at": outcome.pulled_at.isoformat() if outcome.pulled_at else None,
            "records": outcome.records,
            "action": outcome.action,
            "status": outcome.status,
        }
        for outcome in run.sources
    ]


def finish(
    run: NightlyRun,
    *,
    outcomes: Sequence[SourceOutcome],
    passed: bool,
    verdict: str,
    finished_at: datetime,
    notes: Iterable[str] = (),
) -> NightlyRun:
    """Close a run with the night's outcomes and the gate's verdict."""
    return run.model_copy(
        update={
            "finished_at": finished_at,
            "status": "succeeded" if passed else "failed",
            "sources": tuple(outcomes),
            "quality_verdict": verdict,
            "notes": tuple(notes),
        }
    )


__all__ = [
    "CURRENT",
    "METHODOLOGY_VERSION",
    "RUNS",
    "NightlyRun",
    "RunLedger",
    "RunStatus",
    "SourceOutcome",
    "carried",
    "finish",
    "outcome_from",
    "row_for_sql",
    "source_rows_for_sql",
]
