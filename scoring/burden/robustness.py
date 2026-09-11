"""Methodology section 13.5: whether the score is an artifact of its own construction.

Sections 13.2 through 13.4 ask whether the score finds the right places. This
section asks a different and less comfortable question: whether the number is
measuring Louisiana or measuring the choices made in section 10. A score that
flags every pre-registered site and also flips its ordering when one weight
moves from 0.5 to 1.0 has not been validated by the site check. It has been
shown to agree with the sites by accident of its construction.

Three checks, each answerable only by building the score a different way and
comparing.

**Alternative specifications.** Spearman rank correlation of at least 0.85
between the score and each of: equal weighting of Exposures and Environmental
Effects; Exposures alone; addition rather than multiplication. The first two
gate. The third is reported and does not, because section 13.5 says so and the
reason is substantive rather than lenient. Section 3 rejects the additive model
*because* it makes a different claim, so a high correlation with it would be the
surprising result. Reporting a low one is the point; requiring a high one would
quietly assert that the choice between the two models does not matter.

**Leave-one-indicator-out.** Removing any single indicator must not move more
than 10% of hexes by more than one decile. An indicator that fails is doing too
much work alone, and section 13.5 sends that back to the methodology paper to be
re-argued rather than fixing it here.

**Interpolation sensitivity.** The score recomputed with simple area share in
place of the dasymetric weighting of section 7, to quantify how much that
machinery actually changes. Reported, never gating: section 7 argues for
dasymetric weighting on evidentiary grounds, so a large divergence vindicates
the argument rather than failing the score, and a small one is worth publishing
because it tells a reader the most expensive step in the pipeline bought less
than it cost.

**Every variant is built with the production code, not a re-implementation.**
`compute` in `component.py` takes the group specification as an argument, so a
variant is a different `ComponentSpec` handed to the same function rather than a
second copy of the arithmetic. That matters more here than anywhere else in the
package: a robustness check that re-derives the score in order to compare
against it is comparing two implementations, and would report a difference in
its own comparison code as a property of the methodology. `_compose` is the one
place this module composes components itself, because section 10 step 4
multiplies and one variant adds, and
`tests/test_robustness.py::test_the_baseline_specification_reproduces_cs_204`
holds it to `burden_score` exactly. That test is what makes "the same code path"
a fact rather than an intention.

**The comparison universe is fixed once, at the top.** Section 12 bars
insufficient-confidence hexes from validation statistics and CS-205 enforces
that rather than advising it, so `check` requires the bands and filters before
anything is ranked. Every variant is then ranked against that same denominator,
which is what makes the correlations between them mean anything: percentiles
drawn from two different denominators are not comparable, and a robustness check
built on them would be measuring its own bookkeeping.

**Nothing here adjusts anything.** Section 13.7's failure protocol applies in
full. A specification correlation below the bar, or an indicator that moves the
map, is answered by a code fix, a data-handling fix, or a methodology revision
whose rationale stands independently of this outcome. Not by moving the 0.85 or
the 10%, which is why both arrive from section 13.5 as constants a reader can
find rather than as arguments a caller can pass.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Literal

from burden.component import ComponentSpec, HexComponent, compute
from burden.eligibility import Eligibility
from burden.indicators import GROUP_INDICATORS, GroupSpec, group_spec
from burden.methodology import METHODOLOGY_VERSION
from burden.percentile import RankedHex, Ranking, rank, rank_indicators
from burden.pollution import ENVIRONMENTAL_EFFECTS, EXPOSURES, POLLUTION_BURDEN
from burden.population import POPULATION_CHARACTERISTICS

# Section 13.5. Not tunables. Section 13.7 does not permit answering a failing
# check by loosening it, and a threshold arriving as a function argument would be
# one call site away from being loosened without this file changing.
SPECIFICATION_CORRELATION = 0.85
LEAVE_ONE_OUT_MAX_MOVED_SHARE = 0.10
LEAVE_ONE_OUT_DECILE_TOLERANCE = 1

# Section 12, via CS-205: an untrusted hex is out of every validation statistic,
# and section 13.5 is a validation statistic.
INSUFFICIENT = "insufficient"

Combine = Literal["multiplicative", "additive"]


@dataclass(frozen=True, slots=True)
class Specification:
    """One way of building the score, as section 13.5 wants it built.

    The baseline is section 10 exactly. Each variant changes one thing and says
    which, because a variant that changed two would not tell you which of them
    the correlation was about.
    """

    name: str
    pollution: ComponentSpec
    population: ComponentSpec
    combine: Combine
    gating: bool
    changed: str
    """What this variant does differently from section 10, for the write-up."""


def _pollution_variant(name: str, groups: tuple[GroupSpec, ...]) -> ComponentSpec:
    """A Pollution Burden built from different groups or different weights.

    The reason string stays `insufficient_pollution_data`. A variant that could
    not build the pollution half failed for the same reason the real one would,
    and inventing a fifth no-score reason here would put a string on a
    comparison row that `hex_score` does not accept.
    """
    return ComponentSpec(name=name, groups=groups, no_score_reason="insufficient_pollution_data")


# Section 10 as written. Present as a specification so the baseline goes through
# the identical code path as every variant it is compared against.
BASELINE = Specification(
    name="baseline",
    pollution=POLLUTION_BURDEN,
    population=POPULATION_CHARACTERISTICS,
    combine="multiplicative",
    gating=False,
    changed="section 10 as written",
)

# Section 13.5, variant 1. Environmental Effects raised from 0.5 to 1.0. The
# group minimums are untouched: this variant asks what the weight buys, and
# moving a minimum at the same time would answer a different question.
EQUAL_WEIGHTS = Specification(
    name="equal_weights",
    pollution=_pollution_variant(
        "pollution_burden_equal_weights",
        (
            GroupSpec(EXPOSURES, GROUP_INDICATORS[EXPOSURES], 1.0, 2),
            GroupSpec(ENVIRONMENTAL_EFFECTS, GROUP_INDICATORS[ENVIRONMENTAL_EFFECTS], 1.0, 2),
        ),
    ),
    population=POPULATION_CHARACTERISTICS,
    combine="multiplicative",
    gating=True,
    changed="Environmental Effects weighted 1.0 rather than 0.5",
)

# Section 13.5, variant 2. Environmental Effects dropped entirely, so Pollution
# Burden is the Exposures mean rescaled. A hex whose Exposures group misses its
# minimum has no pollution half at all under this variant, which is part of what
# is being tested: section 11 rule 3's fallback is one of the choices in question.
EXPOSURES_ONLY = Specification(
    name="exposures_only",
    pollution=_pollution_variant("pollution_burden_exposures_only", (group_spec(EXPOSURES),)),
    population=POPULATION_CHARACTERISTICS,
    combine="multiplicative",
    gating=True,
    changed="Pollution Burden from Exposures alone, Environmental Effects dropped",
)

# Section 13.5, variant 3. Both components exactly as section 10 builds them,
# added instead of multiplied. Reported, not gating, per section 13.5.
ADDITIVE = Specification(
    name="additive",
    pollution=POLLUTION_BURDEN,
    population=POPULATION_CHARACTERISTICS,
    combine="additive",
    gating=False,
    changed="components added rather than multiplied",
)

SPECIFICATIONS: tuple[Specification, ...] = (EQUAL_WEIGHTS, EXPOSURES_ONLY, ADDITIVE)


@dataclass(frozen=True, slots=True)
class SpecificationResult:
    """How closely one alternative specification orders the state the same way."""

    name: str
    changed: str
    gating: bool
    correlation: float | None
    threshold: float
    hexes_compared: int
    hexes_baseline_only: int
    hexes_variant_only: int
    detail: str

    @property
    def met(self) -> bool:
        """Whether this cleared section 13.5. Always true for a reported variant.

        An uncomputable correlation fails a gating variant rather than passing
        it. Section 13.5 asks for evidence that the ordering survives the
        change, and "there was not enough to say" is not that evidence.
        """
        if not self.gating:
            return True
        return self.correlation is not None and self.correlation >= self.threshold


@dataclass(frozen=True, slots=True)
class IndicatorResult:
    """What removing one indicator did to the map.

    `hexes_group_lost` separates two findings section 13.5 would otherwise
    conflate. A hex can move because the indicator carried real information, or
    because its group fell under the section 11 rule 2 minimum once the
    indicator was gone and dropped out entirely. The first is what the criterion
    is looking for. The second is a property of the minimum count, and a reader
    deciding whether an indicator needs re-arguing in the paper needs to know
    which of the two they are looking at.
    """

    indicator: str
    group: str
    hexes_compared: int
    moved_more_than_one_decile: int
    hexes_lost_score: int
    hexes_group_lost: int
    largest_decile_move: int
    share_moved: float
    threshold: float
    detail: str

    @property
    def met(self) -> bool:
        return self.share_moved <= self.threshold


@dataclass(frozen=True, slots=True)
class InterpolationResult:
    """How much the section 7 machinery changes, quantified rather than judged.

    Areal weighting changes the population estimate as well as the indicator
    values, so it changes which hexes clear the 25-person threshold of section 5.
    The two runs therefore have different scored universes, and the hexes only
    one of them scored are reported rather than reconciled: a hex that only one
    method scores at all is a larger consequence of the choice than any decile
    move, and folding it into an average would hide the biggest thing this check
    found.
    """

    correlation: float | None
    hexes_compared: int
    hexes_dasymetric_only: int
    hexes_areal_only: int
    moved_more_than_one_decile: int
    share_moved: float
    largest_decile_move: int
    median_absolute_decile_move: float
    median_absolute_score_change: float | None
    detail: str


@dataclass(frozen=True, slots=True)
class Interpolation:
    """One interpolation method's inputs: what it estimated, and for whom.

    Both are needed because section 7 decides the population estimate too, and
    section 5 draws the scored universe from that estimate. Handing this check
    only the indicator values would silently hold the universe fixed at whatever
    the other method produced, which is the single largest effect the choice has.
    """

    eligibility: Eligibility
    values: Mapping[str, Mapping[str, float | None]]


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    """Section 13.5's answer for one run."""

    specifications: tuple[SpecificationResult, ...]
    indicators: tuple[IndicatorResult, ...]
    interpolation: InterpolationResult | None
    hexes_in_universe: int
    hexes_excluded_low_confidence: int
    methodology_version: str

    @property
    def passed(self) -> bool:
        """Whether every gating check in section 13.5 cleared its bar."""
        return all(row.met for row in self.specifications) and all(
            row.met for row in self.indicators
        )

    def specification(self, name: str) -> SpecificationResult:
        for row in self.specifications:
            if row.name == name:
                return row
        raise KeyError(f"{name} is not a specification of this run")

    def indicator(self, indicator_id: str) -> IndicatorResult:
        for row in self.indicators:
            if row.indicator == indicator_id:
                return row
        raise KeyError(f"{indicator_id} was not left out of this run")

    def failures(self) -> tuple[str, ...]:
        """Every gating check that did not clear, for the write-up."""
        return tuple(
            [row.name for row in self.specifications if not row.met]
            + [row.indicator for row in self.indicators if not row.met]
        )


