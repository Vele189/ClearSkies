import h3
from fastapi import APIRouter, HTTPException, Path

from app import db, hex_detail, runs
from app.schemas import HexDetail

router = APIRouter(tags=["hex"])

TARGET_RESOLUTION = 8


@router.get(
    "/hex/{h3_index}",
    response_model=HexDetail,
    responses={
        404: {"description": "A resolution 8 cell the current run did not score"},
        422: {"description": "Not an H3 cell index, or not resolution 8"},
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
    if not h3.is_valid_cell(h3_index):
        raise HTTPException(status_code=422, detail=f"{h3_index!r} is not a valid H3 cell index")

    resolution = h3.get_resolution(h3_index)
    if resolution != TARGET_RESOLUTION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cell is resolution {resolution}; ClearSkies scores resolution "
                f"{TARGET_RESOLUTION}. See docs/methodology.md section 5."
            ),
        )

    p = db.pool()
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
