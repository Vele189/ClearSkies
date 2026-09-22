"""Last-good copies of what each source served.

Methodology section 6 treats upstream availability as unreliable: several EPA
datasets were withdrawn from public hosting during 2025. When a source is
unreachable the pipeline continues on the last good snapshot and the recency
term in the confidence score degrades accordingly. It does not silently
substitute a different source, and it does not skip the night.

The store is a protocol for the same reason the sink is. Phase 1 backs it with
Cloudflare R2, holding raw source snapshots as Parquet alongside the tiles.
`FileSnapshotStore` is what stands in until then, and it is what makes the
promise above true from the command line: a fallback is only possible if the
bytes outlive the process that downloaded them, and an in-memory store is
emptied by the exit of the night that filled it.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


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


# A source name is a registry key and looks like an identifier, but it becomes a
# directory here, so it is checked rather than trusted.
_SAFE_SOURCE = re.compile(r"[A-Za-z0-9_-]+")


class FileSnapshotStore:
    """The same store, on disk, so the next process can fall back on it.

    One directory per source, and one pair of files per URL: the bytes, and a
    small JSON header carrying the URL they answered, when they were retrieved
    and their checksum. The pair is named by the SHA-256 of the URL rather than
    by the URL itself, because a URL is longer than a file name may be and
    contains characters a file name may not.

    Keyed by URL and keeping only the most recent snapshot, exactly as
    `InMemorySnapshotStore` is: the fallback replays one night, not a history.
    `HttpFetcher` is what decides which URLs get here, and its docstring is
    where the consequence lives -- two requests sharing a URL share a snapshot.

    Both files are written to a temporary name and renamed into place, so a run
    killed mid-write leaves the previous snapshot intact rather than a truncated
    one. The checksum is verified on the way out for the same reason: a half
    written or corrupted file reads as no snapshot, which falls back to failing
    the source, rather than as data.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _directory(self, source: str) -> Path:
        if not _SAFE_SOURCE.fullmatch(source):
            raise ValueError(f"{source!r} is not usable as a snapshot directory name")
        return self.root / source

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    async def put(self, source: str, snapshot: Snapshot) -> None:
        await asyncio.to_thread(self._write, source, snapshot)

    def _write(self, source: str, snapshot: Snapshot) -> None:
        directory = self._directory(source)
        directory.mkdir(parents=True, exist_ok=True)
        key = self._key(snapshot.url)
        header = {
            "url": snapshot.url,
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "sha256": snapshot.sha256,
            "size_bytes": len(snapshot.content),
        }
        _replace(directory / f"{key}.bin", snapshot.content)
        _replace(directory / f"{key}.json", json.dumps(header, indent=2).encode("utf-8"))

    async def get(self, source: str, url: str) -> Snapshot | None:
        return await asyncio.to_thread(self._read, source, url)

    def _read(self, source: str, url: str) -> Snapshot | None:
        directory = self._directory(source)
        key = self._key(url)
        try:
            header = json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))
            content = (directory / f"{key}.bin").read_bytes()
        except (OSError, ValueError):
            return None
        digest = hashlib.sha256(content).hexdigest()
        if digest != header.get("sha256"):
            log.warning("%s: snapshot of %s does not match its checksum; ignoring it", source, url)
            return None
        return Snapshot(
            url=str(header.get("url", url)),
            content=content,
            retrieved_at=datetime.fromisoformat(str(header["retrieved_at"])),
            sha256=digest,
        )


def _replace(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
