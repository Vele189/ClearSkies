from fastapi import APIRouter

from app import __version__, db
from app.config import get_settings
from app.schemas import ExtensionStatus, Health

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
async def health() -> Health:
    """Liveness plus a report of which Postgres extensions are actually present.

    The extension list is the cheap way to prove a deploy is running the custom
    image from infra/postgres rather than a stock Postgres, which is the single
    most likely thing to be silently wrong about this stack.
    """
    settings = get_settings()
    p = db.pool()

    if p is None:
        return Health(
            status="degraded",
            version=__version__,
            pilot_state=settings.pilot_state,
            database="unavailable",
            extensions=[],
            notes=["Database pool not established. Scores and drill-down are unavailable."],
        )

    notes: list[str] = []
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT name, version FROM clearskies_extensions")
        scored = await conn.fetchval("SELECT to_regclass('public.hex_score') IS NOT NULL")
        count = await conn.fetchval("SELECT count(*) FROM hex_score") if scored else None

    extensions = [ExtensionStatus(name=r["name"], version=r["version"]) for r in rows]
    present = {e.name for e in extensions}
    for required in ("postgis", "h3", "vector"):
        if required not in present:
            notes.append(f"Extension {required!r} is missing from this database.")

    if count is None:
        notes.append("No hex_score table yet. The Phase 1 pipeline has not run.")
    elif count == 0:
        notes.append("hex_score is empty. The Phase 1 pipeline has not loaded the pilot state.")

    return Health(
        status="ok" if not notes else "degraded",
        version=__version__,
        pilot_state=settings.pilot_state,
        database="connected",
        extensions=extensions,
        scored_hexes=count,
        notes=notes,
    )
