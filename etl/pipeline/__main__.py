"""Command line entry point.

    python -m pipeline sources          what the registry knows about
    python -m pipeline run fake         run one adapter end to end
    python -m pipeline run fake --dry-run
    python -m pipeline check fake       run adapters, then the quality gate
    python -m pipeline plan             what tonight would pull, and why
    python -m pipeline nightly          plan, pull, gate, promote
    python -m pipeline history          what each check has measured over time
    python -m pipeline runs             the ledger: past nights and the current one
    python -m pipeline provenance       where every number came from, and when

The nightly job in .github/workflows/etl.yml calls this. Exit status 1 means the
run produced no usable data, which is the signal the job should fail on; a
`partial` or `stale` run exits 0 and says so in its manifest.

`check` is the CS-108 gate. It runs the adapters into one shared sink so the
cross-source checks can see all of them at once, applies the per-source
thresholds, and exits 1 if the night's load should not be scored.

`nightly` is CS-109 and is what the schedule actually invokes. It wraps `check`
in the three things a scheduled job needs and a manual one does not: a plan that
decides which sources are due before spending a minute on them, a ledger that
remembers the night, and a promotion that only happens if the gate passed. That
last one is what "a failed run leaves the previous dataset intact" means at the
level of the whole run rather than one source.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import census_acs, fake, get, names, openaq, specs
from pipeline.context import make_context
from pipeline.http import build_client
from pipeline.ledger import NightlyRun, RunLedger, carried, finish, outcome_from
from pipeline.metadata import PullMetadata
from pipeline.provenance import ProvenanceStore, payload, summarise, write_page
from pipeline.quality import (
    JsonQualityStore,
    QualityReport,
    run_gate,
    run_id_for,
    summarise_history,
)
from pipeline.runner import run_adapter
from pipeline.schedule import RunPlan, apply_outcomes, plan_run
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore

# The only place the pipeline reads the environment. Adapters ask for a secret
# by name from this table, through `ctx.credential`, and never touch os.environ
# themselves; an adapter that did would be one no test could run, one whose
# requirements stayed invisible until it failed in the middle of the night, and
# one that could put a key in a log line.
CREDENTIAL_ENV: Mapping[str, str] = {
    census_acs.CREDENTIAL: "CENSUS_API_KEY",
    openaq.API_KEY_CREDENTIAL: "OPENAQ_API_KEY",
}


def _credentials() -> dict[str, str]:
    return {
        name: value
        for name, variable in CREDENTIAL_ENV.items()
        if (value := os.environ.get(variable, "").strip())
    }

DEFAULT_STORE = Path("quality-runs")
# Kept apart from the quality store because the two have different lifetimes. A
# quality report is evidence about one night and is uploaded as an artifact; the
# ledger is the state the next night reads, and the workflow caches it.
DEFAULT_STATE = Path("pipeline-state")
# The generated block in this page is rewritten from the manifests by the nightly
# job. Relative to the repository root, which is where the job runs it from.
DEFAULT_PAGE = Path("docs/provenance.md")


def _list_sources() -> int:
    for spec in specs():
        provides = ", ".join(spec.provides) or "-"
        print(f"{spec.name:14} {spec.title}")
        print(f"{'':14} {spec.cadence} · {spec.native_geography} · indicators: {provides}")
    return 0


async def _run(
    name: str,
    *,
    dry_run: bool,
    pilot_state: str,
    sink: InMemorySink | None = None,
) -> PullMetadata:
    adapter = get(name)()
    # The reference adapter has no server behind it; everything else goes to the
    # real network.
    transport = fake.fixture_transport() if name == fake.FakeAirAdapter.spec.name else None
    async with build_client(adapter.policy, transport=transport) as client:
        ctx = make_context(
            source=adapter.spec.name,
            client=client,
            sink=sink if sink is not None else InMemorySink(),
            policy=adapter.policy,
            snapshots=InMemorySnapshotStore(),
            now=datetime.now(UTC),
            pilot_state=pilot_state,
            dry_run=dry_run,
            credentials=_credentials(),
        )
        return await run_adapter(adapter, ctx)


async def _check(
    sources: list[str], *, pilot_state: str, required: list[str]
) -> tuple[QualityReport, list[PullMetadata]]:
    """Run every named adapter into one sink, then gate the result.

    One sink rather than one per source, because half of CS-108 is the checks no
    adapter can make about itself: TRI matching ECHO, tract coverage, the hex
    grid agreeing between the sources that write to it.
    """
    sink = InMemorySink()
    manifests = []
    for name in sources:
        manifests.append(await _run(name, dry_run=False, pilot_state=pilot_state, sink=sink))

    report = run_gate(
        manifests=manifests,
        data=sink,
        now=datetime.now(UTC),
        required=required,
        adapters={name: get(name) for name in sources},
        pilot_state=pilot_state,
    )
    return report, manifests


async def _nightly(
    sources: list[str],
    *,
    pilot_state: str,
    required: list[str],
    state: Path,
    store: Path | None,
    force: list[str],
    force_all: bool,
    git_sha: str,
) -> tuple[NightlyRun, QualityReport, RunPlan, bool]:
    """One scheduled night: plan, pull what is due, gate, record, promote.

    The order is the point. Planning before pulling is what lets the run say "four
    of six are carried" on the run page before it spends the minutes proving it,
    and recording before promoting is what leaves a failed night in the ledger,
    visible, without letting it become the run the map serves.
    """
    ledger = RunLedger(state)
    now = datetime.now(UTC)
    run_id = ledger.unique_run_id(run_id_for(now))
    plan = plan_run(
        sources,
        now=now,
        last_success=ledger.last_success(),
        force=force,
        force_all=force_all,
    )

    sink = InMemorySink()
    manifests: list[PullMetadata] = []
    for name in plan.to_pull:
        manifests.append(await _run(name, dry_run=False, pilot_state=pilot_state, sink=sink))

    succeeded = {m.source for m in manifests if m.ok}
    plan = apply_outcomes(plan, succeeded=succeeded)

    # A source that was carried produced no manifest tonight, so requiring it
    # would fail the run for having obeyed its own cadence. `--require` means
    # "this source must have produced what it was asked for", and a carried
    # source was asked for nothing.
    #
    # A source that is required and is not in the plan at all is a different
    # thing entirely, and it is enforced. It was not carried by a cadence; it was
    # never considered, because it is unregistered or was excluded from the
    # source list. Waiving that would let a typo in `--require` read as a night
    # that went fine.
    pulling = set(plan.to_pull)
    considered = {p.source for p in plan.planned}
    waived = [name for name in required if name in considered and name not in pulling]
    enforced = [name for name in required if name not in waived]

    report = run_gate(
        manifests=manifests,
        data=sink,
        now=now,
        run_id=run_id,
        required=enforced,
        adapters={name: get(name) for name in plan.to_pull},
        pilot_state=pilot_state,
    )

    outcomes = []
    for planned in plan.planned:
        manifest = next((m for m in manifests if m.source == planned.source), None)
        if manifest is None:
            outcomes.append(carried(planned.source, planned.reason, action=planned.action))
        else:
            outcomes.append(outcome_from(manifest, action=planned.action, reason=planned.reason))

    notes = list(plan.notes)
    if waived:
        notes.append(
            f"{', '.join(waived)} was required but is carried tonight by its cadence, "
            "so the requirement was not enforced against this run."
        )

    # A night on which every source was carried loaded nothing, so its gate had
    # nothing to check and passed by having no opinion. Promoting it would
    # replace a run that scored data with one that did not, and would do it on
    # the strength of a green report made entirely of skips -- the exact shape
    # CS-108 exists to refuse. Nothing changed, so the run already current is
    # still the right one.
    idle = not plan.to_pull
    if idle:
        notes.append(
            "No source was due, so nothing was pulled and the run already current "
            "stays current. A night that loaded nothing does not become the night "
            "the map serves."
        )

    run = finish(
        NightlyRun(run_id=run_id, started_at=now, git_sha=git_sha),
        outcomes=outcomes,
        passed=report.passed,
        verdict=report.status,
        finished_at=datetime.now(UTC),
        notes=notes,
    )
    ledger.record(run)
    # Recorded whatever the gate decided, and whatever each pull's own status
    # was. A provenance history that drops the night a source could not be
    # reached tells the reader the data is more complete than it is.
    ProvenanceStore(state).record(manifests, run_id=run_id)
    promoted = False if idle else ledger.promote(run)

    if store is not None:
        JsonQualityStore(store).save(report, manifests)
    return run, report, plan, promoted


def _surface_plan(plan: RunPlan, *, github: bool) -> None:
    for planned in plan.planned:
        print(planned.line())
    print()
    print(plan.summary())
    if github:
        _append_summary(plan.markdown())


def _append_summary(markdown: str) -> None:
    """Write to the Actions step summary, which renders on the run page."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(markdown)


