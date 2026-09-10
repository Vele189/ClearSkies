"""Forward-only SQL migrations.

Every schema change lands as a numbered .sql file in ``api/migrations`` and is
applied by this runner. Nothing else may create, alter, or drop anything in the
database. A schema that exists because somebody ran psql once is a schema
nobody can rebuild, and this project's whole claim is that its numbers are
reproducible from public inputs.

Why plain SQL rather than Alembic. Alembic earns its keep by diffing ORM models,
and there are none here: the API talks to Postgres through raw asyncpg. Every
revision would be ``op.execute()`` wrapping exactly the SQL in these files, with
SQLAlchemy carried as a dependency to do the wrapping. The schema is also mostly
PostGIS geometry, H3 cells, and pgvector columns, which is where a Python DSL
reads worst and a reviewer most wants to see the literal DDL.

Why the files live under ``api/`` rather than ``infra/``. Railway builds the api
service with Root Directory ``/api``, so nothing outside that directory reaches
the image. Keeping migrations here is what lets a deploy run
``python -m app.migrate up`` against the same DATABASE_URL the API already has.

Usage::

    python -m app.migrate status
    python -m app.migrate up
    python -m app.migrate down --to 0007
    python -m app.migrate verify
    python -m app.migrate new add_facility_naics
"""

import argparse
import asyncio
import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# One fixed key, so two deploys racing to migrate queue up instead of
# interleaving half-applied schemas.
LOCK_KEY = 4121906006

FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<slug>[a-z0-9_]+)\.(?P<direction>up|down)\.sql$")
SLUG = re.compile(r"^[a-z][a-z0-9_]*$")

# Postgres refuses CREATE INDEX CONCURRENTLY and a few other statements inside a
# transaction block. A file opening with this marker is run outside one, and must
# hold exactly one statement: without a transaction there is nothing to roll back,
# so a failure part way through a multi-statement file would leave the database in
# a state the ledger does not describe.
NO_TRANSACTION = "-- migrate:no-transaction"

LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     text        PRIMARY KEY,
    slug        text        NOT NULL,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    duration_ms integer     NOT NULL
)
"""

RECORD = """
INSERT INTO schema_migration (version, slug, checksum, duration_ms)
VALUES ($1, $2, $3, $4)
"""

UP_TEMPLATE = """\
-- {version}: {title}
--
-- Why this change is needed, and anything a reader would otherwise have to
-- reconstruct from the DDL. Reference the methodology section it implements.

"""

DOWN_TEMPLATE = """\
-- Reverts {version}_{slug}.
--
-- Down migrations exist so a review branch can be unwound locally. Production
-- rolls forward: to undo a shipped migration, write the next one.

"""


class MigrationError(RuntimeError):
    """A problem with the migration set or the ledger, not with the SQL itself."""


@dataclass(frozen=True)
class Migration:
    version: str
    slug: str
    up_path: Path
    down_path: Path | None

    @property
    def name(self) -> str:
        return f"{self.version}_{self.slug}"

    @property
    def sql(self) -> str:
        return self.up_path.read_text()

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.up_path.read_bytes()).hexdigest()

    @property
    def reversible(self) -> bool:
        return self.down_path is not None

    @property
    def no_transaction(self) -> bool:
        return self.sql.lstrip().startswith(NO_TRANSACTION)


def discover(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Read the migration set off disk, rejecting anything ambiguous.

    Strictness here is deliberate. A file the runner cannot classify is far more
    likely to be a migration somebody expected to run than a stray note, and
    silently skipping it would produce two databases that disagree.
    """
    if not directory.is_dir():
        raise MigrationError(f"No migrations directory at {directory}")

    ups: dict[str, Path] = {}
    downs: dict[str, Path] = {}
    slugs: dict[str, str] = {}

    for path in sorted(directory.iterdir()):
        if path.is_dir() or path.name.startswith("."):
            continue
        matched = FILENAME.match(path.name)
        if matched is None:
            raise MigrationError(
                f"{path.name!r} is not named NNNN_slug.up.sql or NNNN_slug.down.sql"
            )
        version = matched["version"]
        slug = matched["slug"]
        side = ups if matched["direction"] == "up" else downs
        if version in side:
            raise MigrationError(
                f"Two migrations numbered {version}: {side[version].name} and {path.name}"
            )
        side[version] = path
        if slugs.setdefault(version, slug) != slug:
            raise MigrationError(
                f"Migration {version} has two slugs, {slugs[version]!r} and {slug!r}"
            )

    orphaned = sorted(set(downs) - set(ups))
    if orphaned:
        raise MigrationError(f"Down migrations with no up migration: {', '.join(orphaned)}")

    return tuple(
        Migration(version, slugs[version], ups[version], downs.get(version))
        for version in sorted(ups)
    )


