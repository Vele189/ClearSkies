"""Methodology section 9: every indicator expressed as a Louisiana percentile.

Raw units are not comparable. A cancer risk per million, a hazard index and a
share of households below poverty cannot be averaged as they stand, and section
10 then multiplies the two components together, so every indicator is converted
to a statewide percentile before it is combined with anything else. This module
is that conversion and nothing else; the group means, the weights and the
rescaling live in the component modules.

**The formula.** For indicator `k` over the `n_k` scored hexes holding a valid
value, sorted ascending, with ties taking the mean of their ranks:

    p_k(h) = 100 · ( r_k(h) − 0.5 ) / n_k

This is the Hazen convention. Section 9 chooses it over `(r−1)/(n−1)` because
the latter assigns exactly 0 to the statewide minimum, and in a multiplicative
model a zero annihilates its whole component: one indicator at the state minimum
would drive a hex's Pollution Burden to zero regardless of the other three.
Hazen is bounded strictly inside 0 and 100 and is symmetric at both tails, which
is what `CHECK (percentile > 0 AND percentile < 100)` on `hex_indicator` in
migration 0009 encodes.

**Ties take the mean of their ranks.** That is the documented rule, and here it
is load-bearing rather than a detail. E3 and F1 through F4 are exactly zero for
every hex with no qualifying facility within 10 km, which will be a large share
of Louisiana. All of those hexes land on one percentile, and which percentile
that is depends on how many other hexes are also zero: it works out to
`50 · n_zero / n`, which `Distribution.zero_block_percentile` returns. Below
that point the indicator carries no information at all. Section 9 requires the
limitation to be published rather than smoothed over, so the zero block is
counted here and stored on `indicator_distribution` instead of being left
implicit in the percentiles themselves.

**Two exclusions, and they are not the same exclusion.**

*Not scored.* A hex with fewer than 25 estimated residents is not scored at all
(section 5). It is excluded from every percentile denominator, because ranking
against tens of thousands of uninhabited marsh cells describes where people are
not rather than how burdened a place is. `rank` takes the scored universe as a
required argument rather than trusting its callers to have filtered already: the
denominator is the thing this module exists to get right, and a caller who
forgets a filter should not be able to skew a whole distribution silently.

*No value.* A scored hex may simply have nothing to say for one indicator — no
monitor within 25 km for E4, a tract the source never covered. It stays in the
scored universe, takes no percentile, and is left out of `n_k`. It is never
imputed to zero and never to the median. Section 11 and CONTRIBUTING are both
emphatic on this and it is the failure the project exists to avoid: an
unmonitored area is uncertain, not clean, and filling it in pulls exactly the
unmonitored high-burden areas back toward the middle.

The two are distinguishable in the output. An unscored hex gets no row at all,
and a scored hex with no value gets a row with `observed` false carrying neither
value nor percentile, which is the `hex_indicator_absent_has_no_value`
constraint in migration 0009.
"""

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

# The breakpoints stored on `indicator_distribution`: the indicator's value at
# each whole percent from 0 to 100. They exist so a stored score can be
# re-derived and audited later without reloading the source data it came from,
# which is why they are a fixed ladder rather than a caller's choice — a
# distribution whose grid varied per run would not be comparable across runs.
BREAKPOINT_PERCENTS: tuple[int, ...] = tuple(range(101))


@dataclass(frozen=True, slots=True)
class RankedHex:
    """One row of `hex_indicator`: this hex's value and where it ranked.

    `observed` false means the hex is scored but this indicator had nothing for
    it. It then carries neither a value nor a percentile. Zero is an
    observation and absence is an absence; section 11 does not let the pipeline
    turn either into the other.
    """

    h3: str
    value: float | None
    percentile: float | None
    observed: bool


@dataclass(frozen=True, slots=True)
class Distribution:
    """One row of `indicator_distribution`: what the percentiles were ranked against.

    A percentile means nothing beside the distribution that produced it, so this
    is stored per run next to the values themselves.
    """

    n: int
    n_zero: int
    min_value: float | None
    max_value: float | None
    breakpoints: tuple[float, ...]

    @property
    def zero_block_percentile(self) -> float | None:
        """The one percentile every exactly-zero hex shares, or None if there are none.

        Published on the hex detail panel. For a hex with no facility within
        10 km the honest reading of F1 is "none within 10 km", not "cleaner than
        40% of Louisiana", and a reader can only tell those apart with this
        number in front of them.
        """
        if self.n == 0 or self.n_zero == 0:
            return None
        return 50.0 * self.n_zero / self.n


@dataclass(frozen=True, slots=True)
class Ranking:
    """Percentiles for one indicator, plus the distribution they came from.

    `hexes` covers the scored universe and only the scored universe, ordered by
    H3 index so that two runs over the same inputs serialize identically.
    """

    hexes: tuple[RankedHex, ...]
    distribution: Distribution
    excluded_unscored: int
    """Hexes that held a value but were not scored, so did not reach the denominator.

    Reported rather than dropped quietly: if this is zero on a statewide run
    something upstream has already filtered, and section 5 expects most of the
    grid to land here.
    """

    def by_h3(self) -> dict[str, RankedHex]:
        """Index the rows by hex. Builds a new dict, so hold it rather than re-calling."""
        return {row.h3: row for row in self.hexes}