def _surface(report: QualityReport, *, github: bool) -> None:
    """Put the report where a person will see it, not only in the log.

    On GitHub Actions that means the step summary, which renders on the run page,
    and workflow annotations, which attach to the run itself. Elsewhere it means
    the terminal.
    """
    for line in (r.line() for r in report.results):
        print(line)
    print()
    print(report.summary())

    if not github:
        return
    for command in report.annotations():
        print(command)
    _append_summary(report.markdown())


def _provenance(state: Path, page: Path | None, *, as_json: bool, github: bool) -> int:
    """Publish where every number came from, optionally rewriting the page.

    Reads the recorded history rather than pulling anything, so it is safe to run
    at any time and is what the nightly job calls once its adapters have finished.
    """
    store = ProvenanceStore(state)
    pulls = store.latest()

    if as_json:
        print(json.dumps(payload(pulls), indent=2))
    else:
        print(summarise(pulls, now=datetime.now(UTC)))

    if page is None:
        return 0
    if not page.exists():
        print(f"no page at {page}; nothing to regenerate")
        return 1

    changed = write_page(page, pulls)
    # An unchanged page is the normal case on a night when nothing was due, so
    # it is reported rather than treated as a problem. The nightly job reads
    # this to decide whether there is anything to commit.
    print(f"{page}: {'updated' if changed else 'already up to date'}")
    if github:
        _github_output("provenance_changed", "true" if changed else "false")
    return 0


