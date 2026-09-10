"""Retry, rate limiting, and partial failure — declared once, for every source.

This module is the reason the adapter interface is worth having. Five sources
with five hand-rolled retry loops drift apart within a month: one honours
Retry-After and one does not, one gives up after three attempts and one hammers
an EPA endpoint until it is blocked, one silently loads a pull that lost a third
of its rows. Here the behaviour is one object, `SourcePolicy`, that the runner
applies. An adapter that needs different numbers overrides the numbers; it does
not get to override the behaviour.

The only field expected to vary in practice is the rate limit, because each
upstream publishes its own. Everything else should stay at the default and a
pull request that changes it should say why in the commit message.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

Monotonic = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]

Verdict = Literal["ok", "partial", "failed"]

# Statuses that mean "the server is busy or broken, come back shortly".
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter.

    Attempt 1 is the first try, so `max_attempts=5` means one call and four
    retries. Jitter is subtractive rather than additive: five adapters that
    started together in the nightly job must not line their retries up.
    """

    max_attempts: int = 5
    initial_backoff_s: float = 1.0
    multiplier: float = 2.0
    max_backoff_s: float = 60.0
    jitter: float = 0.25
    # An upstream asking for a longer wait than this is treated as down for the
    # night rather than slept through; the nightly job has a finite budget.
    max_retry_after_s: float = 300.0

    def backoff_for(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
        rng: random.Random | None = None,
    ) -> float:
        """Seconds to wait before attempt number `attempt + 1`."""
        if retry_after is not None:
            return min(max(retry_after, 0.0), self.max_retry_after_s)
        raw = self.initial_backoff_s * self.multiplier ** max(attempt - 1, 0)
        capped = min(raw, self.max_backoff_s)
        source = rng if rng is not None else random
        return capped * (1.0 - self.jitter * source.random())

    def gives_up_after(self, attempt: int) -> bool:
        return attempt >= self.max_attempts


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Token bucket parameters. A non-positive rate means no limiting."""

    requests_per_second: float = 5.0
    burst: int = 5

    @classmethod
    def unlimited(cls) -> "RateLimit":
        return cls(requests_per_second=0.0, burst=0)

    @property
    def limited(self) -> bool:
        return self.requests_per_second > 0.0


class Throttle:
    """Async token bucket. One instance per adapter run, shared by every request.

    The clock and the sleeper are injected so tests can prove the spacing
    without spending the wall time.
    """

    def __init__(
        self,
        limit: RateLimit,
        *,
        monotonic: Monotonic = time.monotonic,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._limit = limit
        self._monotonic = monotonic
        self._sleep = sleep
        self._tokens = float(limit.burst)
        self._updated = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Take one token, waiting if the bucket is empty. Returns seconds waited."""
        if not self._limit.limited:
            return 0.0
        waited = 0.0
        async with self._lock:
            while True:
                now = self._monotonic()
                self._tokens = min(
                    float(self._limit.burst),
                    self._tokens + (now - self._updated) * self._limit.requests_per_second,
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return waited
                deficit = (1.0 - self._tokens) / self._limit.requests_per_second
                await self._sleep(deficit)
                waited += deficit


@dataclass(frozen=True, slots=True)
class PartialFailurePolicy:
    """When a pull that lost some records is still worth loading.

    The defaults are deliberately tight. A source that suddenly rejects one row
    in fifty has usually changed its schema, and loading the survivors would
    quietly shrink coverage in whichever region the change happened to affect.
    Coverage loss must show up as a failed run, not as a smaller map.
    """

    max_reject_fraction: float = 0.01
    max_rejects: int | None = None
    min_records: int = 1

    def verdict(self, *, accepted: int, rejected: int) -> Verdict:
        seen = accepted + rejected
        if seen == 0 or accepted < self.min_records:
            return "failed"
        if self.max_rejects is not None and rejected > self.max_rejects:
            return "failed"
        if rejected == 0:
            return "ok"
        if rejected / seen > self.max_reject_fraction:
            return "failed"
        return "partial"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """Everything an adapter is allowed to tune about failure handling."""

    retry: RetryPolicy = field(default_factory=RetryPolicy)
    rate_limit: RateLimit = field(default_factory=RateLimit)
    partial_failure: PartialFailurePolicy = field(default_factory=PartialFailurePolicy)
    request_timeout_s: float = 30.0
    # Methodology section 6: if a source is unavailable the pipeline continues on
    # the last good snapshot and the recency term degrades. It never silently
    # substitutes a different source, and it never invents a value.
    stale_fallback: bool = True


DEFAULT_POLICY = SourcePolicy()
