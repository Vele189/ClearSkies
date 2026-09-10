"""Everything an adapter is handed for one run.

The context is the only channel through which an adapter touches the outside
world: HTTP through `http`, the database through `sink`, the clock through `now`.
Nothing in an adapter should call `datetime.now()`, open a socket, or read an
environment variable directly. That is what makes an adapter testable against a
fake source, and what keeps a single pull timestamp on every record and on the
manifest.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from pipeline.http import HttpFetcher
from pipeline.policy import SourcePolicy
from pipeline.sinks import Sink
from pipeline.snapshots import SnapshotStore


@dataclass(frozen=True, slots=True)
class RunContext:
    source: str
    # One timestamp for the whole run. Two records from the same pull that
    # disagree about when they were pulled make the recency term meaningless.
    now: datetime
    http: HttpFetcher
    sink: Sink
    policy: SourcePolicy
    pilot_state: str = "LA"
    dry_run: bool = False
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("pipeline"))


def make_context(
    *,
    source: str,
    client: httpx.AsyncClient,
    sink: Sink,
    policy: SourcePolicy,
    snapshots: SnapshotStore | None = None,
    now: datetime | None = None,
    pilot_state: str = "LA",
    dry_run: bool = False,
) -> RunContext:
    """Wire a context, deriving the fetcher from the adapter's own policy."""
    moment = now if now is not None else datetime.now(UTC)
    fetcher = HttpFetcher(
        client,
        source=source,
        policy=policy,
        snapshots=snapshots,
    )
    return RunContext(
        source=source,
        now=moment,
        http=fetcher,
        sink=sink,
        policy=policy,
        pilot_state=pilot_state,
        dry_run=dry_run,
        log=logging.getLogger(f"pipeline.{source}"),
    )
