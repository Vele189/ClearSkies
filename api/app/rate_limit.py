"""Small per-client limits on the public endpoints.

`/draft` calls a paid API on every miss, and nothing stood between a script and
the spend cap. The read endpoints spend no money and still reach the database
once per request, and a crawler that walks every hexagon in Louisiana is 19,881
queries nobody asked for. Both are the same cheap answer: a fixed number of
requests per client per window, in this process's memory, with no dependency
and no Redis.

**The two limits are deliberately far apart.** A draft is a few per hour,
because each one is money and no human writes ten an hour. A read is hundreds
per minute, because opening a panel is one request and a reader clicking around
the map is meant to be able to keep clicking. A read limit tight enough to stop
a determined scraper would stop ordinary use first, and the scraper would still
get the data one request at a time -- it is public data, and the limit is there
to keep one client from taking the database down, not to keep anybody out.

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


#: One window per named limit, per process. Built on first use rather than at
#: import, so a deployment or a test can change a limit without the module
#: having already read it.
_windows: dict[str, SlidingWindow] = {}


def window_for(name: str, limit: int, window_s: float) -> SlidingWindow:
    """The named window, rebuilt when its configuration has changed.

    Rebuilding drops the counts, which is the right way round: a deployment
    that raises its limit should not keep rejecting the client that was over
    the old one.
    """
    existing = _windows.get(name)
    if existing is None or existing.limit != limit or existing.window_s != window_s:
        existing = SlidingWindow(limit, window_s)
        _windows[name] = existing
    return existing


def reset_all() -> None:
    """Forget every count. For tests, which must not inherit each other's."""
    for window in _windows.values():
        window.reset()


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
