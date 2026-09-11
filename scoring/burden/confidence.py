"""Methodology section 12: how well supported a score is.

Every scored hex carries a confidence value in (0, 1]. It measures how well
supported the score is, **not how severe the burden is**, and section 12 says
the two must never be conflated in the interface. A hex can be badly burdened
and well measured, or badly burdened and barely measured at all, and the second
is the one this number exists to make visible rather than to hide.

**Four terms**, each mapped into (0.05, 1] and combined by weight:

    c_coverage  0.35  weight-weighted fraction of the fifteen indicators observed
    c_recency   0.20  exp(−Δt / τ), τ = 4 years, over the contributing vintages
    c_spatial   0.25  interpolation support
    c_monitor   0.20  min(1, 10 km / d_nearest)

**Combination is geometric, not arithmetic.**

    C(h) = Π_j  c_j(h) ^ ( w_j / Σ w )

Section 12 chooses it so one badly deficient term cannot be averaged away by
three healthy ones. A hex with excellent coverage, recency and spatial support
but no monitor within 100 km should read as less certain than its arithmetic
mean would suggest, and under a geometric mean it does. Each term is floored at
0.05 first, so a single zero cannot annihilate the product; without the floor
one missing input would take the whole value to zero and lose the information
that the other three terms were fine.

**Recency is measured against vintages, not against pull timestamps.** Downloading
a 2019 dataset this morning does not make it a 2019 dataset from this morning.
The input here is `vintage_end` per indicator, the same date
`indicator_distribution` stores for the run, which is the release the adapter
actually read rather than the moment it read it. Getting this backwards would
make a stale pipeline look permanently fresh, which is the one thing a recency
term must not do.

**c_spatial is the term section 12 specifies by direction rather than by
formula.** It says interpolation support "falls with the share of hex population
drawn from ACS estimates whose coefficient of variation exceeds 0.30, and with
the mean area of the source census blocks", and stops there. So the functional
form below is an implementation choice, and it is flagged as one rather than
presented as the paper's:

    c_spatial = ( 1 − high_cv_share ) · min( 1, hex_area / mean_block_area )

It is monotone decreasing in both quantities, as required, lands in [0, 1], and
borrows the `min(1, reference / observed)` shape section 12 already uses for
c_monitor rather than inventing a second one. The reference area is the hex
itself, 0.737 km² from section 5: a source block no larger than the hex supports
the interpolation fully, and a block ten times the hex is a tenth of the support
because the dasymetric step is spreading one number across ten cells' worth of
ground. **This needs ratifying in docs/methodology.md with a changelog entry
before any score computed with it is published.** It is the one place in this
package where the code is ahead of the paper, and it is written down here so
that it is argued rather than inherited.

**Unknown support is not good support.** A hex with no block-area record has a
dasymetric step that cannot say what it interpolated from, and that is a reason
to trust the number less, not a reason to assume the best. The same goes for a
hex with no monitor distance at all. Both fall to the floor.

**The insufficient band is enforced here, not advised.** Section 12 bars a hex
below 0.40 from validation statistics and from the drafting assistant, because
producing a cited complaint from a score the system does not itself trust would
be the most damaging thing this tool could do. So `for_validation` returns a
sample those hexes are already out of, and `assert_documentable` raises rather
than returning a flag a caller can ignore. A rule that depends on every future
caller remembering it is not a rule.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from burden.indicators import GROUP_INDICATORS, GROUP_WEIGHTS

Band = Literal["high", "moderate", "low", "insufficient"]

# Section 12's table. They sum to 1.0, but the combination divides by their sum
# anyway so that changing one in the paper does not silently rescale the others.
TERM_WEIGHTS: dict[str, float] = {
    "coverage": 0.35,
    "recency": 0.20,
    "spatial": 0.25,
    "monitor": 0.20,
}

# "Each term is floored at 0.05 so that a single zero cannot annihilate the
# product." The floor is what makes the geometric mean usable at all.
TERM_FLOOR = 0.05

# exp(−Δt / τ). Four years is roughly the ACS five-year estimate's own window,
# so an indicator at one τ of age has about a third of the recency of a fresh one.
RECENCY_TAU_YEARS = 4.0

# min(1, 10 km / d). Ten kilometres is section 12's reference distance.
MONITOR_REFERENCE_KM = 10.0

# Section 5: average H3 resolution 8 cell area. The reference for block size.
HEX_AREA_KM2 = 0.737

# The Julian year, so a vintage's age does not drift with leap years.
DAYS_PER_YEAR = 365.25

# Section 12's band table. The printed ranges are two-decimal renderings of
# half-open intervals, so 0.795 is moderate rather than falling between bands.
BAND_FLOORS: tuple[tuple[float, Band], ...] = (
    (0.80, "high"),
    (0.60, "moderate"),
    (0.40, "low"),
)

# A hex below this cannot enter validation statistics or produce a document.
DOCUMENTABLE_FLOOR = 0.40

# Each indicator weighted as section 10 weights its group, which is what
# "weight-weighted fraction of the fifteen" means: four Exposures at 1.0, four
# Environmental Effects at 0.5, two Sensitive at 1.0 and five Socioeconomic at
# 1.0, so 13.0 in total. Losing E1 costs twice what losing F1 costs, which is
# the same ratio section 10 already assigns them.
INDICATOR_WEIGHT: dict[str, float] = {
    indicator: GROUP_WEIGHTS[group]
    for group, indicators in GROUP_INDICATORS.items()
    for indicator in indicators
}
TOTAL_INDICATOR_WEIGHT = sum(INDICATOR_WEIGHT.values())


class InsufficientConfidence(Exception):
    """Raised when a hex the system does not trust is asked to support a claim."""


@dataclass(frozen=True, slots=True)
class HexEvidence:
    """What is known about how well one hex was measured.

    Assembled by the run from the components and the interpolation step. Every
    field is about support rather than about burden.
    """

    h3: str
    observed_indicators: frozenset[str]
    high_cv_population_share: float = 0.0
    """Share of this hex's population drawn from ACS estimates with a CV over 0.30."""

    mean_block_area_km2: float | None = None
    """Mean area of the census blocks the dasymetric step interpolated from."""

    nearest_monitor_km: float | None = None
    """Distance to the nearest PM2.5 monitor. None where there is none to find."""