def rank(values: Mapping[str, float | None], *, scored: Collection[str]) -> Ranking:
    """Percentile-rank one indicator across the scored hexes, per section 9.

    `values` may cover the whole grid; anything outside `scored` is counted and
    discarded. A key in `scored` that is missing from `values`, or present with
    None, is a scored hex this indicator could not speak to: it comes back
    unobserved rather than at zero.
    """
    universe = set(scored)

    ordered: list[tuple[float, str]] = []
    for h3 in universe:
        raw = values.get(h3)
        if raw is None:
            continue
        ordered.append((_finite(raw, h3), h3))

    # Sorting on (value, h3) keeps the order of tied hexes deterministic. It has
    # no effect on the percentiles themselves, which is the point of mid-ranks.
    ordered.sort()

    percentiles = _midrank_percentiles(ordered)
    sorted_values = [value for value, _ in ordered]

    rows: list[RankedHex] = []
    for h3 in sorted(universe):
        raw = values.get(h3)
        if raw is None:
            rows.append(RankedHex(h3=h3, value=None, percentile=None, observed=False))
        else:
            value = float(raw)
            rows.append(RankedHex(h3=h3, value=value, percentile=percentiles[h3], observed=True))

    excluded = sum(1 for h3, value in values.items() if value is not None and h3 not in universe)

    return Ranking(
        hexes=tuple(rows),
        distribution=_describe(sorted_values),
        excluded_unscored=excluded,
    )


def rank_indicators(
    values: Mapping[str, Mapping[str, float | None]], *, scored: Collection[str]
) -> dict[str, Ranking]:
    """Rank several indicators against one scored universe.

    The components need every indicator ranked against the same denominator, and
    threading one `scored` collection through one call is how that stays true
    when an indicator is later added or dropped.
    """
    universe = frozenset(scored)
    return {indicator_id: rank(row, scored=universe) for indicator_id, row in values.items()}


def _midrank_percentiles(ordered: Sequence[tuple[float, str]]) -> dict[str, float]:
    """Hazen percentiles over a value-sorted list, ties sharing their mean rank."""
    n = len(ordered)
    percentiles: dict[str, float] = {}

    start = 0
    while start < n:
        # Exact equality is the right test: a tie means the same float, and the
        # zero block that drives section 9's caveat is exactly 0.0.
        end = start
        while end + 1 < n and ordered[end + 1][0] == ordered[start][0]:
            end += 1

        # Ranks are 1-based, so this block holds ranks start+1 through end+1.
        mean_rank = (start + 1 + end + 1) / 2.0
        percentile = 100.0 * (mean_rank - 0.5) / n
        for index in range(start, end + 1):
            percentiles[ordered[index][1]] = percentile

        start = end + 1

    return percentiles


def _describe(sorted_values: Sequence[float]) -> Distribution:
    if not sorted_values:
        return Distribution(n=0, n_zero=0, min_value=None, max_value=None, breakpoints=())

    return Distribution(
        n=len(sorted_values),
        n_zero=sum(1 for value in sorted_values if value == 0.0),
        min_value=sorted_values[0],
        max_value=sorted_values[-1],
        breakpoints=tuple(quantile(sorted_values, percent) for percent in BREAKPOINT_PERCENTS),
    )


def quantile(sorted_values: Sequence[float], percent: float) -> float:
    """The value standing at `percent`, inverting the Hazen formula above.

    Solving `percent = 100 · (r − 0.5) / n` for the rank `r` and interpolating
    between the neighbouring order statistics, clamped to the observed range at
    both tails. Inverting the same formula the percentiles use is what makes the
    stored breakpoints agree with the stored percentiles; a different quantile
    convention here would put the two a fraction of a rank apart and leave an
    auditor unable to reproduce either from the other.
    """
    n = len(sorted_values)
    if n == 0:
        raise ValueError("no values to take a quantile of")

    rank_position = percent * n / 100.0 + 0.5
    if rank_position <= 1.0:
        return sorted_values[0]
    if rank_position >= n:
        return sorted_values[-1]

    lower = math.floor(rank_position)
    fraction = rank_position - lower
    return sorted_values[lower - 1] + fraction * (sorted_values[lower] - sorted_values[lower - 1])


def _finite(value: float, h3: str) -> float:
    """Reject NaN and infinity at the door.

    A NaN does not compare equal to itself, so it would sort unpredictably and
    quietly corrupt every percentile in the run rather than just its own. It
    would also fail the CHECK on `hex_indicator.percentile` much later, where
    nothing points back to the indicator that produced it.
    """
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"indicator value for hex {h3} is not finite: {value!r}")
    return result
