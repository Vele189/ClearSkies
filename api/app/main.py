import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, db
from app.config import get_settings
from app.logging_config import REQUEST_ID_HEADER, RequestLogMiddleware, configure_logging
from app.routers import draft, health, hex, meta, provenance

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
log = logging.getLogger(__name__)

DESCRIPTION = """
Cumulative environmental burden scores for Louisiana, on an H3 resolution 8 grid.

Every score decomposes into the indicators that produced it and carries a
confidence value reflecting data coverage and age. Methodology, including the
pre-registered validation set, is in `docs/methodology.md`.

A high score describes modeled exposure, nearby permitted sources, and a
vulnerable population. It is not a finding of wrongdoing by any operator.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "starting",
        extra={"version": __version__, "pilot_state": settings.pilot_state},
    )
    await db.connect()
    yield
    await db.disconnect()
    log.info("stopped")


app = FastAPI(
    title="ClearSkies API",
    version=__version__,
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)

# Added last, so it sits outside CORS and times the whole exchange including a
# rejected preflight. A request refused by CORS is a request worth seeing.
app.add_middleware(RequestLogMiddleware)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(provenance.router)
app.include_router(hex.router)
app.include_router(draft.router)
