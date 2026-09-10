"""Command line entry point.

    python -m pipeline sources          what the registry knows about
    python -m pipeline run fake         run one adapter end to end
    python -m pipeline run fake --dry-run

The nightly job in .github/workflows/etl.yml calls this. Exit status 1 means the
run produced no usable data, which is the signal the job should fail on; a
`partial` or `stale` run exits 0 and says so in its manifest.
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime

from pipeline.adapters import fake, get, specs
from pipeline.context import make_context
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore


def _list_sources() -> int:
    for spec in specs():
        provides = ", ".join(spec.provides) or "-"
        print(f"{spec.name:14} {spec.title}")
        print(f"{'':14} {spec.cadence} · {spec.native_geography} · indicators: {provides}")
    return 0


async def _run(name: str, *, dry_run: bool, pilot_state: str) -> PullMetadata:
    adapter = get(name)()
    # The reference adapter has no server behind it; everything else goes to the
    # real network.
    transport = fake.fixture_transport() if name == fake.FakeAirAdapter.spec.name else None
    async with build_client(adapter.policy, transport=transport) as client:
        ctx = make_context(
            source=adapter.spec.name,
            client=client,
            sink=InMemorySink(),
            policy=adapter.policy,
            snapshots=InMemorySnapshotStore(),
            now=datetime.now(UTC),
            pilot_state=pilot_state,
            dry_run=dry_run,
        )
        return await run_adapter(adapter, ctx)


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

    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")

    if args.command == "sources":
        return _list_sources()

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
