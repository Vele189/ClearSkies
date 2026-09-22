"""The on-disk snapshot store, and the fallback it makes possible.

Methodology section 6 promises that an unreachable source is served from its
last good snapshot. That promise is about two different nights, which means two
different processes, so the last test here really does start one: it writes the
snapshots in this process and reads them back from a `python -c` that shares
nothing with it but the directory.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline.snapshots import FileSnapshotStore, Snapshot, SnapshotStore

RETRIEVED = datetime(2026, 9, 22, 7, 0, tzinfo=UTC)


def snapshot(url: str, content: bytes) -> Snapshot:
    import hashlib

    return Snapshot(
        url=url,
        content=content,
        retrieved_at=RETRIEVED,
        sha256=hashlib.sha256(content).hexdigest(),
    )


async def test_the_store_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(FileSnapshotStore(tmp_path), SnapshotStore)


async def test_a_snapshot_survives_the_store_object_that_wrote_it(tmp_path: Path) -> None:
    await FileSnapshotStore(tmp_path).put("fake", snapshot("https://example.test/a", b"one"))

    restored = await FileSnapshotStore(tmp_path).get("fake", "https://example.test/a")

    assert restored is not None
    assert restored.content == b"one"
    assert restored.url == "https://example.test/a"
    assert restored.retrieved_at == RETRIEVED


async def test_sources_and_urls_do_not_collide(tmp_path: Path) -> None:
    store = FileSnapshotStore(tmp_path)
    await store.put("fake", snapshot("https://example.test/a", b"one"))
    await store.put("fake", snapshot("https://example.test/b", b"two"))
    await store.put("openaq", snapshot("https://example.test/a", b"three"))

    assert (await store.get("fake", "https://example.test/a")).content == b"one"  # type: ignore[union-attr]
    assert (await store.get("fake", "https://example.test/b")).content == b"two"  # type: ignore[union-attr]
    assert (await store.get("openaq", "https://example.test/a")).content == b"three"  # type: ignore[union-attr]


async def test_only_the_most_recent_copy_is_kept(tmp_path: Path) -> None:
    """The same rule `InMemorySnapshotStore` keeps: a fallback replays one night."""
    store = FileSnapshotStore(tmp_path)
    await store.put("fake", snapshot("https://example.test/a", b"old"))
    await store.put("fake", snapshot("https://example.test/a", b"new"))

    restored = await store.get("fake", "https://example.test/a")

    assert restored is not None
    assert restored.content == b"new"


async def test_a_url_never_stored_reads_as_absent(tmp_path: Path) -> None:
    assert await FileSnapshotStore(tmp_path).get("fake", "https://example.test/missing") is None


async def test_a_corrupted_snapshot_reads_as_absent_rather_than_as_data(tmp_path: Path) -> None:
    """Half a file is not a snapshot. Failing the source is the honest outcome."""
    store = FileSnapshotStore(tmp_path)
    await store.put("fake", snapshot("https://example.test/a", b"one"))
    blob = next(tmp_path.glob("fake/*.bin"))
    blob.write_bytes(b"tampered")

    assert await store.get("fake", "https://example.test/a") is None


async def test_a_source_name_that_is_not_a_directory_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="snapshot directory"):
        await FileSnapshotStore(tmp_path).get("../escape", "https://example.test/a")


READ_BACK = """
import asyncio, sys
from pipeline.http import HttpFetcher
from pipeline.snapshots import FileSnapshotStore
import httpx


async def main(root: str) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the second process must not reach the network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        fetcher = HttpFetcher(client, source="fake", snapshots=FileSnapshotStore(root))
        fetcher.offline = True
        download = await fetcher.get("https://example.test/a")
        assert download.artifact.from_snapshot
        sys.stdout.write(download.text())


asyncio.run(main(sys.argv[1]))
"""


async def test_a_second_process_serves_offline_from_the_first_one_s_snapshots(
    tmp_path: Path,
) -> None:
    """E4: what an in-memory store cannot do, and the whole point of the fallback."""
    await FileSnapshotStore(tmp_path).put("fake", snapshot("https://example.test/a", b"last good"))

    finished = subprocess.run(  # noqa: S603
        [sys.executable, "-c", READ_BACK, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout == "last good"
