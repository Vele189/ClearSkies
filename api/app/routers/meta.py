from fastapi import APIRouter, Depends

from app import db
from app.indicators import COMPONENT_GROUPS, GROUP_MINIMUM_PRESENT, GROUP_WEIGHTS, INDICATORS
from app.limits import enforce_read_limit
from app.methodology import METHODOLOGY_VERSION
from app.schemas import StateExtent

router = APIRouter(tags=["meta"], dependencies=[Depends(enforce_read_limit)])


@router.get("/indicators")
async def list_indicators() -> dict[str, object]:
    """The indicator set, its groups, and the weights that combine them.

    Published so a reader can check the running configuration against
    docs/methodology.md rather than taking the paper's word for it.
    """
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "indicators": [
            {
                "id": i.id,
                "name": i.name,
                "group": i.group.value,
                "unit": i.unit,
                "source": i.source,
                "description": i.description,
            }
            for i in INDICATORS
        ],
        "group_weights": {g.value: w for g, w in GROUP_WEIGHTS.items()},
        "group_minimum_present": {g.value: n for g, n in GROUP_MINIMUM_PRESENT.items()},
        "components": {c.value: [g.value for g in gs] for c, gs in COMPONENT_GROUPS.items()},
    }


#: Where each scored state's cells are. The aggregate is deliberately not on
#: /health: that is an uptime probe answered every few seconds, and a spatial
#: extent over 171,725 geometries does not belong in one.
STATE_EXTENTS = """
    SELECT st.usps,
           st.name,
           ST_X(ST_Centroid(ST_Extent(h.centroid)::geometry)) AS lon,
           ST_Y(ST_Centroid(ST_Extent(h.centroid)::geometry)) AS lat,
           ST_XMin(ST_Extent(h.centroid)) AS west,
           ST_YMin(ST_Extent(h.centroid)) AS south,
           ST_XMax(ST_Extent(h.centroid)) AS east,
           ST_YMax(ST_Extent(h.centroid)) AS north,
           count(*)                        AS cells
      FROM scored_state st
      JOIN hex h
        ON h.state_fips = st.state_fips
       AND h.centroid_in_state
     GROUP BY st.state_fips, st.usps, st.name
     ORDER BY st.state_fips
"""


@router.get("/states", response_model=list[StateExtent])
async def list_states() -> list[StateExtent]:
    """Each scored state and where its cells are.

    One row per state in `scored_state` that has a grid. A state declared but
    not yet built returns nothing rather than a marker over the empty point at
    zero degrees, which is where an aggregate over no rows would put it.
    """
    pool = await db.pool()
    if pool is None:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(STATE_EXTENTS)

    return [
        StateExtent(
            usps=row["usps"],
            name=row["name"],
            centroid=(float(row["lon"]), float(row["lat"])),
            bounds=(
                float(row["west"]),
                float(row["south"]),
                float(row["east"]),
                float(row["north"]),
            ),
            cells=row["cells"],
        )
        for row in rows
    ]
