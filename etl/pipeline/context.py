"""Everything an adapter is handed for one run.

The context is the only channel through which an adapter touches the outside
world: HTTP through `http`, the database through `sink`, the clock through `now`,
and credentials through `credential`. Nothing in an adapter should call
`datetime.now()`, open a socket, or read an environment variable directly. That
is what makes an adapter testable against a fake source, and what keeps a single
pull timestamp on every record and on the manifest.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

import httpx

from pipeline.errors import PermanentSourceError
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
    # Credentials the run was started with, under the names adapters ask for.
    # Filled at the command line boundary, because an adapter that reads
    # os.environ itself is an adapter a test cannot run without arranging the
    # environment, and one whose requirements are invisible until it fails at
    # three in the morning. An adapter that needs a key it was not given should
    # raise PermanentSourceError saying which name it looked for.
    credentials: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("pipeline"))

    def credential(self, name: str) -> str:
        """A secret this source cannot run without.

        A missing key is a `PermanentSourceError` rather than a crash, because
        it is the same situation as an upstream that has withdrawn access: the
        runner records a failed pull with a legible reason, falls back to the
        last good snapshot where one exists, and leaves the other sources in
        the nightly job alone.
        """
        value = self.credentials.get(name, "").strip()
        if not value:
            raise PermanentSourceError(
                f"{self.source}: no {name} was configured; this source requires one"
            )
        return value


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
    credentials: Mapping[str, str] | None = None,
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
        credentials=MappingProxyType(dict(credentials or {})),
        log=logging.getLogger(f"pipeline.{source}"),
    )
