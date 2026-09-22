"""One provider client for the process, built once and closed on shutdown.

`/draft` used to construct an `AsyncOpenAI` per request and never close it. Each
one carries its own `httpx` client, connection pool and TLS session, so every
draft paid a fresh handshake to the provider and left a pool behind for the
garbage collector to close whenever it got round to it -- which, under load, is
a slow leak of sockets rather than a crash.

The client is built lazily rather than in the lifespan, because the API is
required to start with no `OPENAI_API_KEY` and report the drafting endpoint as
unavailable. Building it on first use keeps that property and keeps the key in
one place: the typed settings object, which reads `.env` as well as the
environment. A client built by the provider's own inference reads
`os.environ` directly and would miss a key configured the way this project
documents.

Closing is not lazy. The lifespan closes whatever was built, so the sockets go
when the process does rather than when the interpreter feels like it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

_client: Any | None = None


def client() -> Any:
    """The process's `AsyncOpenAI`, built on first use.

    Imported inside the function: the SDK is only needed by the one endpoint
    that drafts, and importing it at module scope would put it on the critical
    path of a process that may never draft anything.
    """
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _client


async def close() -> None:
    """Release the client's connection pool. Safe to call when none was built."""
    global _client
    if _client is None:
        return
    try:
        await _client.close()
    except Exception as exc:  # noqa: BLE001 - shutdown must not fail on a closed socket
        log.warning("closing the provider client failed: %s", exc)
    finally:
        _client = None