def check(
    values: Mapping[str, Mapping[str, float | None]],
    *,
    eligibility: Eligibility,
    confidence_bands: Mapping[str, str],
    areal: Interpolation | None = None,
    methodology_version: str = METHODOLOGY_VERSION,
) -> RobustnessReport:
    """Run the three section 13.5 checks over one set of indicator values.

    `values` maps indicator id to hex to raw value, before any ranking: this
    module ranks them itself so that every variant shares one denominator.
    `eligibility` is the section 5 split. `confidence_bands` covers every scored
    hex, and is required rather than optional because section 12 bars
    insufficient-confidence hexes from validation statistics, and a default of
    "include everything" would be that exclusion left to the caller.

    `areal` supplies the same two things computed with simple area share. It is
    the only optional argument, because the first two checks are answerable from
    one interpolation and the third is not answerable from any number of them.
    """
    universe, excluded = _universe(eligibility, confidence_bands)
    rankings = rank_indicators(values, scored=universe)
    baseline = _compose(BASELINE, rankings, scored=universe)

    return RobustnessReport(
        specifications=alternative_specifications(rankings, scored=universe, baseline=baseline),
        indicators=leave_one_out(rankings, scored=universe, baseline=baseline),
        interpolation=(
            None
            if areal is None
            else interpolation_sensitivity(
                dasymetric=Interpolation(eligibility=eligibility, values=values),
                areal=areal,
                confidence_bands=confidence_bands,
            )
        ),
        hexes_in_universe=len(universe),
        hexes_excluded_low_confidence=excluded,
        methodology_version=methodology_version,
    )


