"""The ingestion package's connection to Postgres.

Separate from the API's `app/db.py` on purpose. The API holds a long-lived pool
and degrades to a database-less `/health` when the database is missing, because
a deploy that cannot reach Postgres should still be able to say so. A pipeline
run has the opposite requirement: it is a batch job with one transaction, and a
database it cannot reach is a failed run, not a degraded one.

`DATABASE_URL` is read from the environment rather than from a settings object,
on the same terms as the credentials in `__main__.py`: this package has no
dotenv loader and nothing here should acquire one, so whatever runs the job is
responsible for putting the variable in the environment.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

ENV_VAR = "DATABASE_URL"


class DatabaseUnavailable(RuntimeError):
    """Raised when the job has no database to write to."""


def database_url() -> str:
    url = os.environ.get(ENV_VAR, "").strip()
    if not url:
        raise DatabaseUnavailable(
            f"{ENV_VAR} is not set, and this command reads or writes Postgres. "
            "The commands that can work without one say so in their own help: "
            "`run --dry-run` fetches and normalizes without a database."
        )
    return url


@asynccontextmanager
async def connection(url: str | None = None) -> AsyncIterator[asyncpg.Connection]:
    """One connection for one job.

    No pool: a run writes from a single task inside a single transaction, and a
    pool would only add a way for two statements to end up on different
    connections and therefore in different transactions.
    """
    target = url if url is not None else database_url()
    try:
        conn = await asyncpg.connect(target, command_timeout=600)
    except (OSError, asyncpg.PostgresError) as exc:
        raise DatabaseUnavailable(f"could not connect to the database: {exc}") from exc
    try:
        yield conn
    finally:
        await conn.close()
