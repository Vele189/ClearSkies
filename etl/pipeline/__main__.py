"""Command line entry point.

    python -m pipeline sources          what the registry knows about
    python -m pipeline run fake         run one adapter end to end
    python -m pipeline run fake --dry-run
    python -m pipeline check fake       run adapters, then the quality gate
    python -m pipeline history          what each check has measured over time

The nightly job in .github/workflows/etl.yml calls this. Exit status 1 means the
run produced no usable data, which is the signal the job should fail on; a
`partial` or `stale` run exits 0 and says so in its manifest.

`check` is the CS-108 gate. It runs the adapters into one shared sink so the
cross-source checks can see all of them at once, applies the per-source
thresholds, and exits 1 if the night's load should not be scored. That exit
status is what keeps a bad load from becoming the current run.
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline.adapters import fake, get, names, specs
from pipeline.context import make_context
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.quality import JsonQualityStore, QualityReport, run_gate, summarise_history
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore

DEFAULT_STORE = Path("quality-runs")


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
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report.markdown())


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

    history = sub.add_parser("history", help="what each check has measured across runs")
    history.add_argument("--store", type=Path, default=DEFAULT_STORE)
    history.add_argument("--check", default=None, help="restrict to one check id")

    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    if args.command == "sources":
        return _list_sources()

    if args.command == "history":
        return _history(args.store, args.check)

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
