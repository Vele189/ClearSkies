from fastapi import APIRouter, Depends, HTTPException, Path

from app import db, h3_cell, hex_detail, runs
from app.limits import enforce_read_limit
from app.schemas import HexDetail

# One database query per hexagon opened, so the limit is on the router
# rather than on the handler: a limit somebody has to remember to add to
# the next endpoint is one the next endpoint will not have.
router = APIRouter(tags=["hex"], dependencies=[Depends(enforce_read_limit)])


@router.get(
    "/hex/{h3_index}",
    response_model=HexDetail,
    responses={
        404: {"description": "A resolution 8 cell the current run did not score"},
        422: {"description": "Not a canonical H3 cell index, or not resolution 8"},
        503: {"description": "No run has been promoted, or the database is unreachable"},
    },
)
async def get_hex(
    h3_index: str = Path(description="H3 cell index at resolution 8, e.g. 88444600ddfffff"),
) -> HexDetail:
    """Everything behind one hexagon's score.

    Returns the same payload the map panel renders: the score, both components,
    every indicator with its percentile and whether it was observed or dropped,
    the confidence breakdown, the contributing facilities, and the demographic
    profile that is displayed but never scored.

    A hexagon the run examined and could not score comes back 200 with `score`
    null and `no_score_reason` set, because "too few people live here to score"
    is an answer. 404 is reserved for a cell the run holds nothing about at all.
    """
    try:
        h3_cell.validate(h3_index)
    except h3_cell.InvalidCell as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    p = await db.pool()
    if p is None:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Check GET /health.",
        )

    async with p.acquire() as conn:
        run = await runs.current(conn)
        if run is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "No scored data yet. The Phase 1 ingestion and Phase 2 scoring steps "
                    "have not run for this deployment. See GET /health."
                ),
            )

        detail = await hex_detail.load(conn, h3_index, run)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"No scored hex {h3_index} in the pilot state.",
        )

    return detail
