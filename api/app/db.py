"""Connection pool lifecycle.

The pool is deliberately optional. A missing database degrades /health rather
than preventing the process from starting, so a Railway deploy that comes up
before the database is reachable reports the problem instead of crash-looping.

Optional has to mean "not yet", not "never". The database is a Neon branch that
scales to zero, so the first connection after an idle period wakes a compute and
can time out; before this module retried, a process that started during a cold
start stayed degraded until somebody redeployed it, answering 503 to every
request with a healthy database on the other end of the socket. So `pool()`
tries again, no more often than `RETRY_AFTER_S`, which keeps a genuinely
unreachable database from being dialled once per request.
"""

import asyncio
import logging
import time

import asyncpg

from app.config import get_settings

log = logging.getLogger(__name__)

# How long to wait before trying to build the pool again. Long enough that a
# database that is down is dialled rarely, short enough that a cold start costs
# one request rather than a deploy.
RETRY_AFTER_S = 10.0

_pool: asyncpg.Pool | None = None
_last_attempt: float = 0.0
_lock = asyncio.Lock()


async def _create() -> asyncpg.Pool | None:
    global _last_attempt
    settings = get_settings()
    _last_attempt = time.monotonic()
    try:
        created: asyncpg.Pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            timeout=settings.db_connect_timeout,
            command_timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - startup must not fail on a cold database
        log.warning(
            "database unavailable: %s",
            exc,
            extra={"database": "unavailable", "error_type": type(exc).__name__},
        )
        return None
    log.info("database pool established", extra={"database": "connected"})
    return created


async def connect() -> None:
    global _pool
    _pool = await _create()


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def pool() -> asyncpg.Pool | None:
    """The pool, building it if startup could not and enough time has passed.

    None still means "no database right now", which every caller turns into a
    503 naming /health. What it no longer means is "no database for the life of
    this process".
    """
    if _pool is not None:
        return _pool
    if time.monotonic() - _last_attempt < RETRY_AFTER_S:
        return None
    async with _lock:
        return await _retry()


async def _retry() -> asyncpg.Pool | None:
    """One attempt, under the lock, so concurrent requests build one pool.

    Both conditions are checked again here rather than trusted from the caller:
    another request may have built the pool, or made its own failed attempt,
    while this one waited at the lock.
    """
    global _pool
    if _pool is not None:
        return _pool
    if time.monotonic() - _last_attempt < RETRY_AFTER_S:
        return None
    _pool = await _create()
    return _pool


def reset_for_tests() -> None:
    """Forget the last attempt, so a test does not wait out the cooldown."""
    global _last_attempt
    _last_attempt = 0.0