def alternative_specifications(
    rankings: Mapping[str, Ranking],
    *,
    scored: Sequence[str],
    baseline: Mapping[str, float] | None = None,
    specifications: Iterable[Specification] = SPECIFICATIONS,
) -> tuple[SpecificationResult, ...]:
    """Section 13.5 check 1: does the ordering survive building the score differently?"""
    reference = _compose(BASELINE, rankings, scored=scored) if baseline is None else baseline

    results: list[SpecificationResult] = []
    for spec in specifications:
        variant = _compose(spec, rankings, scored=scored)
        correlation = spearman(reference, variant)

        results.append(
            SpecificationResult(
                name=spec.name,
                changed=spec.changed,
                gating=spec.gating,
                correlation=correlation,
                threshold=SPECIFICATION_CORRELATION,
                hexes_compared=len(reference.keys() & variant.keys()),
                hexes_baseline_only=len(reference.keys() - variant.keys()),
                hexes_variant_only=len(variant.keys() - reference.keys()),
                detail=_specification_detail(spec, correlation, SPECIFICATION_CORRELATION),
            )
        )

    return tuple(results)


def leave_one_out(
    rankings: Mapping[str, Ranking],
    *,
    scored: Sequence[str],
    baseline: Mapping[str, float] | None = None,
) -> tuple[IndicatorResult, ...]:
    """Section 13.5 check 2: is any single indicator carrying the map on its own?

    One variant per indicator in section 8, each built without that indicator in
    its group and without its ranking. The group minimum from section 11 rule 2
    is a count rather than a share and is left at its stated value, capped at the
    number of indicators the group has left so that removing one can never ask a
    group for more than it has. For every group in section 8 the two readings
    agree, so the cap is a guard rather than a choice: Socioeconomic Factors goes
    from 4 of 5 to 4 of 4 either way. That is severe, and it is why
    `hexes_group_lost` is reported separately from the movement itself.
    """
    reference = _compose(BASELINE, rankings, scored=scored) if baseline is None else baseline
    reference_deciles = _deciles(reference)

    # Both baseline components, once. `_group_lost` needs the one holding the
    # affected group for every indicator, and recomputing it inside the loop
    # would be fifteen passes over the state to produce the same four numbers.
    baseline_components = {
        BASELINE.pollution.name: compute(BASELINE.pollution, rankings, scored=scored).by_h3(),
        BASELINE.population.name: compute(BASELINE.population, rankings, scored=scored).by_h3(),
    }

    results: list[IndicatorResult] = []
    for group, indicators in GROUP_INDICATORS.items():
        for indicator_id in indicators:
            spec = _without(indicator_id)
            trimmed = {key: value for key, value in rankings.items() if key != indicator_id}
            variant_deciles = _deciles(_compose(spec, trimmed, scored=scored))

            moved = 0
            lost = 0
            largest = 0
            for h3, before in reference_deciles.items():
                after = variant_deciles.get(h3)
                if after is None:
                    # Losing a score outright is at least as large a change as
                    # any decile move, so it counts as one rather than dropping
                    # out of the denominator and flattering the result.
                    lost += 1
                    moved += 1
                    continue
                distance = abs(after - before)
                largest = max(largest, distance)
                if distance > LEAVE_ONE_OUT_DECILE_TOLERANCE:
                    moved += 1

            compared = len(reference_deciles)
            share = moved / compared if compared else 0.0
            group_lost = _group_lost(
                spec,
                trimmed,
                scored=scored,
                group=group,
                before=baseline_components[_component_holding(BASELINE, group).name],
            )

            results.append(
                IndicatorResult(
                    indicator=indicator_id,
                    group=group,
                    hexes_compared=compared,
                    moved_more_than_one_decile=moved,
                    hexes_lost_score=lost,
                    hexes_group_lost=group_lost,
                    largest_decile_move=largest,
                    share_moved=share,
                    threshold=LEAVE_ONE_OUT_MAX_MOVED_SHARE,
                    detail=_indicator_detail(
                        indicator_id, moved, compared, share, lost, group_lost
                    ),
                )
            )

    return tuple(results)


