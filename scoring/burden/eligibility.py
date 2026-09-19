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

**The other section 5 exclusion is the state line.** The grid covers Louisiana's
land area plus coastal water out to the boundary, and a hex straddling the line
is included only if its centroid falls inside. That test is geometry and is done
upstream, where PostGIS and the grid cover are; what arrives here is the list of
hexes that failed it, and they leave with `outside_pilot_state`. The reason wins
over `low_population` when both would apply, because a cell in Mississippi is
not a Louisiana cell that happens to be empty, and calling it one would invite
the question of why the pilot is scoring Mississippi at all.

Facility contributions from out-of-state sources still count toward hexes inside
the line, per section 5. Excluding a hex from scoring and ignoring the plant next
to it are different things, and only the first happens here.
"""

import math
from collections.abc import Collection, Mapping
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


def eligible(
    population: Mapping[str, float | None],
    *,
    outside_pilot_state: Collection[str] = (),
) -> Eligibility:
    """Split the grid into the hexes section 5 scores and the ones it does not.

    `population` is the whole grid cover: every hex the run knows about, with
    its dasymetric population estimate from CS-106 or None where the estimate is
    absent. `outside_pilot_state` names the hexes whose centroid falls outside
    Louisiana, decided upstream where the geometry is. The returned `scored`
    tuple is what every percentile denominator and both components are computed
    over.
    """
    outside = set(outside_pilot_state)
    scored: list[str] = []
    excluded: list[ExcludedHex] = []

    for h3 in sorted(set(population) | outside):
        people = population.get(h3)

        # Tested before the threshold, and before the finiteness check: a cell
        # across the state line is out of scope whatever its population says,
        # and a bad estimate there is not this run's problem to report.
        if h3 in outside:
            excluded.append(ExcludedHex(h3=h3, reason="outside_pilot_state", population=people))
            continue

        if people is not None and not math.isfinite(people):
            raise ValueError(f"population estimate for hex {h3} is not finite: {people!r}")

        if people is None or people < MINIMUM_POPULATION:
            excluded.append(ExcludedHex(h3=h3, reason="low_population", population=people))
        else:
            scored.append(h3)

    return Eligibility(scored=tuple(scored), excluded=tuple(excluded))
