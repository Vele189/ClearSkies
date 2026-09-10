"""The fifteen indicators defined in docs/methodology.md section 8.

This registry is the single place the indicator set is declared. The API, the
scoring engine, and the frontend all read names, units, and group membership
from here, so adding an indicator to the methodology means editing one list.

Group weights come from section 10:
    exposures              1.0
    environmental_effects  0.5
    sensitive_populations  1.0
    socioeconomic_factors  1.0

Subgroup means are averaged, not pooled. See section 10 for why.
"""

from dataclasses import dataclass
from enum import StrEnum


class Group(StrEnum):
    EXPOSURES = "exposures"
    ENVIRONMENTAL_EFFECTS = "environmental_effects"
    SENSITIVE_POPULATIONS = "sensitive_populations"
    SOCIOECONOMIC_FACTORS = "socioeconomic_factors"


class Component(StrEnum):
    POLLUTION_BURDEN = "pollution_burden"
    POPULATION_CHARACTERISTICS = "population_characteristics"


GROUP_WEIGHTS: dict[Group, float] = {
    Group.EXPOSURES: 1.0,
    Group.ENVIRONMENTAL_EFFECTS: 0.5,
    Group.SENSITIVE_POPULATIONS: 1.0,
    Group.SOCIOECONOMIC_FACTORS: 1.0,
}

COMPONENT_GROUPS: dict[Component, tuple[Group, ...]] = {
    Component.POLLUTION_BURDEN: (Group.EXPOSURES, Group.ENVIRONMENTAL_EFFECTS),
    Component.POPULATION_CHARACTERISTICS: (
        Group.SENSITIVE_POPULATIONS,
        Group.SOCIOECONOMIC_FACTORS,
    ),
}

# Minimum indicators required for a group to be computable (section 11, rule 2).
GROUP_MINIMUM_PRESENT: dict[Group, int] = {
    Group.EXPOSURES: 2,
    Group.ENVIRONMENTAL_EFFECTS: 2,
    Group.SENSITIVE_POPULATIONS: 1,
    Group.SOCIOECONOMIC_FACTORS: 4,
}


@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    group: Group
    unit: str
    source: str
    description: str


INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        "E1",
        "Air toxics cancer risk",
        Group.EXPOSURES,
        "risk per million",
        "EPA AirToxScreen",
        "Modeled lifetime cancer risk from inhalation of air toxics.",
    ),
    Indicator(
        "E2",
        "Air toxics respiratory hazard",
        Group.EXPOSURES,
        "hazard index",
        "EPA AirToxScreen",
        "Modeled respiratory hazard index from air toxics.",
    ),
    Indicator(
        "E3",
        "Toxic release proximity",
        Group.EXPOSURES,
        "weighted lb/km2",
        "EPA TRI",
        "Toxicity-weighted on-site air releases, inverse-square distance decay, 10 km cutoff.",
    ),
    Indicator(
        "E4",
        "Measured PM2.5",
        Group.EXPOSURES,
        "ug/m3",
        "OpenAQ",
        "Annual mean of daily PM2.5. Missing, never zero, beyond 25 km from a monitor.",
    ),
    Indicator(
        "F1",
        "Major source proximity",
        Group.ENVIRONMENTAL_EFFECTS,
        "weighted count",
        "EPA ECHO",
        "Distance-decayed count of Clean Air Act major sources and Title V permits.",
    ),
    Indicator(
        "F2",
        "Non-compliance burden",
        Group.ENVIRONMENTAL_EFFECTS,
        "weighted count",
        "EPA ECHO",
        "Distance-decayed facility-quarters in non-compliance over 12 quarters.",
    ),
    Indicator(
        "F3",
        "Enforcement burden",
        Group.ENVIRONMENTAL_EFFECTS,
        "weighted count",
        "EPA ECHO",
        "Distance-decayed formal enforcement actions over 5 years, log-scaled penalties.",
    ),
    Indicator(
        "F4",
        "Hazardous waste proximity",
        Group.ENVIRONMENTAL_EFFECTS,
        "weighted count",
        "EPA ECHO",
        "Distance-decayed count of RCRA large-quantity generators and TSD facilities.",
    ),
    Indicator(
        "S1",
        "Young children",
        Group.SENSITIVE_POPULATIONS,
        "percent",
        "US Census ACS",
        "Share of population under 5.",
    ),
    Indicator(
        "S2",
        "Older adults",
        Group.SENSITIVE_POPULATIONS,
        "percent",
        "US Census ACS",
        "Share of population 65 and over.",
    ),
    Indicator(
        "P1",
        "Poverty",
        Group.SOCIOECONOMIC_FACTORS,
        "percent",
        "US Census ACS",
        "Share of population below 200 percent of the federal poverty level.",
    ),
    Indicator(
        "P2",
        "Educational attainment",
        Group.SOCIOECONOMIC_FACTORS,
        "percent",
        "US Census ACS",
        "Share of adults 25+ without a high school diploma.",
    ),
    Indicator(
        "P3",
        "Linguistic isolation",
        Group.SOCIOECONOMIC_FACTORS,
        "percent",
        "US Census ACS",
        "Share of limited-English-speaking households.",
    ),
    Indicator(
        "P4",
        "Unemployment",
        Group.SOCIOECONOMIC_FACTORS,
        "percent",
        "US Census ACS",
        "Share of the civilian labour force unemployed.",
    ),
    Indicator(
        "P5",
        "Housing cost burden",
        Group.SOCIOECONOMIC_FACTORS,
        "percent",
        "US Census ACS",
        "Share of low-income households paying over 50 percent of income on housing.",
    ),
)

BY_ID: dict[str, Indicator] = {i.id: i for i in INDICATORS}


def in_group(group: Group) -> tuple[Indicator, ...]:
    return tuple(i for i in INDICATORS if i.group is group)
