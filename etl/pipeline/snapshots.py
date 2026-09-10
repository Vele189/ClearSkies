"""Last-good copies of what each source served.

Methodology section 6 treats upstream availability as unreliable: several EPA
datasets were withdrawn from public hosting during 2025. When a source is
unreachable the pipeline continues on the last good snapshot and the recency
term in the confidence score degrades accordingly. It does not silently
substitute a different source, and it does not skip the night.

The store is a protocol for the same reason the sink is. Phase 1 backs it with
Cloudflare R2, holding raw source snapshots as Parquet alongside the tiles.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Snapshot:
    url: str
    content: bytes
    retrieved_at: datetime
    sha256: str


@runtime_checkable
class SnapshotStore(Protocol):
    async def put(self, source: str, snapshot: Snapshot) -> None: ...

    async def get(self, source: str, url: str) -> Snapshot | None: ...


class InMemorySnapshotStore:
    """Reference store. Keeps only the most recent snapshot per URL."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], Snapshot] = {}

    async def put(self, source: str, snapshot: Snapshot) -> None:
        self._items[(source, snapshot.url)] = snapshot

    async def get(self, source: str, url: str) -> Snapshot | None:
        return self._items.get((source, url))

    def __len__(self) -> int:
        return len(self._items)
