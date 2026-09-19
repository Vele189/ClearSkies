"""Read access to what a run loaded, for the checks that need more than one source.

The `Sink` protocol is deliberately write-only: an adapter loads and never reads,
which is what keeps one source from quietly depending on another having already
run. Cross-source checks are the one thing that legitimately needs the other
direction, so they get their own narrow protocol rather than widening `Sink`.

Narrow on purpose. A check may ask which tables exist and read the rows of one.
It cannot write, cannot begin a transaction, and cannot commit, so a check that
tries to repair what it found will not compile rather than silently mutating a
load the gate is supposed to be judging.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from pipeline.records import NormalizedRecord


@runtime_checkable
class Dataset(Protocol):
    """What the quality gate is allowed to see."""

    def table_names(self) -> tuple[str, ...]:
        """Tables holding at least one row after this run."""
        ...

    def rows(self, table: str) -> Sequence[NormalizedRecord]:
        """Every row in one table. Empty for a table that does not exist."""
        ...


class EmptyDataset:
    """Nothing was loaded. Every check that needs rows skips, and says so."""

    def table_names(self) -> tuple[str, ...]:
        return ()

    def rows(self, table: str) -> Sequence[NormalizedRecord]:
        return ()


class DictDataset:
    """A dataset assembled by hand. Used by the tests and by `--dry-run`.

    `run_adapter` in dry-run mode writes nothing, so the gate has no sink to read.
    Collecting the normalized records into one of these is what lets a dry run
    still answer "would this load have passed the gate".
    """

    def __init__(self, tables: Mapping[str, Sequence[NormalizedRecord]] | None = None) -> None:
        self._tables: dict[str, list[NormalizedRecord]] = {
            name: list(rows) for name, rows in (tables or {}).items()
        }

    def add(self, records: Sequence[NormalizedRecord]) -> None:
        """File records under their own declared table."""
        for record in records:
            self._tables.setdefault(type(record).table, []).append(record)

    def table_names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, rows in self._tables.items() if rows))

    def rows(self, table: str) -> Sequence[NormalizedRecord]:
        return self._tables.get(table, [])


__all__ = ["Dataset", "DictDataset", "EmptyDataset"]
