from fastapi import APIRouter

from app.indicators import COMPONENT_GROUPS, GROUP_MINIMUM_PRESENT, GROUP_WEIGHTS, INDICATORS
from app.methodology import METHODOLOGY_VERSION

router = APIRouter(tags=["meta"])


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
