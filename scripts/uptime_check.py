#!/usr/bin/env python3
"""CS-403: is the public site up, from the outside, the way a reader sees it.

Three checks, each of which has failed or nearly failed in a way an HTTP 200
would not have shown:

- **The API's `/health` says `ok` with the database connected.** The endpoint
  degrades rather than failing when the database is unreachable, so a 200 alone
  proves only that the process is running.
- **The website serves its page.**
- **The tile archive answers a Range request with a PMTiles header.** The map
  is drawn from it and there is no tile server, so a moved or private archive is
  a map with no hexagons. Its URL is read out of the live bundle rather than
  configured here, because each release points the site at a new run-numbered
  archive and a check pinned to the old one would watch the wrong file.

Standard library only, so the workflow runs it without installing anything.
Exits non-zero on any failure and prints one line per check.

    python scripts/uptime_check.py
    python scripts/uptime_check.py --api https://... --web https://...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

API = "https://clearskies-api-production.up.railway.app"
WEB = "https://clearskies-web-production.up.railway.app"
TIMEOUT_S = 30
USER_AGENT = "clearskies-uptime/1"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def fetch(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


Fetch = Callable[..., tuple[int, bytes]]


def check_api(api: str, get: Fetch = fetch) -> Check:
    try:
        status, body = get(f"{api}/health")
        health = json.loads(body)
    except Exception as exc:  # noqa: BLE001 - any failure to read is a failure
        return Check("api", False, f"/health unreadable: {exc}")
    if status != 200:
        return Check("api", False, f"/health returned {status}")
    if health.get("status") != "ok" or health.get("database") != "connected":
        return Check(
            "api",
            False,
            f"/health status={health.get('status')} database={health.get('database')}",
        )
    return Check("api", True, f"ok, {health.get('scored_hexes')} scored hexes")


def check_web(web: str, get: Fetch = fetch) -> tuple[Check, str]:
    """The page, and the HTML for the tile check to read the bundle from."""
    try:
        status, body = get(web + "/")
    except Exception as exc:  # noqa: BLE001
        return Check("web", False, f"unreachable: {exc}"), ""
    html = body.decode("utf-8", "replace")
    if status != 200 or 'id="root"' not in html:
        return Check("web", False, f"returned {status} without the app's root element"), html
    return Check("web", True, "ok"), html


def tiles_url(web: str, html: str, get: Fetch = fetch) -> str | None:
    for asset in re.findall(r'/assets/[^"]+\.js', html):
        try:
            _, body = get(web + asset)
        except Exception:  # noqa: BLE001
            continue
        found = re.search(r"https://[^\"'\s]+\.pmtiles", body.decode("utf-8", "replace"))
        if found:
            return found.group(0)
    return None


def check_tiles(url: str | None, get: Fetch = fetch) -> Check:
    if url is None:
        return Check("tiles", False, "no .pmtiles URL found in the live bundle")
    try:
        status, body = get(url, headers={"Range": "bytes=0-6"})
    except Exception as exc:  # noqa: BLE001
        return Check("tiles", False, f"{url}: {exc}")
    if status != 206 or not body.startswith(b"PMTiles"):
        return Check("tiles", False, f"{url}: {status}, not a PMTiles range response")
    return Check("tiles", True, url.rsplit("/", 1)[-1])


def run(api: str, web: str, get: Fetch = fetch) -> list[Check]:
    web_check, html = check_web(web, get)
    checks = [check_api(api, get), web_check]
    checks.append(check_tiles(tiles_url(web, html, get) if web_check.ok else None, get))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API)
    parser.add_argument("--web", default=WEB)
    args = parser.parse_args(argv)

    checks = run(args.api.rstrip("/"), args.web.rstrip("/"))
    for check in checks:
        print(f"{'ok  ' if check.ok else 'FAIL'} {check.name:<6} {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