def interpolation_sensitivity(
    *,
    dasymetric: Interpolation,
    areal: Interpolation,
    confidence_bands: Mapping[str, str],
) -> InterpolationResult:
    """Section 13.5 check 3: how much does the section 7 machinery actually change?

    Each method is scored on its own universe, because each produces its own
    population estimate and section 5 draws the 25-person line from it. The
    correlation and the decile movement are computed over the hexes both
    methods scored; the hexes only one of them scored are counted beside them.
    """
    left = _score_one(dasymetric, confidence_bands)
    right = _score_one(areal, confidence_bands)

    shared = sorted(left.keys() & right.keys())
    left_deciles = _deciles(left)
    right_deciles = _deciles(right)

    moves = [abs(right_deciles[h3] - left_deciles[h3]) for h3 in shared]
    changes = [abs(right[h3] - left[h3]) for h3 in shared]
    moved = sum(1 for distance in moves if distance > LEAVE_ONE_OUT_DECILE_TOLERANCE)
    correlation = spearman(left, right)

    return InterpolationResult(
        correlation=correlation,
        hexes_compared=len(shared),
        hexes_dasymetric_only=len(left.keys() - right.keys()),
        hexes_areal_only=len(right.keys() - left.keys()),
        moved_more_than_one_decile=moved,
        share_moved=moved / len(shared) if shared else 0.0,
        largest_decile_move=max(moves) if moves else 0,
        median_absolute_decile_move=float(median(moves)) if moves else 0.0,
        median_absolute_score_change=float(median(changes)) if changes else None,
        detail=_interpolation_detail(correlation, moved, len(shared), left, right),
    )


