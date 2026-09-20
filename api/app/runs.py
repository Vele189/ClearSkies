"""Which run the API serves, and which release of each source it read.

`pipeline_run.is_current` names exactly one run, enforced by a partial unique
index in migration 0002. Everything the API reads is keyed by that run id, so
a hex detail assembled from two different runs would be a score explained by
inputs that did not produce it. One lookup, reused by every reader, is what
stops that.

The vintage map is the answer to "what is this number citing". Migration 0002
says so directly: `pipeline_run_source` records which snapshot of each source a
run actually read, and its comment names this payload as the consumer.

Both are constant for the life of a run and a run is produced nightly, so they
are cached briefly rather than fetched on every drill-down. The cost of the
cache is that a freshly promoted run takes up to `CACHE_TTL_S` to appear, which
against a nightly cadence is not a cost at all.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import asyncpg

from app.indicators import SOURCE_NAMES

log = logging.getLogger(__name__)

CACHE_TTL_S = 30.0

CURRENT = """
    SELECT run_id, methodology_version, started_at, finished_at, scored_hexes
      FROM pipeline_run
     WHERE is_current
"""

# Newest snapshot per source, in case a run read two of one source. ORDER BY
# with DISTINCT ON is what makes "newest" well defined rather than whichever
# row the planner happened to return first.
VINTAGES = """
    SELECT DISTINCT ON (s.source)
           s.source, s.vintage, s.vintage_end
      FROM pipeline_run_source rs
      JOIN source_snapshot s ON s.snapshot_id = rs.snapshot_id
     WHERE rs.run_id = $1
     ORDER BY s.source, s.vintage_end DESC
"""


@dataclass(frozen=True)
class RunContext:
    """The run the API serves, and what it read."""

    run_id: int
    methodology_version: str
    finished_at: datetime | None
    scored_hexes: int | None
    # Keyed by the source names the indicator registry uses, so a caller
    # holding an IndicatorValue can look up that indicator's vintage directly.
    data_vintage: dict[str, str] = field(default_factory=dict)
    # Last date each source's data describes, which is a different question
    # from its release identifier and the one the recency term asks.
    vintage_end: dict[str, date] = field(default_factory=dict)


_cached: RunContext | None = None
_cached_at: float = 0.0
_lock = asyncio.Lock()


def _fresh(now: float) -> RunContext | None:
    if _cached is not None and now - _cached_at < CACHE_TTL_S:
        return _cached
    return None


async def current(conn: Any) -> RunContext | None:
    """The current run, or None when no run has been promoted yet.

    None is not an error here. It is the ordinary state of a deployment whose
    pipeline has not finished a run, and the caller turns it into a 503 that
    says so.
    """
    now = time.monotonic()
    cached = _fresh(now)
    if cached is not None:
        return cached

    async with _lock:
        # Another waiter may have filled it while this one held at the lock.
        cached = _fresh(time.monotonic())
        if cached is not None:
            return cached

        context = await _load(conn)

        global _cached, _cached_at
        _cached = context
        _cached_at = time.monotonic()
        return context


async def _load(conn: Any) -> RunContext | None:
    try:
        row = await conn.fetchrow(CURRENT)
    except asyncpg.UndefinedTableError:
        # A database migrated partway: 0002 has not landed, so no run can
        # exist. Indistinguishable, from here, from a database with no run.
        log.warning("pipeline_run is missing; treating the deployment as unscored")
        return None

    if row is None:
        return None

    vintages = await conn.fetch(VINTAGES, row["run_id"])

    data_vintage: dict[str, str] = {}
    vintage_end: dict[str, date] = {}
    for v in vintages:
        name = SOURCE_NAMES.get(v["source"])
        if name is None:
            # A source the registry does not name. Published under its raw key
            # rather than dropped: an uncitable vintage is still better than a
            # silently missing one, and the log line is how it gets fixed.
            log.warning(
                "source has no display name in the indicator registry",
                extra={"source": v["source"]},
            )
            name = v["source"]
        data_vintage[name] = v["vintage"]
        vintage_end[name] = v["vintage_end"]

    return RunContext(
        run_id=row["run_id"],
        methodology_version=row["methodology_version"],
        finished_at=row["finished_at"],
        scored_hexes=row["scored_hexes"],
        data_vintage=data_vintage,
        vintage_end=vintage_end,
    )


def reset_cache() -> None:
    """Drop the cached run. For tests, and for a caller that has just promoted a run."""
    global _cached, _cached_at
    _cached = None
    _cached_at = 0.0
