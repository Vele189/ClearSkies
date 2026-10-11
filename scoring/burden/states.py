"""Methodology section 9: one set of denominators per state.

Every indicator is ranked against the rest of its own state, and section 15 is
emphatic that the result does not travel: "A Louisiana 50th percentile hex may
be dirtier than a top-decile hex in another state." Until migration 0031 the
schema could not hold that distinction and this package did not have to make
it, because one state and "every scored hex" were the same set.

They stop being the same set the moment a second state is loaded, and the way
they stop is silent. Ranking two states together does not fail; it returns
percentiles computed against a denominator nobody asked for, and the
pre-registered criterion in section 13.2 -- eight of ten documented sites in
the *statewide* top decile -- carries on printing a pass or a fail against it.

**Nothing new is computed here.** `rank`, `compute` and `burden_score` were
already written to take their universe as an argument rather than assume one;
`percentile.rank` says so outright, and `rank`'s docstring records that values
outside the universe are "counted and discarded", which is what lets one
grid-wide `values` mapping serve every state. This module is the loop that
calls them once per state, and the only thing it adds is the insistence that
each state's hexes are ranked, rescaled and composed entirely among themselves.

**Three things are per state, and it is worth naming which.** The indicator
percentiles of section 9, obviously. The 0-to-10 rescale of section 10 step 3,
because its divisor is "the highest value anywhere in the state" -- a single
`ComponentResult` holds one `raw_max`, which is why each state gets its own
rather than the results being merged. And the score's own percentile, ranked
through the same machinery in `burden_score`.

**Confidence is not per state.** Section 12's four terms are coverage, recency,
spatial support and monitor distance. None of them is a rank, so none of them
changes with who else is in the denominator, and computing them once over the
whole grid is both cheaper and the same answer. The caller passes the one
mapping and each state takes the rows belonging to its own hexes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from burden.component import compute
from burden.confidence import HexConfidence
from burden.eligibility import eligible
from burden.percentile import Ranking, rank_indicators
from burden.pollution import POLLUTION_BURDEN
from burden.population import POPULATION_CHARACTERISTICS
from burden.score import ScoreRun, burden_score


@dataclass(frozen=True, slots=True)
class StateRun:
    """One state's slice of a run, with the denominators it was ranked against.

    `rankings` is carried rather than discarded because
    `indicator_distribution` stores one row per indicator *per state* since
    0031, and the distribution is the only thing that makes a stored percentile
    re-derivable later.
    """

    state_fips: str
    run: ScoreRun
    rankings: Mapping[str, Ranking]


def score_by_state(
    *,
    cover: Mapping[str, float | None],
    state_of: Mapping[str, str],
    values: Mapping[str, Mapping[str, float | None]],
    confidence: Mapping[str, HexConfidence] | None = None,
) -> tuple[StateRun, ...]:
    """Score each state against itself, in state_fips order.

    `cover` is the whole grid with its interpolated population, exactly as a
    single-state run passes it today. `state_of` says which state each of those
    hexes is ranked in -- `hex.state_fips`, which is the state whose grid the
    cell belongs to and not necessarily the state its centroid sits in; section
    6 builds the grid over the state plus an interaction-radius buffer, and
    `hex.centroid_in_state` is the other question.

    A hex in `cover` with no entry in `state_of` is an error rather than a hex
    quietly dropped from every denominator. Being unable to say which state a
    cell is ranked in is being unable to rank it, and a run that silently
    omitted it would produce percentiles over a denominator smaller than the
    grid it reported.

    A state whose hexes are all excluded by section 5 still comes back, with a
    run holding its exclusions and no scored rows. The grid has to account for
    every cell it knows about -- `hex_score` carries a reason for the ones it
    did not score, and the map draws them -- so dropping such a state here
    would lose rows rather than save work.
    """
    orphans = sorted(h3 for h3 in cover if h3 not in state_of)
    if orphans:
        shown = ", ".join(orphans[:5])
        more = f" and {len(orphans) - 5} more" if len(orphans) > 5 else ""
        raise ValueError(
            f"{len(orphans)} hexes have no state to be ranked in: {shown}{more}. "
            "Every hex in the cover needs a state_fips; see hex.state_fips."
        )

    runs: list[StateRun] = []
    for state_fips in sorted({state_of[h3] for h3 in cover}):
        members = {h3: people for h3, people in cover.items() if state_of[h3] == state_fips}
        eligibility = eligible(members)
        scored = eligibility.scored

        rankings = rank_indicators(values, scored=scored)
        pollution = compute(POLLUTION_BURDEN, rankings, scored=scored)
        population = compute(POPULATION_CHARACTERISTICS, rankings, scored=scored)

        runs.append(
            StateRun(
                state_fips=state_fips,
                rankings=rankings,
                run=burden_score(
                    eligibility=eligibility,
                    pollution=pollution,
                    population=population,
                    confidence=(
                        None
                        if confidence is None
                        else {h3: row for h3, row in confidence.items() if h3 in scored}
                    ),
                ),
            )
        )

    return tuple(runs)