def spearman(left: Mapping[str, float], right: Mapping[str, float]) -> float | None:
    """Spearman rank correlation over the keys both mappings hold.

    Spearman is Pearson's correlation computed on ranks, and section 9's
    percentile is `100 · (r − 0.5) / n`, a strictly increasing affine function of
    the mid-rank with the same `n` on both sides here because both are ranked
    over the same shared keys. Pearson is invariant under an affine change of
    either variable, so ranking through `rank` gives exactly Spearman's rho while
    reusing the tie handling section 9 already specifies and tests.

    Ties taking the mean of their ranks is load-bearing rather than a detail. E3
    and F1 through F4 are exactly zero across a large share of Louisiana, so a
    large block of hexes shares one rank, and the uncorrected `1 − 6Σd²/(n³−n)`
    shortcut is wrong by an amount that grows with the size of that block.

    Returns None where the statistic does not exist: fewer than two shared hexes,
    or one side constant across all of them, which leaves its rank variance zero
    and the correlation undefined rather than zero.
    """
    shared = tuple(sorted(left.keys() & right.keys()))
    if len(shared) < 2:
        return None

    left_ranked = rank({h3: left[h3] for h3 in shared}, scored=shared).by_h3()
    right_ranked = rank({h3: right[h3] for h3 in shared}, scored=shared).by_h3()

    xs = [_percentile_of(left_ranked[h3]) for h3 in shared]
    ys = [_percentile_of(right_ranked[h3]) for h3 in shared]

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    spread_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    spread_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

    if spread_x == 0.0 or spread_y == 0.0:
        return None

    # Floating point can put an exact ±1 a few ulps outside the range. Comparing
    # 1.0000000000000002 against a threshold is harmless; printing it in a report
    # that claims to be a correlation is not.
    return max(-1.0, min(1.0, covariance / (spread_x * spread_y)))


