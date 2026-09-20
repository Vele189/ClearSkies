"""Check that a published archive is actually servable to the map.

CS-207 asks for CORS configured for the frontend origin and Range requests
confirmed working. Confirmed by whom, though. A bucket policy that looks right
in a dashboard and a bucket that answers a cross-origin Range request with 206
are different claims, and only the second one is the one the browser cares
about. So this asks the deployed URL the questions the browser will ask, from
outside, and reports each answer separately.

**Why each check is here rather than trusted.**

*Range requests.* PMTiles is one large object read in pieces. If the host
answers 200 with the whole body instead of 206 with the slice, the map still
works and quietly pulls the entire archive on every load. That failure is
invisible in a browser and expensive in a bill, which is exactly the kind of
thing that survives a manual check.

*The CORS origin.* The archive is deliberately on a different origin from the
app, so every fetch is cross-origin. Without the header the browser discards a
response it already paid to download, and the console error blames the fetch
rather than the bucket.

*Exposed headers.* `Content-Range` and `Content-Length` are not readable
cross-origin unless the bucket says so. A client that cannot read them can still
work by counting bytes, but a client that checks them fails in a way that looks
like a corrupt archive.

*A different origin from the app.* The reason the archive is not on the Railway
frontend service at all: that edge cache keys on whole URLs, so it either misses
on every Range request or caches a large archive to serve a kilobyte of it, and
Railway bills egress where R2 does not. A URL that has drifted back onto the app
origin has quietly undone the decision, so it is checked rather than assumed.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

# Enough of the archive to prove the slice arrived and to read the file's magic
# number, and small enough that the check costs nothing.
PROBE_BYTES = 128

# Every PMTiles archive starts with these seven bytes followed by the spec
# version. Reading them proves the Range response held the start of the file
# rather than an error page with a 206 stapled to it.
PMTILES_MAGIC = b"PMTiles"
PMTILES_VERSION = 3


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"  {'ok  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


@dataclass(frozen=True, slots=True)
class HostingReport:
    url: str
    origin: str
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def summary(self) -> str:
        head = f"{self.url}\n  as seen from {self.origin}"
        body = "\n".join(check.line() for check in self.checks)
        verdict = "servable" if self.ok else f"{len(self.failures())} check(s) failed"
        return f"{head}\n{body}\n  -> {verdict}"


async def check_hosting(url: str, *, origin: str, client: httpx.AsyncClient) -> HostingReport:
    """Ask the published URL the questions a browser will ask.

    A malformed `url` is refused here rather than left to fail somewhere inside
    the HTTP client. This is usually a mistyped `VITE_TILES_URL`, and a legible
    sentence naming the variable is worth more than a stack trace from urllib.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{url!r} is not an absolute http(s) URL; VITE_TILES_URL must be one")

    checks: list[Check] = []

    head = await client.head(url, headers={"Origin": origin})
    checks.append(_reachable(head))
    checks.append(_accept_ranges(head))

    ranged = await client.get(
        url, headers={"Origin": origin, "Range": f"bytes=0-{PROBE_BYTES - 1}"}
    )
    checks.append(_partial_content(ranged))
    checks.append(_is_pmtiles(ranged))
    checks.append(_cors_origin(ranged, origin))
    checks.append(_exposed_headers(ranged))
    checks.append(_off_app_origin(url, origin))

    return HostingReport(url=url, origin=origin, checks=tuple(checks))


def _reachable(response: httpx.Response) -> Check:
    ok = response.status_code == 200
    return Check(
        name="reachable",
        ok=ok,
        detail=f"HEAD returned {response.status_code}",
    )


def _accept_ranges(response: httpx.Response) -> Check:
    value = response.headers.get("accept-ranges", "")
    return Check(
        name="accept-ranges",
        ok=value.lower() == "bytes",
        detail=f"accept-ranges: {value or 'absent'}",
    )


def _partial_content(response: httpx.Response) -> Check:
    # 200 here means the host ignored the Range and sent the whole archive. The
    # map would still work and would pull every byte on every load.
    if response.status_code != 206:
        return Check(
            name="range request",
            ok=False,
            detail=f"expected 206, got {response.status_code}; the whole archive was sent",
        )
    served = len(response.content)
    return Check(
        name="range request",
        ok=served == PROBE_BYTES,
        detail=f"206 with {served} bytes, content-range: "
        f"{response.headers.get('content-range', 'absent')}",
    )


def _is_pmtiles(response: httpx.Response) -> Check:
    body = response.content
    if not body.startswith(PMTILES_MAGIC):
        return Check(
            name="archive header",
            ok=False,
            detail="the first bytes are not a PMTiles header",
        )
    version = body[7] if len(body) > 7 else -1
    return Check(
        name="archive header",
        ok=version == PMTILES_VERSION,
        detail=f"PMTiles v{version}",
    )


def _cors_origin(response: httpx.Response, origin: str) -> Check:
    allowed = response.headers.get("access-control-allow-origin", "")
    return Check(
        name="cors origin",
        ok=allowed in (origin, "*"),
        detail=f"access-control-allow-origin: {allowed or 'absent'}",
    )


def _exposed_headers(response: httpx.Response) -> Check:
    exposed = response.headers.get("access-control-expose-headers", "")
    names = {name.strip().lower() for name in exposed.split(",") if name.strip()}
    missing = {"content-range", "content-length"} - names
    if "*" in names:
        return Check(name="exposed headers", ok=True, detail="access-control-expose-headers: *")
    return Check(
        name="exposed headers",
        ok=not missing,
        detail=f"exposed: {exposed or 'none'}"
        + (f"; missing {', '.join(sorted(missing))}" if missing else ""),
    )


def _off_app_origin(url: str, origin: str) -> Check:
    archive_host = urlparse(url).netloc.lower()
    app_host = urlparse(origin).netloc.lower()
    return Check(
        name="separate origin",
        ok=bool(archive_host) and archive_host != app_host,
        detail=f"archive on {archive_host or 'no host'}, app on {app_host or 'no host'}",
    )
