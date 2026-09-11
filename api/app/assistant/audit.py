"""The spread of hexagons the CS-308 audit draws from.

Here rather than in `scripts/run_citation_audit.py` for the reason
`scoring/burden/validation.py` is not in `scripts/run_validation.py`: a gate's
criteria should be testable without running the gate, and a script is not
importable. The script is the CLI and the network; this is what the gate is
about.

**The hexagons are a fixture and the audit report says so.** Phase 2 has not run
against a populated database, so there is no scored cell to point at, and these
scores, confidence values and demographics are invented to span the spread the
ticket asks for: all four document types, every band down to low, and hexagons
with as few as one contributing facility.

That does not weaken the citation result, which is what the gate is about. A
citation is verified against the statute corpus and the facility table, and both
hold real rows: the statutes were fetched from govinfo and the eCFR, and the
facilities from ECHO with their own FRS registry identifiers. What it does mean
is that the drafts are about places that do not have these scores, and the audit
has to be re-run once the pipeline has loaded real data before anybody cites it
as a statement about production behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Section 12's insufficient band is absent. Such a hexagon cannot be drafted
# from at all, so including one would measure the band check rather than the
# citations, and the band check has its own tests.
DRAFTABLE_BANDS = ("high", "moderate", "low")

# Below this a hexagon counts as thin evidence. Two facilities is where a model
# has the least to work with and the most temptation to pad a document with
# something it remembers, which is the case the gate most wants covered.
THIN_FACILITIES = 2


@dataclass(frozen=True)
class Profile:
    """One hexagon in the spread, and why it is in it."""

    name: str
    band: str
    confidence: float
    score: float
    percentile: float
    facilities: int
    parish: str
    population: int
    black_pct: float
    poverty_pct: float
    note: str

    @property
    def thin(self) -> bool:
        return self.facilities <= THIN_FACILITIES


PROFILES: tuple[Profile, ...] = (
    Profile(
        "dense-corridor-high",
        "high",
        0.88,
        91.2,
        98.5,
        14,
        "St. James",
        1840,
        78.2,
        51.3,
        "The case the tool is for: many sources, high burden, well covered.",
    ),
    Profile(
        "dense-corridor-high-2",
        "high",
        0.84,
        88.7,
        97.1,
        11,
        "Ascension",
        3120,
        44.6,
        33.9,
        "The same shape in a different parish.",
    ),
    Profile(
        "industrial-moderate",
        "moderate",
        0.71,
        81.4,
        94.2,
        8,
        "Calcasieu",
        2410,
        31.5,
        38.7,
        "The common case.",
    ),
    Profile(
        "industrial-moderate-2",
        "moderate",
        0.66,
        74.9,
        88.0,
        6,
        "East Baton Rouge",
        4870,
        62.1,
        41.2,
        "Moderate confidence, urban.",
    ),
    Profile(
        "suburban-moderate",
        "moderate",
        0.63,
        58.3,
        71.4,
        4,
        "Jefferson",
        5210,
        27.8,
        24.0,
        "Middling everything, which is most of the state.",
    ),
    Profile(
        "rural-low",
        "low",
        0.44,
        62.7,
        76.9,
        2,
        "Iberville",
        890,
        55.4,
        46.8,
        "Low confidence and few sources: the band the gate asks to run down to.",
    ),
    Profile(
        "rural-low-2",
        "low",
        0.41,
        49.1,
        61.2,
        1,
        "Pointe Coupee",
        620,
        38.9,
        43.1,
        "One facility. Thin evidence, where the model is most tempted to pad.",
    ),
    Profile(
        "rural-low-sparse",
        "low",
        0.38,
        44.6,
        55.0,
        1,
        "Concordia",
        540,
        41.2,
        49.6,
        "The thinnest case that can still be drafted from.",
    ),
    Profile(
        "coastal-low",
        "low",
        0.46,
        55.8,
        68.3,
        3,
        "Plaquemines",
        1120,
        22.7,
        35.4,
        "Low confidence, with the nearest monitor a long way off.",
    ),
    Profile(
        "river-high-few",
        "high",
        0.81,
        70.2,
        85.6,
        2,
        "West Baton Rouge",
        1460,
        49.3,
        37.7,
        "Well covered and only two sources: high confidence is not high burden.",
    ),
    Profile(
        "urban-moderate-many",
        "moderate",
        0.69,
        84.0,
        95.3,
        17,
        "Orleans",
        6340,
        71.5,
        45.9,
        "The longest facility list in the set.",
    ),
    Profile(
        "northern-low",
        "low",
        0.43,
        51.4,
        63.8,
        2,
        "Ouachita",
        1980,
        58.6,
        47.3,
        "Outside the industrial corridor, where coverage is worst.",
    ),
    Profile(
        "border-moderate",
        "moderate",
        0.61,
        66.9,
        79.1,
        5,
        "Calcasieu",
        1730,
        34.2,
        39.8,
        "Section 5's case: the nearest heavy industry is across a state line.",
    ),
)


def indicators_for(profile: Profile) -> list[dict[str, Any]]:
    """Three indicators, one of which is unobserved outside the high band.

    The unobserved one is not decoration. Section 11 says a missing indicator is
    dropped rather than imputed, and a draft that quietly treats an absent
    monitor reading as a low one is the failure that rule exists to prevent. It
    should appear in the audit, so it appears in the fixture.
    """
    return [
        {
            "id": "E1",
            "name": "Modelled air toxics cancer risk",
            "value": round(20 + profile.percentile * 0.5, 1),
            "unit": "per million",
            "percentile": profile.percentile,
            "source": "AirToxScreen",
            "observed": True,
        },
        {
            "id": "E2",
            "name": "PM2.5 annual mean",
            "value": round(7 + profile.percentile / 40, 1),
            "unit": "ug/m3",
            "percentile": max(profile.percentile - 15, 5.0),
            "source": "AirToxScreen",
            "observed": True,
        },
        {
            "id": "E4",
            "name": "Monitored NO2",
            "value": 11.4 if profile.band == "high" else None,
            "unit": "ppb",
            "percentile": 48.0 if profile.band == "high" else None,
            "source": "OpenAQ",
            "observed": profile.band == "high",
        },
    ]


def facilities_for(
    profile: Profile, facilities: list[dict[str, Any]], index: int
) -> list[dict[str, Any]]:
    """Real facilities, as many as this profile calls for.

    A rotating window rather than the same first few every time, so fifty drafts
    do not all cite one facility and the audit says something about more than
    one row in the table.
    """
    if not facilities:
        return []
    start = (index * profile.facilities) % len(facilities)
    doubled = facilities + facilities
    window = doubled[start : start + profile.facilities]
    return [
        {
            "name": row["name"],
            "registry_id": row["registry_id"],
            "distance_km": round(1.5 + i * 1.3, 1),
            "program": "CAA Title V" if row["has_title_v"] else "CAA major source",
        }
        for i, row in enumerate(window)
    ]


def plan(count: int, types: list[str]) -> list[tuple[Profile, str, int]]:
    """Which hexagon and document type each of `count` drafts covers.

    Profiles and types advance independently so the two cycles do not lock into
    step and leave a band paired with only one document type, which is what a
    single index would do with thirteen profiles and four types.
    """
    return [(PROFILES[i % len(PROFILES)], types[i % len(types)], i) for i in range(count)]
