"""Crossing census tract vintages, for sources published on 2010 geography.

AirToxScreen's 2019 assessment is published on 2010 census tracts. Everything
else in this project is keyed to the 2020 set: the ACS release CS-105 loads, the
blocks CS-112 loads, the crosswalk section 7 builds from them, and the foreign
key `tract_exposure.tract_geoid` carries. All 1,128 Louisiana tracts in the
AirToxScreen file exist in the 2010 set and 273 of them do not exist in the 2020
one, so the join is across vintages and a quarter of the state vanishes if it is
attempted directly.

The AirToxScreen adapter's own docstring says where the fix belongs: "Reconciling
the two needs a Census tract relationship file and belongs with the geography
loader, not here." This is that module.

**One translation, applied early.** A source's values are re-keyed from 2010
tracts onto 2020 tracts before anything else sees them. Downstream nothing
changes: `tract_exposure` satisfies its foreign key, and the 2020-keyed crosswalk
already built carries the values to hexagons with no second mapping. The
alternative — composing a 2010-tract-to-hex crosswalk and dropping the foreign
key — would leave two tract vintages live in one database and every later join
would have to know which it was looking at.

**The weight is shared land area, and that is an approximation.** Section 7
combines intensive quantities as a *population*-weighted mean, and modelled risk
per million is intensive. Weighting by population here would need the population
of each 2010/2020 overlap piece, which needs the block layer at both vintages;
only the 2020 blocks were ever loaded, and CS-112 discards them once the
crosswalk is built. The relationship file publishes shared land area, so that is
what this uses.

Where the two disagree is where population density varies sharply *within* the
overlap between an old tract and a new one — which is exactly where tracts get
redrawn, so the error is not randomly placed. It is recorded here rather than
buried: `Translation.area_weighted` is always true today, and a caller that
wants the population-weighted version should say so rather than assume this one
is it. Any use of E1 or E2 inherits this approximation.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

__all__ = [
    "RELATIONSHIP_URL",
    "TractRelationship",
    "Translation",
    "parse_relationship",
    "rekey_intensive",
]

#: The Census 2020-to-2010 tract relationship file. One row per pair of tracts
#: that overlap, with the land and water area they share. National, pipe
#: delimited, and about 126,000 rows; callers filter by state.
RELATIONSHIP_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt"
)

_GEOID_20 = "GEOID_TRACT_20"
_GEOID_10 = "GEOID_TRACT_10"
_SHARED_LAND = "AREALAND_PART"


@dataclass(frozen=True, slots=True)
class TractRelationship:
    """Which 2010 tracts each 2020 tract is made of, and in what proportion."""

    #: 2020 tract -> ((2010 tract, shared land area in m²), ...)
    parts: Mapping[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)

    def tracts_2020(self) -> tuple[str, ...]:
        return tuple(sorted(self.parts))

    def tracts_2010(self) -> tuple[str, ...]:
        return tuple(sorted({old for parts in self.parts.values() for old, _ in parts}))


@dataclass(frozen=True, slots=True)
class Translation:
    """Values re-keyed onto 2020 tracts, and what the crossing cost.

    `unmatched` is the 2010 tracts the relationship file never mentions, and
    `uncovered` the 2020 tracts no source value reached. Both are counted rather
    than dropped: a source that silently covers three quarters of a state is the
    failure this whole module exists to prevent.
    """

    values: Mapping[str, float]
    unmatched: tuple[str, ...] = ()
    uncovered: tuple[str, ...] = ()
    area_weighted: bool = True

    def summary(self) -> str:
        return (
            f"{len(self.values)} of {len(self.values) + len(self.uncovered)} 2020 tracts "
            f"carry a value after crossing from 2010 geography"
            + (
                f"; {len(self.unmatched)} source tracts had no 2020 counterpart"
                if self.unmatched
                else ""
            )
            + ". Weighted by shared land area, not population: see pipeline.tract_vintage."
        )


def parse_relationship(lines: Iterator[str], *, state_fips: str) -> TractRelationship:
    """The relationship file as a 2020-to-2010 mapping, for one state.

    Streamed line by line because the national file is large and only one
    state's rows are ever wanted. A row whose shared land area is zero is
    dropped: two tracts can touch along a boundary and share no area, and such a
    pair carries no value from one to the other.
    """
    header: list[str] | None = None
    parts: dict[str, list[tuple[str, float]]] = {}

    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if header is None:
            header = line.lstrip("﻿").split("|")
            continue

        fields = line.split("|")
        if len(fields) != len(header):
            continue

        row = dict(zip(header, fields, strict=True))
        new = row.get(_GEOID_20, "")
        if not new.startswith(state_fips):
            continue
        old = row.get(_GEOID_10, "")
        try:
            shared = float(row.get(_SHARED_LAND) or 0.0)
        except ValueError:
            continue
        if not old or shared <= 0:
            continue
        parts.setdefault(new, []).append((old, shared))

    return TractRelationship(
        parts={new: tuple(sorted(items)) for new, items in sorted(parts.items())}
    )


def rekey_intensive(values: Mapping[str, float], relationship: TractRelationship) -> Translation:
    """Move an intensive quantity from 2010 tracts onto 2020 tracts.

    Intensive: a rate, a risk per million, an index. It does not sum across
    space, so a 2020 tract's value is the mean of the 2010 tracts it is made of,
    weighted by how much land it takes from each — not their total.

    A 2020 tract whose source tracts all lack a value gets none, rather than a
    mean over the ones that happen to be present. Partial coverage of a redrawn
    tract is a value that describes somewhere else.
    """
    out: dict[str, float] = {}
    uncovered: list[str] = []

    for new, items in relationship.parts.items():
        weighted = 0.0
        total = 0.0
        for old, area in items:
            value = values.get(old)
            if value is None:
                continue
            weighted += value * area
            total += area
        if total > 0:
            out[new] = weighted / total
        else:
            uncovered.append(new)

    known = set(relationship.tracts_2010())
    unmatched = tuple(sorted(set(values) - known))
    return Translation(
        values=out,
        unmatched=unmatched,
        uncovered=tuple(sorted(uncovered)),
        area_weighted=True,
    )


def relationship_from_text(payload: str, *, state_fips: str) -> TractRelationship:
    """Convenience for a whole file already in memory."""
    return parse_relationship(iter(payload.splitlines()), state_fips=state_fips)
