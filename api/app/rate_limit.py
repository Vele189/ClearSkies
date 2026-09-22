"""A small per-client limit on the endpoint that spends money.

`/draft` calls a paid API on every miss, and nothing stood between a script and
the spend cap. This is the cheap half of the answer: a fixed number of requests
per client per window, in this process's memory, with no dependency and no
Redis.

**It is a courtesy, not a control.** The process holds its own counters, so two
replicas allow twice the limit and a restart forgets everything. The limit that
cannot be got round is the spend cap configured with the provider, for the same
reason `/draft/spend` says so: a limit the application enforces stops working
when the application has a bug. What this buys is that one client cannot burn a
month's budget in a minute by holding down a button, which is the failure that
actually happens.

A sliding window rather than a token bucket, because the question a 429 has to
answer is "how long until I may retry", and a window of timestamps answers it
exactly: the oldest request in the window falls out at a known moment.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindow:
    """At most `limit` hits per `window_s`, per key."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @property
    def enabled(self) -> bool:
        """A limit of zero or less is off, which is how the setting turns it off."""
        return self.limit > 0

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit and return None, or the seconds to wait and record nothing.

        Recording only the allowed hits is deliberate. A client that keeps
        knocking while limited would otherwise push its own window forward with
        every rejected request and never be let back in, which turns a rate
        limit into a ban.
        """
        if not self.enabled:
            return None

        moment = time.monotonic() if now is None else now
        hits = self._hits[key]
        cutoff = moment - self.window_s
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return max(hits[0] + self.window_s - moment, 0.0)

        hits.append(moment)
        # Keys with nothing left in the window are dropped, so a long-running
        # process does not accumulate one deque per address it has ever seen.
        self._prune(cutoff)
        return None

    def _prune(self, cutoff: float) -> None:
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


def client_key(forwarded_for: str | None, peer: str | None) -> str:
    """Who to count a request against.

    The first hop in `X-Forwarded-For` when the platform sets one, because
    behind Railway's proxy every peer address is the proxy's. It is a header and
    a client can send whatever it likes in it, which is why this is a courtesy
    and not a control; the peer address is the fallback and, in a deployment
    with no proxy, the only value anybody can trust.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"
