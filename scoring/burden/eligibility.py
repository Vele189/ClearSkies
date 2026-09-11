"""Methodology section 5: which hexes are scored at all.

    Hexes with an estimated population below 25 are not scored. They receive a
    `no_score` status with reason `low_population`, and they are excluded from
    every percentile denominator.

This runs before anything else in a scoring run, because it decides the
denominator every indicator is ranked against. Section 9's percentiles, both
component scores and the final burden score are all computed over the set this
module returns, so getting it wrong does not produce a few bad hexes — it
shifts every percentile in the state.

**Why the threshold exists.** Louisiana's grid is roughly 150,000 populated
hexagons inside a far larger cover that includes the Atchafalaya Basin, coastal
marsh and open water out to the state line. Those cells have modeled
AirToxScreen values like anywhere else, so they would rank perfectly happily.
Ranking them would mean a hex in Baton Rouge is being told where it stands
relative to tens of thousands of uninhabited swamp cells, which describes where
people are not rather than how burdened a place is. Section 5 puts it plainly:
scoring an uninhabited cell distorts the distribution and means nothing.

**An absent population estimate is an unpopulated cell.** CS-106's interpolation
returns `no_population` for a hex when every contributing overlap held zero
population, and `interpolate.py` already reads that as an unpopulated cell that
section 11 leaves unscored. This module follows that reading rather than
inventing a second one: no estimate and an estimate of nought reach the same
place, `low_population`.

**A population that is not a number is a bug, not a small population.** A NaN
compares false against every threshold, so it would sail through the filter and
into a denominator. It is refused here, where the hex that produced it is still
in hand.

`outside_pilot_state` is the other section 5 exclusion, for hexes whose centroid
falls outside Louisiana. It belongs to CS-204, which builds the grid cover; this
module is handed the hexes that survived that test.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

# Section 5. Not a tunable: moving it changes every percentile in the state, so
# it moves in docs/methodology.md first, with an entry in that document's
# changelog.
MINIMUM_POPULATION = 25.0

# The four reasons `hex_score.no_score_reason` accepts, per migration 0009. A
# hex without a score reports which one applies rather than a bare null.
NoScoreReason = Literal[
    "low_population",
    "insufficient_pollution_data",
    "insufficient_population_data",
    "outside_pilot_state",
]


@dataclass(frozen=True, slots=True)
class ExcludedHex:
    """A hex the run will not score, and why.

    The population is carried so the detail panel can say "21 estimated
    residents" rather than only "not scored", which is the difference between a
    reader trusting the map and filing a bug about a hole in it.
    """

    h3: str
    reason: NoScoreReason
    population: float | None


@dataclass(frozen=True, slots=True)
class Eligibility:
    """The scored universe of one run, and the hexes kept out of it."""

    scored: tuple[str, ...]
    excluded: tuple[ExcludedHex, ...]

    def reasons(self) -> dict[str, NoScoreReason]:
        """Excluded hexes indexed by hex, for the `no_score_reason` column."""
        return {row.h3: row.reason for row in self.excluded}


def eligible(population: Mapping[str, float | None]) -> Eligibility:
    """Split the grid into the hexes section 5 scores and the ones it does not.

    `population` is the whole grid cover: every hex the run knows about, with
    its dasymetric population estimate from CS-106 or None where the estimate is
    absent. The returned `scored` tuple is what every percentile denominator and
    both components are computed over.
    """
    scored: list[str] = []
    excluded: list[ExcludedHex] = []

    for h3 in sorted(population):
        people = population[h3]

        if people is not None and not math.isfinite(people):
            raise ValueError(f"population estimate for hex {h3} is not finite: {people!r}")

        if people is None or people < MINIMUM_POPULATION:
            excluded.append(ExcludedHex(h3=h3, reason="low_population", population=people))
        else:
            scored.append(h3)

    return Eligibility(scored=tuple(scored), excluded=tuple(excluded))
