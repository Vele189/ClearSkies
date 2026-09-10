"""The one HTTP client every adapter uses.

An adapter calls `ctx.http.get(url)` and gets back bytes plus a checksummed
`Artifact`. It does not write a retry loop, does not sleep between requests, and
does not decide whether a 503 is worth another attempt. All of that is applied
here from the `SourcePolicy`, which is how "retry, rate limit, and partial
failure specified once" stays true as sources are added.

Two behaviours worth knowing about:

- Every successful download is written to the snapshot store. That is what makes
  the stale fallback possible on a later night when upstream is gone.
- In offline mode the fetcher serves those snapshots instead of the network, so
  an adapter's `fetch` runs unmodified during a fallback and simply produces
  artifacts flagged `from_snapshot`.
"""

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from pipeline import __version__
from pipeline.errors import PermanentSourceError, TransientSourceError
from pipeline.metadata import Artifact
from pipeline.policy import (
    DEFAULT_POLICY,
    RETRYABLE_STATUS,
    Monotonic,
    Sleeper,
    SourcePolicy,
    Throttle,
)
from pipeline.snapshots import Snapshot, SnapshotStore

log = logging.getLogger(__name__)

# Public agencies are entitled to know who is calling them nightly.
USER_AGENT = f"ClearSkies/{__version__} (open-source environmental burden mapping)"


@dataclass(frozen=True, slots=True)
class Download:
    artifact: Artifact
    content: bytes

    def text(self, encoding: str = "utf-8") -> str:
        return self.content.decode(encoding)


def build_client(
    policy: SourcePolicy = DEFAULT_POLICY,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """The client every adapter runs against. `transport` is for fixtures."""
    return httpx.AsyncClient(
        timeout=policy.request_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        transport=transport,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _retry_after_seconds(response: httpx.Response, now: datetime) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - now).total_seconds(), 0.0)


class HttpFetcher:
    """Retrying, rate-limited, checksumming GET. One instance per adapter run."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        source: str,
        policy: SourcePolicy = DEFAULT_POLICY,
        snapshots: SnapshotStore | None = None,
        now: Callable[[], datetime] = _utcnow,
        monotonic: Monotonic | None = None,
        sleep: Sleeper = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._source = source
        self._policy = policy
        self._snapshots = snapshots
        self._now = now
        self._sleep = sleep
        self._rng = rng
        self._throttle = (
            Throttle(policy.rate_limit, monotonic=monotonic, sleep=sleep)
            if monotonic is not None
            else Throttle(policy.rate_limit, sleep=sleep)
        )
        self.offline = False
        self.requests = 0
        self.retries = 0
        self.urls: list[str] = []

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        secret_params: Mapping[str, str] | None = None,
    ) -> Download:
        """Fetch one URL, or raise `TransientSourceError` once retries are spent.

        `secret_params` is for query parameters that must never be written down.
        An API key belongs there and nowhere else: it is merged into the request
        and left out of the artifact, the snapshot key and the retry log, all
        three of which are either published or persisted. `Artifact.url` reaches
        docs/provenance.md verbatim, so a key placed in `url` or `params` would
        be published to the repository.

        The corollary is that `url` is the identity of the request. Two calls
        that pass the same `url` share one snapshot, so a source paged or
        chunked across several requests must vary `url` rather than `params`,
        or a later stale night will replay one response for all of them.
        """
        if url not in self.urls:
            self.urls.append(url)
        if self.offline:
            return await self._from_snapshot(url)

        # Merged here rather than handed to httpx, which replaces a URL's own
        # query string when it is given params instead of merging into it.
        target = httpx.URL(url)
        if params:
            target = target.copy_merge_params(params)
        if secret_params:
            target = target.copy_merge_params(secret_params)

        attempt = 0
        while True:
            attempt += 1
            await self._throttle.acquire()
            self.requests += 1
            try:
                response = await self._client.get(target, headers=headers)
            except httpx.TimeoutException as exc:
                error = TransientSourceError(f"{url}: timed out ({exc!r})")
            except httpx.TransportError as exc:
                error = TransientSourceError(f"{url}: transport error ({exc!r})")
            else:
                if response.status_code in RETRYABLE_STATUS:
                    error = TransientSourceError(
                        f"{url}: HTTP {response.status_code}",
                        retry_after=_retry_after_seconds(response, self._now()),
                    )
                elif response.status_code >= 400:
                    raise PermanentSourceError(f"{url}: HTTP {response.status_code}")
                else:
                    return await self._record(url, response)

            if self._policy.retry.gives_up_after(attempt):
                raise error
            delay = self._policy.retry.backoff_for(
                attempt, retry_after=error.retry_after, rng=self._rng
            )
            self.retries += 1
            log.warning("%s: attempt %d failed (%s); retrying in %.1fs", url, attempt, error, delay)
            await self._sleep(delay)

    async def _record(self, url: str, response: httpx.Response) -> Download:
        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        retrieved_at = self._now()
        if self._snapshots is not None:
            await self._snapshots.put(
                self._source,
                Snapshot(url=url, content=content, retrieved_at=retrieved_at, sha256=digest),
            )
        artifact = Artifact(
            url=url,
            retrieved_at=retrieved_at,
            sha256=digest,
            size_bytes=len(content),
            media_type=response.headers.get("Content-Type"),
        )
        return Download(artifact=artifact, content=content)

    async def _from_snapshot(self, url: str) -> Download:
        if self._snapshots is None:
            raise PermanentSourceError(f"{url}: offline with no snapshot store configured")
        snapshot = await self._snapshots.get(self._source, url)
        if snapshot is None:
            raise PermanentSourceError(f"{url}: unavailable and no snapshot was ever taken")
        artifact = Artifact(
            url=url,
            retrieved_at=snapshot.retrieved_at,
            sha256=snapshot.sha256,
            size_bytes=len(snapshot.content),
            from_snapshot=True,
        )
        return Download(artifact=artifact, content=snapshot.content)

    async def can_serve_offline(self) -> bool:
        """True when every URL this run has asked for has a snapshot behind it."""
        if self._snapshots is None or not self.urls:
            return False
        for url in self.urls:
            if await self._snapshots.get(self._source, url) is None:
                return False
        return True
