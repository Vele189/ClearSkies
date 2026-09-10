"""Tests for the migration runner and for the migration set it ships with.

Nothing here touches a database. Applying the SQL is CI's `database` job, which
already has the custom Postgres image up; these cover the parts that decide
whether two databases end up agreeing, which is where the damage would be
silent.
"""

import re
from pathlib import Path

import pytest

from app.migrate import (
    MigrationError,
    discover,
    drift,
    new,
    out_of_order,
    parse_args,
)

SHIPPED = discover()

CREATE_TABLE = re.compile(r"^CREATE TABLE (?:IF NOT EXISTS )?(\w+)", re.MULTILINE)
DROP_TABLE = re.compile(r"^DROP TABLE (?:IF EXISTS )?(\w+)", re.MULTILINE)


def ddl_only(sql: str) -> str:
    """The statements with comments and string literals emptied out.

    Tests that assert something is absent from the schema have to look at what
    Postgres will execute. Prose explaining why a thing is absent mentions it by
    name, and would otherwise trip the check it exists to document.

    One pass rather than two regexes, because comments hold apostrophes and
    literals could hold a double dash, so whichever pattern ran first would
    swallow the rest of the file. Dollar quoting is not handled; no migration
    uses it, and one that did would need a real parser anyway.
    """
    out: list[str] = []
    i = 0
    while i < len(sql):
        if sql[i] == "'":
            i += 1
            while i < len(sql):
                if sql[i] == "'":
                    if sql[i + 1 : i + 2] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append("''")
        elif sql.startswith("--", i):
            while i < len(sql) and sql[i] != "\n":
                i += 1
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def write(directory: Path, name: str, body: str = "SELECT 1;\n") -> Path:
    path = directory / name
    path.write_text(body)
    return path


# ---- The set that ships -------------------------------------------------


def test_shipped_migrations_are_numbered_from_one_without_gaps() -> None:
    assert [m.version for m in SHIPPED] == [f"{n:04d}" for n in range(1, len(SHIPPED) + 1)]


def test_every_shipped_migration_is_reversible() -> None:
    assert [m.name for m in SHIPPED if not m.reversible] == []


def test_every_created_table_is_dropped_by_its_down_migration() -> None:
    """A down migration that forgets a table leaves the next `up` unable to run."""
    for migration in SHIPPED:
        assert migration.down_path is not None
        created = set(CREATE_TABLE.findall(ddl_only(migration.sql)))
        dropped = set(DROP_TABLE.findall(ddl_only(migration.down_path.read_text())))
        assert created <= dropped, f"{migration.name} does not drop {sorted(created - dropped)}"


def test_scores_migration_creates_the_table_health_reports_on() -> None:
    # GET /health and GET /hex/{h3} both probe for hex_score by name to decide
    # whether the pipeline has run. Renaming it would degrade both endpoints
    # without failing anything else.
    created = {table for m in SHIPPED for table in CREATE_TABLE.findall(ddl_only(m.sql))}
    assert "hex_score" in created


def test_h3_columns_avoid_the_h3_pg_extension_type() -> None:
    # The pipeline computes cell indexes in Python and must keep working on a
    # database without h3-pg. A column typed h3index would break that quietly.
    for migration in SHIPPED:
        assert not re.search(r"\bh3index\b", ddl_only(migration.sql)), migration.name


def test_no_shipped_migration_needs_to_skip_its_transaction() -> None:
    assert [m.name for m in SHIPPED if m.no_transaction] == []


# ---- discover -----------------------------------------------------------


def test_discover_pairs_up_and_down_files(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0001_first.down.sql")
    write(tmp_path, "0002_second.up.sql")

    found = discover(tmp_path)

    assert [m.name for m in found] == ["0001_first", "0002_second"]
    assert found[0].reversible
    assert not found[1].reversible


def test_discover_ignores_dotfiles(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, ".gitkeep", "")

    assert len(discover(tmp_path)) == 1


def test_discover_rejects_an_unrecognised_filename(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "fixup.sql")

    with pytest.raises(MigrationError, match="not named"):
        discover(tmp_path)


def test_discover_rejects_two_migrations_with_the_same_number(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0001_other.up.sql")

    with pytest.raises(MigrationError, match="Two migrations numbered 0001"):
        discover(tmp_path)


def test_discover_rejects_a_down_migration_with_no_up(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0002_orphan.down.sql")

    with pytest.raises(MigrationError, match="no up migration"):
        discover(tmp_path)


def test_discover_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="No migrations directory"):
        discover(tmp_path / "absent")


def test_no_transaction_marker_is_read_from_the_first_line(tmp_path: Path) -> None:
    write(tmp_path, "0001_plain.up.sql", "CREATE INDEX a ON b (c);\n")
    write(
        tmp_path,
        "0002_concurrent.up.sql",
        "-- migrate:no-transaction\nCREATE INDEX CONCURRENTLY a ON b (c);\n",
    )

    plain, concurrent = discover(tmp_path)

    assert not plain.no_transaction
    assert concurrent.no_transaction


# ---- drift and ordering -------------------------------------------------


def test_drift_is_silent_when_the_ledger_matches_disk(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    (migration,) = discover(tmp_path)

    assert drift((migration,), {"0001": migration.checksum}) == []


def test_drift_reports_a_migration_edited_after_it_was_applied(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    (migration,) = discover(tmp_path)
    applied = {"0001": migration.checksum}

    write(tmp_path, "0001_first.up.sql", "SELECT 2;\n")
    (edited,) = discover(tmp_path)

    (problem,) = drift((edited,), applied)
    assert "was edited after it was applied" in problem


def test_drift_reports_an_applied_migration_whose_file_is_gone(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    found = discover(tmp_path)

    (problem,) = drift(found, {"0001": found[0].checksum, "0002": "whatever"})
    assert "0002 is recorded as applied but its file is gone" in problem


def test_out_of_order_flags_a_branch_that_numbered_below_head(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0002_late.up.sql")
    write(tmp_path, "0003_head.up.sql")
    found = discover(tmp_path)

    assert out_of_order(found, {"0001": "x", "0003": "y"}) == ["0002_late"]


def test_out_of_order_allows_the_normal_case(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0002_next.up.sql")
    found = discover(tmp_path)

    assert out_of_order(found, {"0001": "x"}) == []
    assert out_of_order(found, {}) == []


# ---- new ----------------------------------------------------------------


def test_new_scaffolds_the_next_version(tmp_path: Path) -> None:
    write(tmp_path, "0001_first.up.sql")
    write(tmp_path, "0001_first.down.sql")

    up_path, down_path = new("add_facility_naics", tmp_path)

    assert up_path.name == "0002_add_facility_naics.up.sql"
    assert down_path.name == "0002_add_facility_naics.down.sql"
    assert [m.name for m in discover(tmp_path)] == ["0001_first", "0002_add_facility_naics"]


def test_new_starts_at_one_in_an_empty_directory(tmp_path: Path) -> None:
    up_path, _ = new("initial", tmp_path)

    assert up_path.name == "0001_initial.up.sql"


def test_new_rejects_a_slug_that_would_not_parse_back(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="lower case"):
        new("Add Facility NAICS", tmp_path)


# ---- argument parsing ---------------------------------------------------


def test_up_takes_an_optional_target() -> None:
    assert parse_args(["up"]).to is None
    assert parse_args(["up", "--to", "0007"]).to == "0007"


def test_database_url_overrides_the_api_setting() -> None:
    args = parse_args(["--database-url", "postgresql://localhost/other", "status"])

    assert args.database_url == "postgresql://localhost/other"
    assert args.command == "status"


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])
