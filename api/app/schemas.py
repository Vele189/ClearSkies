"""Response models.

Shapes mirror docs/methodology.md so that what the map panel renders and what
the API returns are the same object. Every score carries the indicators that
produced it and the confidence attached to it; there is no endpoint that hands
back a bare number.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.indicators import Component, Group

ConfidenceBand = Literal["high", "moderate", "low", "insufficient"]
NoScoreReason = Literal[
    "low_population",
    "insufficient_pollution_data",
    "insufficient_population_data",
    "outside_pilot_state",
]


class IndicatorValue(BaseModel):
    id: str = Field(description="Indicator id from docs/methodology.md section 8, e.g. E1")
    name: str
    group: Group
    value: float | None = Field(description="Raw value in the indicator's native unit")
    unit: str
    percentile: float | None = Field(description="Statewide percentile rank, 0 to 100")
    source: str
    observed: bool = Field(
        description="False when the indicator was absent and dropped from its group mean. "
        "Absent indicators are never imputed. See methodology section 11."
    )


class GroupScore(BaseModel):
    group: Group
    mean_percentile: float | None
    weight: float
    indicators_present: int
    indicators_required: int
    computable: bool


class ComponentScore(BaseModel):
    component: Component
    score: float = Field(description="Rescaled to 0 to 10, see methodology section 10")
    groups: list[GroupScore]


class Confidence(BaseModel):
    value: float = Field(ge=0.0, le=1.0)
    band: ConfidenceBand
    coverage: float
    recency: float
    spatial_support: float
    monitor_support: float
    nearest_monitor_km: float | None


class Facility(BaseModel):
    registry_id: str = Field(description="EPA FRS registry identifier")
    name: str
    distance_km: float
    program: str = Field(description="e.g. CAA Title V, RCRA, TRI")
    echo_url: str
    in_hex: bool = Field(
        default=False,
        description="True when this hexagon is the one containing the facility, rather than "
        "merely within the 10 km interaction radius. Methodology section 8.1.",
    )
    quarters_in_noncompliance: int | None = None
    formal_actions_5yr: int | None = None


class Demographics(BaseModel):
    """Recorded and displayed, never an input to the score.

    Methodology section 14 argues this at length: keeping race out of the
    arithmetic is what makes the disparity finding an independent result.
    """

    population: int
    under_5_pct: float | None = None
    over_64_pct: float | None = None
    poverty_200pct: float | None = None
    black_pct: float | None = None
    people_of_color_pct: float | None = None
    hispanic_pct: float | None = None


class HexDetail(BaseModel):
    h3: str
    resolution: int
    state: str
    parish: str | None
    centroid: tuple[float, float] = Field(description="lon, lat")

    score: float | None = Field(description="Pollution burden times vulnerability, 0 to 100")
    percentile: float | None = Field(description="Statewide percentile of the score")
    components: list[ComponentScore]
    indicators: list[IndicatorValue]
    confidence: Confidence
    demographics: Demographics
    facilities: list[Facility]

    no_score_reason: NoScoreReason | None = None
    methodology_version: str
    data_vintage: dict[str, str] = Field(
        default_factory=dict, description="Source name to release identifier"
    )


class ExtensionStatus(BaseModel):
    name: str
    version: str


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    pilot_state: str
    database: Literal["connected", "unavailable"]
    extensions: list[ExtensionStatus]
    scored_hexes: int | None = None
    notes: list[str] = Field(default_factory=list)
