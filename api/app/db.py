"""Connection pool lifecycle.

The pool is deliberately optional. A missing database degrades /health rather
than preventing the process from starting, so a Railway deploy that comes up
before the database is reachable reports the problem instead of crash-looping.
"""

import logging

import asyncpg

from app.config import get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def connect() -> None:
    global _pool
    settings = get_settings()
    try:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            timeout=settings.db_connect_timeout,
            command_timeout=30,
        )
        log.info("database pool established")
    except Exception as exc:  # noqa: BLE001 - startup must not fail on a cold database
        _pool = None
        log.warning("database unavailable at startup: %s", exc)


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool | None:
    return _pool
