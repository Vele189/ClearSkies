"""Methodology section 10, steps 1 to 3: subgroup means into one component.

Both components are built the same way out of different parts, so the assembly
lives here once and `pollution.py` and `population.py` supply the parts. The
shape is section 10:

    step 1  within each group, average the percentiles of the indicators that
            have a value for this hex
    step 2  combine the group means, weighted
    step 3  rescale the result to 0 to 10 against the statewide maximum

**Subgroup means are averaged, not pooled.** Section 10 is explicit and the
reason is worth restating where the code does it: pooling all seven Population
Characteristics indicators would hand Socioeconomic Factors five sevenths of
that component purely because it happens to have five indicators to Sensitive
Populations' two. Averaging the group means gives the two groups the influence
the methodology intends, keeps the 1.0 / 0.5 ratio in Pollution Burden a
deliberate weight rather than an artifact of how many indicators each group got,
and stays stable if an indicator is later added to either.

**A missing indicator is dropped and the rest re-averaged.** Never zero, never
the median. Section 11 rule 1, and its "direction matters" paragraph is the
whole argument: imputing a missing pollution indicator to the state median
pulls unmonitored high-burden areas down toward the middle, which is the exact
failure the project exists to avoid. Dropping leaves the estimate unbiased with
respect to the indicators that were observed and pushes the cost into
confidence, where a reader can see it.

**A group has to earn its mean.** Section 11 rule 2 sets a minimum count per
group; below it the group is not computable and drops out of the combination
entirely rather than contributing an average of one indicator. If a group drops
out, the weights re-normalize over the groups that remain, which is what makes
the fallbacks in rules 3 and 4 fall back to the *other group alone* rather than
to a half-weighted fraction of it.

**The confidence penalty is computed but not applied here.** Section 12 owns the
confidence value and CS-205 builds it. Rules 3 and 4 say a fallback is penalized
"heavily" and "with a confidence penalty" without fixing a number, so what this
module reports is the share of the component's weight that survived:

    penalty = Σ w(groups that were computable) / Σ w(all the component's groups)

For Pollution Burden that makes losing Exposures a 1/3 penalty and losing
Environmental Effects a 2/3 one, which is heavier for Exposures exactly because
section 10 weights it twice as much — the asymmetry rule 3 asks for, derived
from the weights already in the methodology rather than picked to look severe.
For Population Characteristics, where both groups weigh 1.0, either loss is 1/2.
CS-205 may refine how this enters `C(h)`; it should not have to re-derive which
hexes fell back.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from burden.indicators import GroupSpec
from burden.percentile import RankedHex, Ranking


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """What distinguishes one component from the other."""

    name: str
    groups: tuple[GroupSpec, ...]
    no_score_reason: str

    @property
    def total_weight(self) -> float:
        return sum(group.weight for group in self.groups)


@dataclass(frozen=True, slots=True)
class GroupMean:
    """One subgroup's mean percentile for one hex, and what went into it.

    `present` and `missing` are what the detail panel renders as the used and
    dropped indicators. Section 11 rule 5 requires a user to be able to see
    which of the fifteen actually produced the score, so the list is carried
    rather than recomputed from the absence of a number.
    """

    group: str
    mean: float | None
    present: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def computable(self) -> bool:
        return self.mean is not None


@dataclass(frozen=True, slots=True)
class HexComponent:
    """One component for one hex: the 0 to 10 score and everything behind it.

    `score` and `no_score_reason` are exclusive and exactly one is set, which is
    the `hex_score_scored_xor_reason` constraint in migration 0009. A hex the
    methodology declines to score says why rather than returning a bare null.
    """

    h3: str
    score: float | None
    raw: float | None
    groups: tuple[GroupMean, ...]
    no_score_reason: str | None
    confidence_penalty: float

    def group_mean(self, group: str) -> float | None:
        """The stored subgroup mean, for the `*_mean` columns on `hex_score`."""
        for entry in self.groups:
            if entry.group == group:
                return entry.mean
        raise KeyError(f"{group} is not a group of this component")


@dataclass(frozen=True, slots=True)
class ComponentResult:
    hexes: tuple[HexComponent, ...]
    raw_max: float | None
    """The statewide maximum of the raw component, the divisor of section 10 step 3.

    Stored because the rescaling is only reproducible beside it: the same hex
    with the same indicators scores differently against a different run's
    maximum, and an auditor re-deriving a stored score needs the number it was
    divided by.
    """

    def by_h3(self) -> dict[str, HexComponent]:
        return {row.h3: row for row in self.hexes}


def compute(
    spec: ComponentSpec, rankings: Mapping[str, Ranking], *, scored: Collection[str]
) -> ComponentResult:
    """Build one component over the scored hexes, per section 10 steps 1 to 3.

    `rankings` are the CS-201 percentile rankings keyed by indicator id. An
    indicator absent from the mapping was never ingested and is missing for
    every hex, which is a different thing from being ingested and having no
    value here, but section 11 treats both the same way: dropped, not zeroed.
    """
    universe = sorted(set(scored))
    lookup = _percentile_lookup(spec, rankings, universe)

    raws: dict[str, float] = {}
    grouped: dict[str, tuple[GroupMean, ...]] = {}

    for h3 in universe:
        means = tuple(_group_mean(group, lookup, h3) for group in spec.groups)
        grouped[h3] = means

        computable = [
            (group, mean.mean)
            for group, mean in zip(spec.groups, means, strict=True)
            if mean.mean is not None
        ]
        if computable:
            weight = sum(group.weight for group, _ in computable)
            raws[h3] = sum(group.weight * value for group, value in computable) / weight

    raw_max = max(raws.values()) if raws else None

    rows: list[HexComponent] = []
    for h3 in universe:
        means = grouped[h3]
        raw = raws.get(h3)

        if raw is None:
            rows.append(
                HexComponent(
                    h3=h3,
                    score=None,
                    raw=None,
                    groups=means,
                    no_score_reason=spec.no_score_reason,
                    confidence_penalty=0.0,
                )
            )
            continue

        # raw_max is a mean of percentiles and section 9 keeps every percentile
        # strictly above zero, so a non-empty run cannot divide by zero here.
        assert raw_max is not None and raw_max > 0.0
        surviving = sum(
            group.weight for group, mean in zip(spec.groups, means, strict=True) if mean.computable
        )

        rows.append(
            HexComponent(
                h3=h3,
                score=10.0 * raw / raw_max,
                raw=raw,
                groups=means,
                no_score_reason=None,
                confidence_penalty=surviving / spec.total_weight,
            )
        )

    return ComponentResult(hexes=tuple(rows), raw_max=raw_max)


def _group_mean(group: GroupSpec, lookup: Mapping[str, dict[str, RankedHex]], h3: str) -> GroupMean:
    present: list[str] = []
    missing: list[str] = []
    total = 0.0

    for indicator_id in group.indicators:
        row = lookup.get(indicator_id, {}).get(h3)
        if row is None or row.percentile is None:
            missing.append(indicator_id)
            continue
        present.append(indicator_id)
        total += row.percentile

    # Below the minimum the group drops out entirely rather than averaging the
    # one or two indicators that happen to be present. Section 11 rule 2: a mean
    # of one Exposures indicator is not a weaker Exposures estimate, it is a
    # different quantity wearing the same name.
    if len(present) < group.minimum_present:
        return GroupMean(
            group=group.group, mean=None, present=tuple(present), missing=tuple(missing)
        )

    return GroupMean(
        group=group.group,
        mean=total / len(present),
        present=tuple(present),
        missing=tuple(missing),
    )


def _percentile_lookup(
    spec: ComponentSpec, rankings: Mapping[str, Ranking], universe: list[str]
) -> dict[str, dict[str, RankedHex]]:
    """Index the rankings by hex, refusing any that was ranked against a different universe.

    Percentiles from two different denominators are not comparable and averaging
    them would produce a number that looks like a component score and is not
    one. The failure is silent everywhere downstream, so it is caught here.
    """
    wanted = {indicator for group in spec.groups for indicator in group.indicators}
    expected = set(universe)
    lookup: dict[str, dict[str, RankedHex]] = {}

    for indicator_id, ranking in rankings.items():
        if indicator_id not in wanted:
            continue
        rows = ranking.by_h3()
        if not expected <= rows.keys():
            raise ValueError(
                f"{indicator_id} was ranked over a different set of hexes than this "
                f"component is being asked to score; its percentiles are not comparable"
            )
        lookup[indicator_id] = rows

    return lookup