def _github_output(name: str, value: str) -> None:
    """Set a workflow output, so a later step can branch on it."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _runs(state: Path, limit: int) -> int:
    """The ledger, newest last, with the served run marked.

    Reads rather than runs anything, so it is what a person opens after a failed
    night to see whether the map is still on the run before it.
    """
    ledger = RunLedger(state)
    history = ledger.runs()
    if not history:
        print(f"no runs recorded under {state}; run `python -m pipeline nightly` first")
        return 0
    current = ledger.current()
    current_id = current.run_id if current else None
    for run in history[-limit:]:
        marker = " <- current" if run.run_id == current_id else ""
        print(f"{run.summary()}{marker}")
        for outcome in run.sources:
            detail = f"{outcome.status or outcome.action}"
            if outcome.vintage:
                detail += f" {outcome.vintage}, {outcome.records} records"
            print(f"    {outcome.source:14} {detail}")
    if current_id is None:
        print()
        print("No run has been promoted, so nothing is being served yet.")
    return 0


def _history(root: Path, check: str | None) -> int:
    store = JsonQualityStore(root)
    rows = store.history(check)
    if not rows:
        print(f"no history under {root}; run `python -m pipeline check` first")
        return 0
    print(f"{'check':46} {'runs':>5} {'low':>14} {'high':>14} {'mean':>14}")
    for key, stats in summarise_history(rows).items():
        print(
            f"{key:46} {stats['runs']:>5.0f} {stats['low']:>14.4g} "
            f"{stats['high']:>14.4g} {stats['mean']:>14.4g}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    parser.add_argument("--log-level", default="info")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list registered data sources")

    run = sub.add_parser("run", help="run one adapter")
    run.add_argument("source")
    run.add_argument("--dry-run", action="store_true", help="fetch and normalize, write nothing")
    run.add_argument("--pilot-state", default="LA")
    run.add_argument("--json", action="store_true", help="print the manifest as JSON")

    check = sub.add_parser("check", help="run adapters and apply the data quality gate")
    check.add_argument(
        "sources",
        nargs="*",
        help="sources to run; default is every registered source",
    )
    check.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="SOURCE",
        help="a source this run must produce; a skipped check on it becomes a failure",
    )
    check.add_argument("--pilot-state", default="LA")
    check.add_argument("--store", type=Path, default=DEFAULT_STORE, help="where to keep results")
    check.add_argument("--no-store", action="store_true", help="do not persist the report")
    check.add_argument("--json", action="store_true", help="print the report as JSON")
    check.add_argument(
        "--github",
        action="store_true",
        default=bool(os.environ.get("GITHUB_ACTIONS")),
        help="emit workflow annotations and write the step summary",
    )

    for name, help_text in (
        ("plan", "show what tonight would pull, and why, without pulling it"),
        ("nightly", "the scheduled run: plan, pull what is due, gate, record, promote"),
    ):
        job = sub.add_parser(name, help=help_text)
        job.add_argument(
            "sources",
            nargs="*",
            help="sources to consider; default is every registered source",
        )
        job.add_argument("--state", type=Path, default=DEFAULT_STATE, help="where the ledger lives")
        job.add_argument(
            "--force",
            action="append",
            default=[],
            metavar="SOURCE",
            help="pull this source regardless of its cadence; repeatable",
        )
        job.add_argument(
            "--all",
            dest="force_all",
            action="store_true",
            help="pull every source, ignoring cadence",
        )
        job.add_argument("--pilot-state", default="LA")
        job.add_argument(
            "--github",
            action="store_true",
            default=bool(os.environ.get("GITHUB_ACTIONS")),
            help="emit workflow annotations and write the step summary",
        )
        if name == "nightly":
            job.add_argument(
                "--require",
                action="append",
                default=[],
                metavar="SOURCE",
                help="a source this run must produce when its cadence says it is due",
            )
            job.add_argument("--store", type=Path, default=DEFAULT_STORE)
            job.add_argument("--no-store", action="store_true", help="do not persist the report")
            job.add_argument("--json", action="store_true", help="print the report as JSON")
            job.add_argument(
                "--git-sha",
                default=os.environ.get("GITHUB_SHA", ""),
                help="the commit this run implemented, recorded in the ledger",
            )

    provenance = sub.add_parser(
        "provenance", help="where every number came from, and regenerate the page"
    )
    provenance.add_argument("--state", type=Path, default=DEFAULT_STATE)
    provenance.add_argument(
        "--page",
        type=Path,
        default=None,
        help=f"rewrite the generated block in this page, e.g. {DEFAULT_PAGE}",
    )
    provenance.add_argument("--json", action="store_true", help="print the payload the API serves")
    provenance.add_argument(
        "--github",
        action="store_true",
        default=bool(os.environ.get("GITHUB_ACTIONS")),
        help="set the provenance_changed workflow output",
    )

    runs = sub.add_parser("runs", help="the ledger: past nights and the one being served")
    runs.add_argument("--state", type=Path, default=DEFAULT_STATE)
    runs.add_argument("--limit", type=int, default=10, help="how many recent runs to show")

    history = sub.add_parser("history", help="what each check has measured across runs")
    history.add_argument("--store", type=Path, default=DEFAULT_STORE)
    history.add_argument("--check", default=None, help="restrict to one check id")

    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    if args.command == "sources":
        return _list_sources()

    if args.command == "history":
        return _history(args.store, args.check)

    if args.command == "runs":
        return _runs(args.state, args.limit)

    if args.command == "provenance":
        return _provenance(args.state, args.page, as_json=args.json, github=args.github)

    if args.command == "plan":
        plan = plan_run(
            args.sources or list(names()),
            now=datetime.now(UTC),
            last_success=RunLedger(args.state).last_success(),
            force=args.force,
            force_all=args.force_all,
        )
        _surface_plan(plan, github=args.github)
        return 0

    if args.command == "nightly":
        night, report, plan, promoted = asyncio.run(
            _nightly(
                args.sources or list(names()),
                pilot_state=args.pilot_state,
                required=args.require,
                state=args.state,
                store=None if args.no_store else args.store,
                force=args.force,
                force_all=args.force_all,
                git_sha=args.git_sha,
            )
        )
        if args.json:
            print(report.model_dump_json(indent=2))
        else:
            _surface_plan(plan, github=args.github)
            print()
            _surface(report, github=args.github)
        print()
        print(night.summary())

        served = RunLedger(args.state).current()
        still = f"still serving {served.run_id}" if served else "nothing has been promoted yet"
        if promoted:
            print(f"promoted {night.run_id}: this is the run the map serves")
        elif not plan.to_pull:
            # Not a failure. Every source obeyed its cadence and there was
            # nothing to load, so the dataset is unchanged and so is what serves
            # it. Saying this in the same words as a failed gate would train a
            # reader to ignore both.
            print(f"nothing was due tonight, so no run was promoted; {still}")
        else:
            print(f"not promoted; the gate said {report.status} and {still}")
            if args.github:
                print(
                    "::error title=Nightly ETL::"
                    f"run {night.run_id} failed its quality gate and was not promoted; {still}"
                )
        return 0 if night.succeeded else 1

    if args.command == "check":
        chosen = args.sources or list(names())
        report, manifests = asyncio.run(
            _check(chosen, pilot_state=args.pilot_state, required=args.require)
        )
        if not args.no_store:
            JsonQualityStore(args.store).save(report, manifests)
        if args.json:
            print(report.model_dump_json(indent=2))
        else:
            _surface(report, github=args.github)
        return 0 if report.passed else 1

    metadata = asyncio.run(_run(args.source, dry_run=args.dry_run, pilot_state=args.pilot_state))
    if args.json:
        print(metadata.model_dump_json(indent=2))
    else:
        print(metadata.summary())
        print(metadata.provenance_row())
        for note in metadata.notes:
            print(f"  note: {note}")
    return 0 if metadata.ok else 1


if __name__ == "__main__":
    sys.exit(main())
