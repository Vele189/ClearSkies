"""CS-207: whether the bucket will actually serve the archive to a browser.

Every case here is a way hosting fails while looking fine. A host that ignores
Range still renders a correct map and pulls the whole archive on every visit. A
bucket missing its CORS header downloads the bytes and throws them away. Neither
shows up as a broken map, which is why they are checked rather than eyeballed.
"""

import httpx
import pytest

from pipeline.tiles.hosting import PROBE_BYTES, check_hosting

ARCHIVE = "https://tiles.clearskies.example/clearskies-la.pmtiles"
ORIGIN = "https://clearskies.up.railway.app"

# The first bytes of any PMTiles v3 archive: the magic, then the version.
HEAD_BYTES = b"PMTiles\x03" + bytes(PROBE_BYTES - 8)

GOOD_HEADERS = {
    "accept-ranges": "bytes",
    "access-control-allow-origin": ORIGIN,
    "access-control-expose-headers": "content-range, content-length, etag",
}


def server(
    *,
    head_status: int = 200,
    range_status: int = 206,
    headers: dict[str, str] | None = None,
    body: bytes = HEAD_BYTES,
) -> httpx.AsyncClient:
    """A stand-in bucket that can be broken one way at a time."""
    supplied = GOOD_HEADERS if headers is None else headers

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(head_status, headers={**supplied, "content-length": "9000"})
        served = {**supplied}
        if range_status == 206:
            served["content-range"] = f"bytes 0-{PROBE_BYTES - 1}/9000"
            return httpx.Response(206, headers=served, content=body)
        # 200 means the host ignored the Range and sent everything.
        return httpx.Response(200, headers=served, content=body + bytes(8000))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def run(**kwargs: object) -> object:
    async with server(**kwargs) as client:  # type: ignore[arg-type]
        return await check_hosting(ARCHIVE, origin=ORIGIN, client=client)


def failed(report: object) -> set[str]:
    return {check.name for check in report.failures()}  # type: ignore[attr-defined]


# ---- the happy path -------------------------------------------------------


async def test_a_correctly_configured_bucket_passes_every_check() -> None:
    report = await run()

    assert report.ok is True  # type: ignore[attr-defined]
    assert "servable" in report.summary()  # type: ignore[attr-defined]


# ---- range requests -------------------------------------------------------


async def test_a_host_that_ignores_range_is_caught() -> None:
    # The map still works. It just pulls the entire archive on every load, which
    # is invisible in a browser and visible only in a bill.
    report = await run(range_status=200)

    assert "range request" in failed(report)
    assert "the whole archive was sent" in report.summary()  # type: ignore[attr-defined]


async def test_a_missing_accept_ranges_header_is_caught() -> None:
    headers = {k: v for k, v in GOOD_HEADERS.items() if k != "accept-ranges"}
    report = await run(headers=headers)

    assert "accept-ranges" in failed(report)


async def test_an_unreachable_archive_is_caught() -> None:
    report = await run(head_status=404)

    assert "reachable" in failed(report)


# ---- CORS -----------------------------------------------------------------


async def test_a_bucket_with_no_cors_header_is_caught() -> None:
    headers = {k: v for k, v in GOOD_HEADERS.items() if k != "access-control-allow-origin"}
    report = await run(headers=headers)

    assert "cors origin" in failed(report)


async def test_a_bucket_allowing_a_different_origin_is_caught() -> None:
    # The commonest way this breaks: the policy was written for the preview
    # domain and the app moved.
    headers = {**GOOD_HEADERS, "access-control-allow-origin": "https://somewhere.else"}
    report = await run(headers=headers)

    assert "cors origin" in failed(report)


async def test_a_wildcard_origin_is_accepted() -> None:
    headers = {**GOOD_HEADERS, "access-control-allow-origin": "*"}
    report = await run(headers=headers)

    assert "cors origin" not in failed(report)


async def test_unexposed_range_headers_are_caught() -> None:
    # Content-Range is not readable cross-origin unless the bucket says so, and
    # a client that checks it fails as though the archive were corrupt.
    headers = {**GOOD_HEADERS, "access-control-expose-headers": "etag"}
    report = await run(headers=headers)

    assert "exposed headers" in failed(report)
    assert "missing content-length, content-range" in report.summary()  # type: ignore[attr-defined]


async def test_exposing_everything_is_accepted() -> None:
    headers = {**GOOD_HEADERS, "access-control-expose-headers": "*"}
    report = await run(headers=headers)

    assert "exposed headers" not in failed(report)


# ---- it really is the archive ---------------------------------------------


async def test_a_response_that_is_not_a_pmtiles_archive_is_caught() -> None:
    # A 206 stapled to an error page is still a 206.
    report = await run(body=b"<!doctype html><title>404</title>" + bytes(90))

    assert "archive header" in failed(report)


async def test_a_pmtiles_archive_of_the_wrong_version_is_caught() -> None:
    report = await run(body=b"PMTiles\x02" + bytes(PROBE_BYTES - 8))

    assert "archive header" in failed(report)


# ---- the reason it is not on the app's own origin -------------------------


async def test_an_archive_served_from_the_app_origin_is_caught() -> None:
    # The decision CS-207 turns on. An edge cache keyed on whole URLs either
    # misses on every Range request or caches the whole archive to serve a
    # kilobyte of it, and Railway bills egress where R2 does not. A URL that has
    # drifted back onto the app origin has quietly undone that.
    async with server() as client:
        report = await check_hosting(f"{ORIGIN}/tiles.pmtiles", origin=ORIGIN, client=client)

    assert "separate origin" in {check.name for check in report.failures()}


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://tiles/archive.pmtiles"])
async def test_a_url_that_is_not_an_absolute_http_url_is_refused(bad: str) -> None:
    # Almost always a mistyped VITE_TILES_URL. A sentence naming the variable
    # beats a stack trace from inside the HTTP client.
    async with server() as client:
        with pytest.raises(ValueError, match="VITE_TILES_URL"):
            await check_hosting(bad, origin=ORIGIN, client=client)