def _universe(
    eligibility: Eligibility, confidence_bands: Mapping[str, str]
) -> tuple[tuple[str, ...], int]:
    """The hexes every check in this module is computed over, fixed once.

    Section 5 supplies the scored set and section 12 removes the hexes it does
    not trust. A scored hex with no band is refused rather than assumed
    trustworthy: a run whose confidence was never computed cannot honour the
    section 12 exclusion, and quietly including those hexes would be the failure
    the exclusion exists to prevent.
    """
    missing = [h3 for h3 in eligibility.scored if h3 not in confidence_bands]
    if missing:
        raise ValueError(
            f"{len(missing)} scored hexes carry no confidence band, so section 12's "
            f"exclusion from validation statistics cannot be applied; the first is "
            f"{missing[0]}"
        )

    universe = tuple(h3 for h3 in eligibility.scored if confidence_bands[h3] != INSUFFICIENT)
    return universe, len(eligibility.scored) - len(universe)


def _score_one(
    interpolation: Interpolation, confidence_bands: Mapping[str, str]
) -> dict[str, float]:
    """One interpolation method scored end to end, on its own section 5 universe.

    A hex this method scores may be absent from the bands entirely, since the two
    methods disagree about which cells are populated enough to score and the
    bands were computed for one of them. An absent band is read as untrusted and
    the hex is left out, which is the conservative direction: it drops the hex
    from the comparison rather than admitting one whose confidence nobody
    computed.
    """
    universe = tuple(
        h3
        for h3 in interpolation.eligibility.scored
        if confidence_bands.get(h3, INSUFFICIENT) != INSUFFICIENT
    )
    rankings = rank_indicators(interpolation.values, scored=universe)
    return _compose(BASELINE, rankings, scored=universe)


def _compose(
    spec: Specification, rankings: Mapping[str, Ranking], *, scored: Sequence[str]
) -> dict[str, float]:
    """Both components through the production `compute`, combined per the variant.

    The only arithmetic this module does that `score.py` also does. It is here
    because section 10 step 4 multiplies and one section 13.5 variant adds, and a
    comparison that could not add would have nothing to say about the model
    section 3 explicitly rejected. The two are held together by a test that runs
    the baseline specification through both and requires identical scores.

    A hex either component could not score is absent from the result rather than
    carrying None, because every caller here is asking about hexes that have a
    score under both of the specifications being compared.
    """
    pollution = compute(spec.pollution, rankings, scored=scored).by_h3()
    population = compute(spec.population, rankings, scored=scored).by_h3()

    composed: dict[str, float] = {}
    for h3 in scored:
        left = pollution[h3].score
        right = population[h3].score
        if left is None or right is None:
            continue
        composed[h3] = left * right if spec.combine == "multiplicative" else left + right

    return composed


def _without(indicator_id: str) -> Specification:
    """The baseline with one indicator removed from whichever group holds it."""

    def trim(group: GroupSpec) -> GroupSpec:
        if indicator_id not in group.indicators:
            return group
        remaining = tuple(entry for entry in group.indicators if entry != indicator_id)
        return GroupSpec(
            group=group.group,
            indicators=remaining,
            weight=group.weight,
            # Section 11 rule 2 states a count. Capped so that removing an
            # indicator can never ask a group for more than it has left.
            minimum_present=min(group.minimum_present, len(remaining)),
        )

    return Specification(
        name=f"without_{indicator_id}",
        pollution=ComponentSpec(
            name=POLLUTION_BURDEN.name,
            groups=tuple(trim(group) for group in POLLUTION_BURDEN.groups),
            no_score_reason=POLLUTION_BURDEN.no_score_reason,
        ),
        population=ComponentSpec(
            name=POPULATION_CHARACTERISTICS.name,
            groups=tuple(trim(group) for group in POPULATION_CHARACTERISTICS.groups),
            no_score_reason=POPULATION_CHARACTERISTICS.no_score_reason,
        ),
        combine="multiplicative",
        gating=True,
        changed=f"{indicator_id} removed",
    )


def _component_holding(spec: Specification, group: str) -> ComponentSpec:
    for component in (spec.pollution, spec.population):
        if any(entry.group == group for entry in component.groups):
            return component
    raise KeyError(f"{group} is not a group of either component")