def drift(migrations: tuple[Migration, ...], applied: dict[str, str]) -> list[str]:
    """Ways the ledger and the files on disk have stopped agreeing."""
    known = {m.version: m for m in migrations}
    problems: list[str] = []
    for version in sorted(applied):
        migration = known.get(version)
        if migration is None:
            problems.append(f"{version} is recorded as applied but its file is gone")
        elif migration.checksum != applied[version]:
            problems.append(
                f"{migration.name} was edited after it was applied; "
                "write a new migration instead of changing a released one"
            )
    return problems


def out_of_order(migrations: tuple[Migration, ...], applied: dict[str, str]) -> list[str]:
    """Pending migrations numbered below one that is already applied.

    Two branches numbering past each other produce this. Applying the lower one
    now gives a database that no fresh run of the set can reproduce, so renumber
    the branch instead.
    """
    if not applied:
        return []
    highest = max(applied)
    return [m.name for m in migrations if m.version not in applied and m.version < highest]


async def _ensure_ledger(conn: Any) -> None:
    await conn.execute(LEDGER)


async def _applied(conn: Any) -> dict[str, str]:
    rows = await conn.fetch("SELECT version, checksum FROM schema_migration")
    return {row["version"]: row["checksum"] for row in rows}


async def _apply(conn: Any, migration: Migration) -> None:
    started = time.perf_counter()
    if migration.no_transaction:
        await conn.execute(migration.sql)
        elapsed = int((time.perf_counter() - started) * 1000)
        await conn.execute(RECORD, migration.version, migration.slug, migration.checksum, elapsed)
        return
    async with conn.transaction():
        await conn.execute(migration.sql)
        elapsed = int((time.perf_counter() - started) * 1000)
        await conn.execute(RECORD, migration.version, migration.slug, migration.checksum, elapsed)


async def _revert(conn: Any, migration: Migration) -> None:
    if migration.down_path is None:  # pragma: no cover - callers check first
        raise MigrationError(f"{migration.name} has no .down.sql")
    async with conn.transaction():
        await conn.execute(migration.down_path.read_text())
        await conn.execute("DELETE FROM schema_migration WHERE version = $1", migration.version)


async def up(
    conn: Any, migrations: tuple[Migration, ...], to: str | None = None
) -> list[Migration]:
    await _ensure_ledger(conn)
    applied = await _applied(conn)

    problems = drift(migrations, applied)
    if problems:
        raise MigrationError("\n".join(problems))
    stragglers = out_of_order(migrations, applied)
    if stragglers:
        raise MigrationError(
            "Pending migrations numbered below one already applied: "
            + ", ".join(stragglers)
            + ". Renumber them above the highest applied version."
        )

    pending = [m for m in migrations if m.version not in applied]
    if to is not None:
        pending = [m for m in pending if m.version <= to]

    for migration in pending:
        await _apply(conn, migration)
    return pending


