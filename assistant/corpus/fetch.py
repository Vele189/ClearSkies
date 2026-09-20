"""Retrieval of source documents, cached on disk and recorded.

Two jobs, and the second is the one that matters. The first is to get the bytes.
The second is to record, for every document in the corpus, the URL it came from
and the moment it was read, because Appendix B rule 1 requires both and because
a corpus that cannot say where its text came from is a corpus whose citations
cannot be checked against anything.

The cache is not a performance feature. Ingestion is run rarely and a few
megabytes of statute would download in under a minute. It is there so that a
re-run produces the same corpus as the first run: without it, "rebuild the
corpus" means "download whatever those URLs serve today", and two builds of the
same manifest version could differ. Cached bytes are keyed by URL and stored
next to the SHA-256 of what arrived, so a changed upstream document is visible
as a changed hash rather than as a silently different corpus.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# The GPO, the eCFR and the Caselaw Access Project all serve large documents and
# all are public services run on public money. A descriptive agent is the least
# that owes them, and the eCFR rejects a request that will not take compression.
USER_AGENT = "ClearSkies-corpus/0.1 (+https://github.com/Vele189/ClearSkies)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".cache"


class FetchError(RuntimeError):
    """A source document could not be retrieved."""


@dataclass(frozen=True)
class Fetched:
    """One source document, and everything rule 1 asks to be recorded about it."""

    url: str
    body: bytes
    sha256: str
    retrieved_at: datetime
    from_cache: bool

    @property
    def text(self) -> str:
        # Every source here is UTF-8 or ASCII. `replace` rather than `strict`
        # because a single bad byte in two megabytes of statute should not cost
        # the whole authority, and a replacement character is visible in the
        # chunk if it ever matters.
        return self.body.decode("utf-8", errors="replace")


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


class Cache:
    """Bytes on disk, keyed by URL, with the retrieval metadata beside them."""

    def __init__(self, directory: Path = DEFAULT_CACHE) -> None:
        self.directory = directory

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = _key(url)
        return self.directory / f"{key}.body", self.directory / f"{key}.json"

    def get(self, url: str) -> Fetched | None:
        body_path, meta_path = self._paths(url)
        if not (body_path.is_file() and meta_path.is_file()):
            return None
        meta = json.loads(meta_path.read_text())
        body = body_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != meta["sha256"]:
            # The cached file was edited or truncated. Refuse it rather than
            # ingest text nothing can vouch for.
            log.warning("cached copy of %s does not match its recorded hash; refetching", url)
            return None
        return Fetched(
            url=url,
            body=body,
            sha256=digest,
            retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
            from_cache=True,
        )

    def put(self, fetched: Fetched) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        body_path, meta_path = self._paths(fetched.url)
        body_path.write_bytes(fetched.body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": fetched.url,
                    "sha256": fetched.sha256,
                    "retrieved_at": fetched.retrieved_at.isoformat(),
                    "bytes": len(fetched.body),
                },
                indent=2,
            )
        )


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    cache: Cache | None = None,
    refresh: bool = False,
) -> Fetched:
    """One document, from the cache when it is there and the network when it is not."""
    if cache is not None and not refresh:
        hit = cache.get(url)
        if hit is not None:
            log.debug("cache hit %s", url)
            return hit

    try:
        response = await client.get(url, headers=HEADERS, follow_redirects=True)
    except httpx.HTTPError as exc:
        # Louisiana's hosts do not resolve from every network, and this is the
        # message that says so in terms somebody can act on.
        raise FetchError(f"{url}: {type(exc).__name__}: {exc}") from exc

    if response.status_code != 200:
        raise FetchError(f"{url}: HTTP {response.status_code}")

    body = response.content
    if not body:
        raise FetchError(f"{url}: empty response")

    fetched = Fetched(
        url=url,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        retrieved_at=datetime.now(UTC),
        from_cache=False,
    )
    if cache is not None:
        cache.put(fetched)
    log.info("fetched %s (%d bytes)", url, len(body))
    return fetched


def build_client(timeout: float = 180.0) -> httpx.AsyncClient:
    """A client with a timeout suited to whole chapters of the US Code.

    Chapter 85 is two and a half megabytes and govinfo is not fast. The default
    five seconds fails on it every time, which reads as an outage rather than as
    a timeout that was set for a different kind of request.
    """
    return httpx.AsyncClient(timeout=timeout)