def _group_lost(
    spec: Specification,
    rankings: Mapping[str, Ranking],
    *,
    scored: Sequence[str],
    group: str,
    before: Mapping[str, HexComponent],
) -> int:
    """Hexes whose affected group was computable before the removal and is not after.

    Counted so a reader can tell an indicator that carried real information from
    one whose absence tripped the section 11 rule 2 minimum. The two look
    identical in the movement figure and mean opposite things in the paper.
    """
    after = compute(_component_holding(spec, group), rankings, scored=scored).by_h3()

    return sum(
        1
        for h3 in scored
        if before[h3].group_mean(group) is not None and after[h3].group_mean(group) is None
    )


def _deciles(scores: Mapping[str, float]) -> dict[str, int]:
    """Each hex's statewide decile under one specification, 1 through 10.

    Ranked with the same section 9 machinery as everything else, over the hexes
    this specification scored. The decile comes from the variant's own
    distribution rather than from the baseline's breakpoints, because what
    section 13.5 asks is where a hex stands relative to the state under each
    construction, not what the baseline's ladder would have called it.
    """
    if not scores:
        return {}
    universe = tuple(sorted(scores))
    ranked = rank(dict(scores), scored=universe)
    return {row.h3: _decile(row.percentile) for row in ranked.hexes if row.percentile is not None}


def _decile(percentile: float) -> int:
    """Decile 1 through 10.

    Section 9 keeps percentiles strictly inside 0 and 100, so the clamp never
    binds. It is here so that a future change to that convention fails a test
    rather than quietly producing a decile 0 or 11.
    """
    return min(10, max(1, math.ceil(percentile / 10.0)))


def _percentile_of(row: RankedHex) -> float:
    assert row.percentile is not None, "every hex ranked here held a value"
    return row.percentile


def _specification_detail(spec: Specification, correlation: float | None, threshold: float) -> str:
    if correlation is None:
        return (
            f"{spec.changed}; rank correlation undefined, with fewer than two hexes "
            f"scored under both specifications or no variation in one of them"
        )
    if not spec.gating:
        return (
            f"{spec.changed}; rank correlation {correlation:.3f}. Reported, not "
            f"gating: section 13.5 expects this to be low and treats it as "
            f"informative, because section 3 rejects this model for making a "
            f"different claim rather than a worse one"
        )
    if correlation >= threshold:
        return f"{spec.changed}; rank correlation {correlation:.3f}, at or above {threshold:.2f}"
    return (
        f"{spec.changed}; rank correlation {correlation:.3f}, below {threshold:.2f}. "
        f"The ordering depends on this choice, so the choice has to be argued in "
        f"the methodology paper rather than assumed"
    )


def _indicator_detail(
    indicator_id: str, moved: int, compared: int, share: float, lost: int, group_lost: int
) -> str:
    head = (
        f"{moved} of {compared} hexes ({share:.1%}) moved more than one decile "
        f"without {indicator_id}"
    )
    aside = []
    if lost:
        aside.append(f"{lost} lost their score entirely")
    if group_lost:
        aside.append(f"{group_lost} lost the group to the section 11 rule 2 minimum")
    if aside:
        head += "; " + ", ".join(aside)
    if share <= LEAVE_ONE_OUT_MAX_MOVED_SHARE:
        return head
    return (
        f"{head}. Above the {LEAVE_ONE_OUT_MAX_MOVED_SHARE:.0%} bar: this indicator "
        f"is doing too much work alone, and section 13.5 sends its inclusion back to "
        f"the methodology paper to be re-argued"
    )