async def down(
    conn: Any, migrations: tuple[Migration, ...], to: str | None = None
) -> list[Migration]:
    """Revert down to but not including ``to``; with no target, revert one."""
    await _ensure_ledger(conn)
    applied = await _applied(conn)
    known = {m.version: m for m in migrations}

    order = sorted(applied, reverse=True)
    order = order[:1] if to is None else [v for v in order if v > to]

    reverted: list[Migration] = []
    for version in order:
        migration = known.get(version)
        if migration is None:
            raise MigrationError(f"{version} is applied but its files are gone; cannot revert it")
        if not migration.reversible:
            raise MigrationError(
                f"{migration.name} has no .down.sql. Roll forward with a new migration."
            )
        await _revert(conn, migration)
        reverted.append(migration)
    return reverted


def new(slug: str, directory: Path = MIGRATIONS_DIR) -> tuple[Path, Path]:
    """Scaffold the next numbered pair of files."""
    if not SLUG.match(slug):
        raise MigrationError(f"{slug!r} must be lower case letters, digits and underscores")
    existing = discover(directory)
    version = f"{(int(existing[-1].version) if existing else 0) + 1:04d}"
    up_path = directory / f"{version}_{slug}.up.sql"
    down_path = directory / f"{version}_{slug}.down.sql"
    up_path.write_text(UP_TEMPLATE.format(version=version, title=slug.replace("_", " ")))
    down_path.write_text(DOWN_TEMPLATE.format(version=version, slug=slug))
    return up_path, down_path


async def _connect(dsn: str) -> Any:
    """Connect and take the migration lock, so concurrent runners queue."""
    conn = await asyncpg.connect(dsn)
    await conn.execute("SELECT pg_advisory_lock($1)", LOCK_KEY)
    return conn


async def _ledger_state(dsn: str) -> dict[str, str]:
    conn = await _connect(dsn)
    try:
        await _ensure_ledger(conn)
        return await _applied(conn)
    finally:
        await conn.close()


async def _run(args: argparse.Namespace) -> int:
    if args.command == "new":
        up_path, down_path = new(args.slug)
        print(f"created {up_path}")
        print(f"created {down_path}")
        return 0

    migrations = discover()
    dsn: str = args.database_url or get_settings().database_url

    if args.command == "status":
        applied = await _ledger_state(dsn)
        for migration in migrations:
            state = "applied" if migration.version in applied else "pending"
            note = "" if migration.reversible else "  (no down migration)"
            print(f"  {state:<8} {migration.name}{note}")
        problems = drift(migrations, applied)
        for problem in problems:
            print(f"  drift    {problem}", file=sys.stderr)
        pending = sum(1 for m in migrations if m.version not in applied)
        print(f"\n{len(applied)} applied, {pending} pending")
        return 1 if problems else 0

    if args.command == "verify":
        applied = await _ledger_state(dsn)
        problems = drift(migrations, applied)
        missing = [m.name for m in migrations if m.version not in applied]
        if missing:
            problems.append(f"not applied: {', '.join(missing)}")
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print(f"{len(applied)} migrations applied, every checksum matches")
        return 0

    conn = await _connect(dsn)
    try:
        if args.command == "up":
            changed = await up(conn, migrations, args.to)
            verb = "applied"
        else:
            changed = await down(conn, migrations, args.to)
            verb = "reverted"
    finally:
        await conn.close()

    for migration in changed:
        print(f"  {verb} {migration.name}")
    print(f"{len(changed)} {verb}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.migrate",
        description="Apply the SQL migrations in api/migrations.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Overrides DATABASE_URL. Defaults to the setting the API itself uses.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="list applied and pending migrations")
    sub.add_parser("verify", help="exit non-zero unless every migration is applied and unchanged")

    up_parser = sub.add_parser("up", help="apply pending migrations")
    up_parser.add_argument("--to", default=None, help="stop after this version, e.g. 0007")

    down_parser = sub.add_parser("down", help="revert migrations")
    down_parser.add_argument(
        "--to", default=None, help="revert down to but not including this version"
    )

    new_parser = sub.add_parser("new", help="scaffold the next migration")
    new_parser.add_argument("slug", help="e.g. add_facility_naics")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
