"""Where normalized records go.

The sink is a protocol rather than a class so the adapter interface does not
depend on PostGIS. Tests run against `InMemorySink`; Phase 1 adds the Postgres
implementation and nothing in `pipeline.adapters` changes.

One rule the protocol encodes: a run is a transaction. The runner opens the
sink, writes, and commits only once the partial-failure verdict allows it. A
pull that loses too many records leaves the previous night's data in place
rather than replacing it with a thinner version of itself.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pipeline.metadata import PullMetadata
from pipeline.records import NormalizedRecord


@runtime_checkable
class Sink(Protocol):
    """Transactional destination for one adapter run."""

    async def begin(self, source: str) -> None:
        """Open the transaction for this source's pull."""
        ...

    async def write(self, table: str, records: Sequence[NormalizedRecord]) -> int:
        """Stage records, upserting on their natural key. Returns rows written."""
        ...

    async def commit(self, metadata: PullMetadata) -> None:
        """Make the pull visible, together with its provenance record."""
        ...

    async def rollback(self) -> None:
        """Discard everything staged in this run."""
        ...


class InMemorySink:
    """Reference sink. Used by the tests, the fake adapter, and `--dry-run`.

    Keyed by natural key so a re-pull of the same records is idempotent, which
    is the property the Postgres implementation will have to reproduce.
    """

    def __init__(self) -> None:
        self.tables: dict[str, dict[tuple[str, ...], NormalizedRecord]] = {}
        self.manifests: list[PullMetadata] = []
        self._staged: dict[str, dict[tuple[str, ...], NormalizedRecord]] = {}
        self._open: str | None = None

    async def begin(self, source: str) -> None:
        self._open = source
        self._staged = {}

    async def write(self, table: str, records: Sequence[NormalizedRecord]) -> int:
        staged = self._staged.setdefault(table, {})
        for record in records:
            staged[record.natural_key()] = record
        return len(records)

    async def commit(self, metadata: PullMetadata) -> None:
        for table, records in self._staged.items():
            self.tables.setdefault(table, {}).update(records)
        self.manifests.append(metadata)
        self._staged = {}
        self._open = None

    async def rollback(self) -> None:
        self._staged = {}
        self._open = None

    def count(self, table: str) -> int:
        return len(self.tables.get(table, {}))

    def rows(self, table: str) -> list[NormalizedRecord]:
        return list(self.tables.get(table, {}).values())

    def table_names(self) -> tuple[str, ...]:
        """Tables holding at least one committed row.

        With `rows`, this is the whole of the `quality.Dataset` protocol, so a
        sink can be handed straight to the gate. Staged-but-uncommitted rows are
        deliberately invisible: the gate judges what a run actually loaded.
        """
        return tuple(sorted(name for name, rows in self.tables.items() if rows))
