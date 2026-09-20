"""Where every number came from, served rather than only written down.

`docs/provenance.md` is the page a reader browses. This is the same content as
data, so the map can show it next to a hexagon instead of asking someone to open
a Markdown file in another tab. CS-406 renders it.

The endpoint reads `source_pull`, the manifest history migration 0016 adds, and
returns the most recent pull of each source. Most recent, not most recent
successful: if last night's ECHO pull failed, that is the fact the page and this
endpoint both have to publish, because a reader shown a green row from three
nights ago would reasonably conclude the data is current.
"""

from fastapi import APIRouter, HTTPException, Query

from app import db
from app.schemas import Provenance, SourceArtifact, SourceGap, SourcePull

router = APIRouter(tags=["meta"])

# The latest pull of each source. DISTINCT ON is the Postgres idiom for
# "one row per group, the newest", and it matches the source_pull_latest index.
LATEST = """
    SELECT DISTINCT ON (source)
           pull_id, run_id, source, source_title, vintage, pulled_at, status,
           records_loaded, records_rejected, notes
      FROM source_pull
     ORDER BY source, pulled_at DESC
"""

# One source's history, newest first, for a reader checking an older claim.
FOR_SOURCE = """
    SELECT pull_id, run_id, source, source_title, vintage, pulled_at, status,
           records_loaded, records_rejected, notes
      FROM source_pull
     WHERE source = $1
     ORDER BY pulled_at DESC
     LIMIT $2
"""

GAPS = """
    SELECT pull_id, scope, detail, affects, since
      FROM source_pull_gap
     WHERE pull_id = ANY($1::bigint[])
     ORDER BY pull_id, gap_id
"""

ARTIFACTS = """
    SELECT pull_id, url, sha256, retrieved_at, from_snapshot
      FROM source_pull_artifact
     WHERE pull_id = ANY($1::bigint[])
     ORDER BY pull_id, artifact_id
"""


@router.get("/provenance", response_model=Provenance)
async def get_provenance(
    source: str | None = Query(
        default=None, description="Registry name, e.g. epa_echo. Omit for the latest of each."
    ),
    limit: int = Query(default=20, ge=1, le=200, description="History length when source is given"),
) -> Provenance:
    """Every source's last pull: release, date, record count and known gaps.

    With `source`, returns that source's history newest first instead, which is
    what answers "was this number current when the claim was made".
    """
    p = db.pool()
    if p is None:
        raise HTTPException(status_code=503, detail="Database unavailable. Check GET /health.")

    async with p.acquire() as conn:
        recorded = await conn.fetchval("SELECT to_regclass('public.source_pull') IS NOT NULL")
        if not recorded:
            # The table arrives with migration 0016 and fills on the first
            # nightly run. Saying so beats an empty list, which would read as
            # "no source has ever been pulled".
            raise HTTPException(
                status_code=503,
                detail=(
                    "No provenance recorded yet. The nightly ingestion has not run "
                    "against this deployment. See GET /health."
                ),
            )

        rows = (
            await conn.fetch(FOR_SOURCE, source, limit)
            if source is not None
            else await conn.fetch(LATEST)
        )
        if source is not None and not rows:
            raise HTTPException(status_code=404, detail=f"No pull recorded for source {source!r}.")

        ids = [r["pull_id"] for r in rows]
        gaps = await conn.fetch(GAPS, ids) if ids else []
        artifacts = await conn.fetch(ARTIFACTS, ids) if ids else []

    by_pull_gaps: dict[int, list[SourceGap]] = {}
    for g in gaps:
        by_pull_gaps.setdefault(g["pull_id"], []).append(
            SourceGap(
                scope=g["scope"],
                detail=g["detail"],
                affects=list(g["affects"] or ()),
                since=g["since"],
            )
        )

    by_pull_artifacts: dict[int, list[SourceArtifact]] = {}
    for a in artifacts:
        by_pull_artifacts.setdefault(a["pull_id"], []).append(
            SourceArtifact(
                url=a["url"],
                sha256=a["sha256"],
                short_sha=a["sha256"][:12],
                retrieved_at=a["retrieved_at"],
                from_snapshot=a["from_snapshot"],
            )
        )

    return Provenance(
        sources=[
            SourcePull(
                source=r["source"],
                title=r["source_title"],
                vintage=r["vintage"],
                pulled_at=r["pulled_at"],
                status=r["status"],
                records=r["records_loaded"],
                rejected=r["records_rejected"],
                run_id=r["run_id"],
                known_gaps=by_pull_gaps.get(r["pull_id"], []),
                artifacts=by_pull_artifacts.get(r["pull_id"], []),
                notes=list(r["notes"] or ()),
            )
            for r in rows
        ]
    )