@dataclass(frozen=True, slots=True)
class HexConfidence:
    """One hex's confidence and the four terms behind it.

    The fields map onto the confidence columns of `hex_score`. The terms are
    stored, not only the combined value, because "this hex is at 0.42" is not
    actionable and "this hex is at 0.42 because the nearest monitor is 90 km
    away" is.
    """

    h3: str
    value: float
    band: Band
    c_coverage: float
    c_recency: float
    c_spatial: float
    c_monitor: float
    nearest_monitor_km: float | None

    @property
    def documentable(self) -> bool:
        """Whether section 12 lets this hex support a validation claim or a document."""
        return self.band != "insufficient"


def confidence(
    evidence: HexEvidence, *, vintages: Mapping[str, date], as_of: date
) -> HexConfidence:
    """The section 12 confidence value for one hex.

    `vintages` is the `vintage_end` date per indicator for this run, the release
    each adapter read. `as_of` is the run date the ages are measured against.
    """
    coverage = _floor(_coverage(evidence.observed_indicators))
    recency = _floor(_recency(evidence.observed_indicators, vintages, as_of))
    spatial = _floor(_spatial(evidence))
    monitor = _floor(_monitor(evidence.nearest_monitor_km))

    value = _geometric_mean(
        {
            "coverage": coverage,
            "recency": recency,
            "spatial": spatial,
            "monitor": monitor,
        }
    )

    return HexConfidence(
        h3=evidence.h3,
        value=value,
        band=band_for(value),
        c_coverage=coverage,
        c_recency=recency,
        c_spatial=spatial,
        c_monitor=monitor,
        nearest_monitor_km=evidence.nearest_monitor_km,
    )


def confidence_for_run(
    evidence: Iterable[HexEvidence], *, vintages: Mapping[str, date], as_of: date
) -> dict[str, HexConfidence]:
    """Confidence for every hex in the run, indexed by hex.

    Section 12 wants it computed for every scored hex including fully covered
    ones. A hex at 1.0 is a statement worth publishing, not a default worth
    skipping, and a map with confidence on some hexes and not others cannot be
    read at all.
    """
    return {
        row.h3: confidence(row, vintages=vintages, as_of=as_of)
        for row in sorted(evidence, key=lambda row: row.h3)
    }


def band_for(value: float) -> Band:
    """Section 12's bands, as half-open intervals."""
    for floor, band in BAND_FLOORS:
        if value >= floor:
            return band
    return "insufficient"


