"""The rate limits the routers depend on, as FastAPI dependencies.

`app/rate_limit.py` holds the window and what it does not promise. This is
where a limit is attached to an endpoint, kept apart from the drafting router
so that the read endpoints do not import the one that spends money.
"""

import math

from fastapi import HTTPException, Request

from app import rate_limit
from app.config import get_settings

#: Named so the two limits count separately. A reader who has been clicking
#: around the map has not used up their drafts.
READ = "read"


def _key(request: Request) -> str:
    return rate_limit.client_key(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )


def enforce_read_limit(request: Request) -> None:
    """429 with a Retry-After, or nothing at all.

    Applied to the endpoints that read the database. Deliberately **not**
    applied to `/health`: the uptime check polls it, a limited health check
    would page the operator about a rate limit rather than an outage, and it is
    the one endpoint that must answer when everything else is refusing.
    """
    settings = get_settings()
    window = rate_limit.window_for(READ, settings.read_rate_limit, settings.read_rate_window_s)
    wait = window.check(_key(request))
    if wait is None:
        return

    seconds = max(int(math.ceil(wait)), 1)
    raise HTTPException(
        status_code=429,
        detail=(
            f"Too many requests from this client. This deployment allows "
            f"{window.limit} read requests every {int(window.window_s)} seconds, so "
            f"that one client cannot exhaust the database for everyone else. The "
            f"data is public and there is no quota on how much of it you may have; "
            f"try again in {seconds} seconds, or more slowly."
        ),
        headers={"Retry-After": str(seconds)},
    )
