from fastapi import APIRouter

from app import __version__, db
from app.schemas import ExtensionStatus, Health, ScoredState

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=Health)
async def health() -> Health:
    """Liveness plus a report of which Postgres extensions are actually present.

    The extension list is the cheap way to prove a deploy is running the custom
    image from infra/postgres rather than a stock Postgres, which is the single
    most likely thing to be silently wrong about this stack.
    """
    p = await db.pool()

    if p is None:
        # No scored_states, because the list is read from the database and this
        # is the branch where there isn't one. Reporting the configured value
        # instead is how a deploy claims coverage it cannot serve.
        return Health(
            status="degraded",
            version=__version__,
            database="unavailable",
            extensions=[],
            notes=["Database pool not established. Scores and drill-down are unavailable."],
        )

    notes: list[str] = []
    async with p.acquire() as conn:
        rows = await conn.fetch("SELECT name, version FROM clearskies_extensions")
        scored = await conn.fetchval("SELECT to_regclass('public.hex_score') IS NOT NULL")
        # The current run's own count of the cells it ranked. Counting hex_score
        # instead adds up every run ever kept, which grows with each re-score
        # and is not a number of anything a reader can see on the map.
        current = (
            await conn.fetchrow("SELECT scored_hexes FROM pipeline_run WHERE is_current")
            if scored
            else None
        )
        count = (current["scored_hexes"] or 0) if current is not None else (0 if scored else None)
        # Which states this deployment ranks hexes within. Ordered by FIPS so
        # the list is stable between calls rather than by insertion.
        states = await conn.fetch("SELECT usps, name FROM scored_state ORDER BY state_fips")

    extensions = [ExtensionStatus(name=r["name"], version=r["version"]) for r in rows]
    present = {e.name for e in extensions}
    for required in ("postgis", "h3", "vector"):
        if required not in present:
            notes.append(f"Extension {required!r} is missing from this database.")

    if not states:
        # Section 9 ranks within a state, so a database with none declared
        # cannot produce a percentile that means anything.
        notes.append("No state is declared scored. Nothing can be ranked.")

    if count is None:
        notes.append("No hex_score table yet. The Phase 1 pipeline has not run.")
    elif current is None:
        notes.append("No scoring run has been promoted, so there are no scores to serve.")
    elif count == 0:
        notes.append("The current run scored no hexes.")

    return Health(
        status="ok" if not notes else "degraded",
        version=__version__,
        scored_states=[ScoredState(usps=r["usps"], name=r["name"]) for r in states],
        database="connected",
        extensions=extensions,
        scored_hexes=count,
        notes=notes,
    )
