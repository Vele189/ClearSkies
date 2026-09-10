import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, db
from app.config import get_settings
from app.routers import health, hex, meta

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

DESCRIPTION = """
Cumulative environmental burden scores for Louisiana, on an H3 resolution 8 grid.

Every score decomposes into the indicators that produced it and carries a
confidence value reflecting data coverage and age. Methodology, including the
pre-registered validation set, is in `docs/methodology.md`.

A high score describes modeled exposure, nearby permitted sources, and a
vulnerable population. It is not a finding of wrongdoing by any operator.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


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
)

app.include_router(health.router)
app.include_router(meta.router)
app.include_router(hex.router)