def _interpolation_detail(
    correlation: float | None,
    moved: int,
    compared: int,
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> str:
    only_left = len(left.keys() - right.keys())
    only_right = len(right.keys() - left.keys())
    measured = (
        "rank correlation undefined"
        if correlation is None
        else f"rank correlation {correlation:.3f}"
    )
    head = (
        f"areal weighting against dasymetric: {measured}, {moved} of {compared} "
        f"shared hexes moved more than one decile"
    )
    if only_left or only_right:
        head += (
            f"; {only_left} hexes scored only under dasymetric weighting and "
            f"{only_right} only under areal, because the two disagree about which "
            f"cells clear the 25-person line of section 5"
        )
    return (
        f"{head}. Reported, not gating: section 13.5 asks this check to quantify how "
        f"much the section 7 machinery changes, and section 7 argues for dasymetric "
        f"weighting on grounds that do not depend on the answer"
    )


def report(result: RobustnessReport, *, scores_from: str) -> str:
    """The write-up section 13.5 asks for, in the shape section 13's already takes.

    `scores_from` names where the values came from and is printed at the top, for
    the same reason `validation.report` prints it: a robustness result read
    beside the wrong run is worse than no robustness result, and section 13.7
    turns on being able to say which run a verdict describes.
    """
    lines: list[str] = [
        "# ClearSkies robustness checks",
        "",
        f"- Methodology version: {result.methodology_version}",
        f"- Scores from: {scores_from}",
        f"- Hexes in the comparison universe: {result.hexes_in_universe}",
        f"- Excluded as insufficient confidence: {result.hexes_excluded_low_confidence}",
        f"- Outcome: **{'PASS' if result.passed else 'FAIL'}**",
        "",
        "## 13.5 Alternative specifications",
        "",
        "Spearman rank correlation against the score as section 10 builds it. At "
        f"least {SPECIFICATION_CORRELATION:.2f} is required of the gating variants.",
        "",
        "| Specification | Gating | Correlation | Hexes compared | Notes |",
        "|---|---|---|---|---|",
    ]

    for spec in result.specifications:
        lines.append(
            f"| {spec.name} "
            f"| {'yes' if spec.gating else 'reported'} "
            f"| {_number(spec.correlation)} "
            f"| {spec.hexes_compared} "
            f"| {spec.detail} |"
        )

    lines += [
        "",
        "## 13.5 Leave-one-indicator-out",
        "",
        "Removing any single indicator must not move more than "
        f"{LEAVE_ONE_OUT_MAX_MOVED_SHARE:.0%} of hexes by more than one decile.",
        "",
        "| Indicator | Group | Moved > 1 decile | Share | Lost score | Group lost | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]

    for row in result.indicators:
        lines.append(
            f"| {row.indicator} "
            f"| {row.group} "
            f"| {row.moved_more_than_one_decile} of {row.hexes_compared} "
            f"| {row.share_moved:.1%} "
            f"| {row.hexes_lost_score} "
            f"| {row.hexes_group_lost} "
            f"| {'within' if row.met else 'ABOVE THE BAR'} |"
        )

    lines += ["", "## 13.5 Interpolation sensitivity", ""]
    if result.interpolation is None:
        lines.append(
            "Not run: no areal-weighted interpolation was supplied. Section 13.5 asks "
            "for the score recomputed with simple areal weighting, and that cannot be "
            "answered from the dasymetric run alone."
        )
    else:
        sensitivity = result.interpolation
        lines += [
            f"- Rank correlation: {_number(sensitivity.correlation)}",
            f"- Hexes scored by both methods: {sensitivity.hexes_compared}",
            f"- Scored only under dasymetric weighting: {sensitivity.hexes_dasymetric_only}",
            f"- Scored only under areal weighting: {sensitivity.hexes_areal_only}",
            f"- Moved more than one decile: {sensitivity.moved_more_than_one_decile} "
            f"({sensitivity.share_moved:.1%})",
            f"- Largest decile move: {sensitivity.largest_decile_move}",
            f"- Median absolute decile move: {sensitivity.median_absolute_decile_move:.1f}",
            f"- Median absolute score change: {_number(sensitivity.median_absolute_score_change)}",
            "",
            sensitivity.detail,
        ]

    failures = result.failures()
    lines += ["", "## If this run failed", ""]
    if failures:
        lines += ["Checks that did not clear: " + ", ".join(failures) + ".", ""]
    lines += [
        "Section 13.7 permits three responses: fix a defect in the code, fix a defect "
        "in the data handling, or revise the methodology with a rationale that stands "
        "independently of this outcome, then re-run every check from the beginning. "
        "Moving the 0.85 or the 10% because a check missed them is not one of them. "
        "Section 13.5 is specific about the leave-one-out case: an indicator that "
        "fails is re-argued in the methodology paper, and the paper is where that "
        "argument has to stand.",
        "",
    ]

    return "\n".join(lines)


def _number(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"