def for_validation(rows: Iterable[HexConfidence]) -> tuple[HexConfidence, ...]:
    """The hexes section 12 allows into validation statistics.

    Returns a sample the insufficient hexes are already out of, rather than a
    predicate a caller may forget to apply. Including a hex the system does not
    trust would let a validation result rest on a number the same document says
    is not to be relied on.
    """
    return tuple(row for row in rows if row.documentable)


def assert_documentable(row: HexConfidence) -> None:
    """Bar an insufficient hex from producing an advocacy document.

    Raises rather than returning false. Section 12: producing a cited complaint
    from a score the system does not itself trust would be the most damaging
    thing this tool could do, and a bar that depends on every future caller
    checking a boolean is not a bar.
    """
    if not row.documentable:
        raise InsufficientConfidence(
            f"hex {row.h3} is in the insufficient confidence band "
            f"({row.value:.2f} < {DOCUMENTABLE_FLOOR:.2f}); section 12 bars it from "
            f"supporting a drafted document"
        )


def low_confidence(rows: Iterable[HexConfidence]) -> tuple[HexConfidence, ...]:
    """Hexes in the low and insufficient bands, worst first, for QA.

    The database answer to the same question is one query against
    `hex_score.confidence_band`, which migration 0017 indexes for it.
    """
    return tuple(
        sorted(
            (row for row in rows if row.band in ("low", "insufficient")),
            key=lambda row: row.value,
        )
    )


def _coverage(observed: frozenset[str]) -> float:
    known = sum(INDICATOR_WEIGHT[i] for i in observed if i in INDICATOR_WEIGHT)
    return known / TOTAL_INDICATOR_WEIGHT


def _recency(observed: frozenset[str], vintages: Mapping[str, date], as_of: date) -> float:
    weighted_age = 0.0
    weight = 0.0

    for indicator in observed:
        vintage = vintages.get(indicator)
        if vintage is None or indicator not in INDICATOR_WEIGHT:
            continue
        # A vintage dated after the run is a clock problem upstream, not a
        # dataset from the future; treat it as current rather than as a bonus.
        age = max(0.0, (as_of - vintage).days / DAYS_PER_YEAR)
        weighted_age += INDICATOR_WEIGHT[indicator] * age
        weight += INDICATOR_WEIGHT[indicator]

    if weight == 0.0:
        # Nothing contributing carries a vintage, so the age of this score is
        # unknown. Unknown is not fresh.
        return 0.0

    return math.exp(-(weighted_age / weight) / RECENCY_TAU_YEARS)


def _spatial(evidence: HexEvidence) -> float:
    share = evidence.high_cv_population_share
    if not 0.0 <= share <= 1.0 or not math.isfinite(share):
        raise ValueError(
            f"high-CV population share for hex {evidence.h3} is not a share: {share!r}"
        )

    area = evidence.mean_block_area_km2
    if area is None:
        # No record of what the interpolation drew on. Not good support.
        return 0.0
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError(f"mean block area for hex {evidence.h3} is not an area: {area!r}")

    return (1.0 - share) * min(1.0, HEX_AREA_KM2 / area)


def _monitor(nearest_km: float | None) -> float:
    if nearest_km is None:
        return 0.0
    if not math.isfinite(nearest_km) or nearest_km < 0.0:
        raise ValueError(f"nearest monitor distance is not a distance: {nearest_km!r}")
    if nearest_km == 0.0:
        return 1.0
    return min(1.0, MONITOR_REFERENCE_KM / nearest_km)


def _geometric_mean(terms: Mapping[str, float]) -> float:
    """Π c_j ^ (w_j / Σw), computed in log space.

    Summing logs rather than multiplying powers keeps the result stable when a
    term sits near the floor, and makes the weighting obviously a weighted mean
    of logs rather than four exponentiations whose order might matter.
    """
    total_weight = sum(TERM_WEIGHTS[name] for name in terms)
    logs = sum(TERM_WEIGHTS[name] * math.log(value) for name, value in terms.items())
    return math.exp(logs / total_weight)


def _floor(value: float) -> float:
    return min(1.0, max(TERM_FLOOR, value))


def term_weights_sum_to_one() -> bool:
    """Section 12's four weights, as the paper prints them."""
    return math.isclose(sum(TERM_WEIGHTS.values()), 1.0)


def indicator_ids() -> Sequence[str]:
    """The fifteen, in registry order. Handy for assembling `observed_indicators`."""
    return tuple(INDICATOR_WEIGHT)
