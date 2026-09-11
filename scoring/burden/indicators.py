"""The part of the indicator registry the scoring package needs.

`api/app/indicators.py` is the registry of record for the fifteen indicators,
their groups and their weights, and it is locked to methodology section 8. The
scoring package cannot import it: `api` and `scoring` are separate
distributions with separate dependency sets, which is what lets the API deploy
without a scoring engine and lets this package declare no dependencies at all.

So the small part of that registry the components need is restated here, and
`tests/test_indicators.py::test_the_registry_matches_the_api` loads the API
module off disk and fails the moment the two disagree. The same arrangement is
already in `etl/pipeline/quality/cross.py` for the same reason.

Nothing here decides anything. Adding an indicator or changing a weight is a
methodology change argued in `docs/methodology.md` and applied to the registry of
record; this file follows, and the drift guard is what makes "follows" a fact
rather than an intention.
"""

from dataclasses import dataclass

# Section 8: which indicators belong to which group.
GROUP_INDICATORS: dict[str, tuple[str, ...]] = {
    "exposures": ("E1", "E2", "E3", "E4"),
    "environmental_effects": ("F1", "F2", "F3", "F4"),
    "sensitive_populations": ("S1", "S2"),
    "socioeconomic_factors": ("P1", "P2", "P3", "P4", "P5"),
}

# Section 10: Environmental Effects counts for half of what Exposures does. The
# two Population Characteristics groups count equally.
GROUP_WEIGHTS: dict[str, float] = {
    "exposures": 1.0,
    "environmental_effects": 0.5,
    "sensitive_populations": 1.0,
    "socioeconomic_factors": 1.0,
}

# Section 11 rule 2: how many of a group's indicators must be present before the
# group mean means anything.
GROUP_MINIMUM_PRESENT: dict[str, int] = {
    "exposures": 2,
    "environmental_effects": 2,
    "sensitive_populations": 1,
    "socioeconomic_factors": 4,
}


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """One subgroup as the aggregation in section 10 needs it."""

    group: str
    indicators: tuple[str, ...]
    weight: float
    minimum_present: int


def group_spec(group: str) -> GroupSpec:
    return GroupSpec(
        group=group,
        indicators=GROUP_INDICATORS[group],
        weight=GROUP_WEIGHTS[group],
        minimum_present=GROUP_MINIMUM_PRESENT[group],
    )
