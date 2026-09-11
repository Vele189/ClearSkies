"""What is being interpolated, and how its uncertainty travels with it.

Two things live here. The first is the extensive/intensive distinction, which
methodology section 7 calls the most common source of error in the whole step
and which this module makes structural rather than advisory: a value carries
its own kind, and the two interpolation functions each refuse the other's kind
outright. Confusing them is then a crash on the first row, not a plausible
number nobody questions.

The second is the margin-of-error arithmetic. ACS 5-year estimates carry
published margins, and at tract level for small subgroups those margins are
frequently larger than the estimate. Section 7 requires them to be combined in
quadrature under the Census Bureau's approximation for derived sums, with the
resulting coefficient of variation travelling with the value into the
`c_spatial` term of section 12. Nothing here ever drops a high-uncertainty
estimate: section 7 is explicit that there is no threshold above which an
estimate is silently discarded, because dropping high-uncertainty estimates
preferentially removes small and rural populations.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

#: ACS margins of error are published at the 90 percent confidence level. The
#: Census Bureau's own worked examples divide by this to recover a standard
#: error, and the 0.30 coefficient-of-variation threshold in sections 7 and 12
#: is only meaningful against a standard error derived the same way. Using 1.96
#: here, as if the margins were 95 percent, would understate every coefficient
#: of variation in the pipeline by about 16 percent.
ACS_MOE_Z = 1.645

#: Section 7 and section 12: above this the estimate is still used and
#: c_spatial falls instead. It is a confidence input, never a filter.
HIGH_UNCERTAINTY_CV = 0.30


class Kind(StrEnum):
    """Extensive or intensive, in section 7's sense.

    EXTENSIVE quantities are counts and sum across space: population,
    households, number of people in poverty. They are apportioned through the
    crosswalk's population weights.

    INTENSIVE quantities are rates, ratios, and modeled risks and do not sum:
    poverty rate, AirToxScreen cancer risk, percent without a high school
    diploma. They are combined as a population-weighted mean.
    """

    EXTENSIVE = "extensive"
    INTENSIVE = "intensive"

    @property
    def is_extensive(self) -> bool:
        return self is Kind.EXTENSIVE


class KindMismatch(TypeError):
    """An intensive value reached an extensive path, or the reverse.

    Its own exception type because this is the error section 7 singles out, and
    because a caller that catches it has a real bug rather than a bad row.
    """


@dataclass(frozen=True, slots=True)
class TractEstimate:
    """One published tract-level value, as stored in `tract_demographics`.

    `estimate` of None means upstream had nothing for this tract. It is an
    absence and stays one; section 11 forbids coercing it to zero or to the
    median. `margin_of_error` of None means the value came without a published
    margin, which is true of the modeled AirToxScreen surfaces and is different
    from a margin of zero.
    """

    tract_geoid: str
    variable: str
    estimate: float | None
    margin_of_error: float | None
    kind: Kind

    @property
    def present(self) -> bool:
        return self.estimate is not None

    def require(self, kind: Kind) -> None:
        if self.kind is not kind:
            raise KindMismatch(
                f"{self.variable} for tract {self.tract_geoid} is {self.kind.value}, "
                f"but it reached the {kind.value} path. Section 7: apportioning a rate "
                "or averaging a count is the most common error in this step."
            )


@dataclass(frozen=True, slots=True)
class HexValue:
    """One interpolated value on one hexagon, with its uncertainty.

    `population_support` is the share of the hex's block-apportioned population
    that sat under a tract which actually had this value. It is 1.0 when every
    contributing tract reported, and less when some did not. Section 11 keeps
    absences from becoming zeros, so a partially supported hex reports the
    partial value and this number alongside it rather than a confident total
    over a hole; section 12's coverage and spatial terms are where that gets
    priced in.
    """

    h3: str
    variable: str
    kind: Kind
    value: float | None
    margin_of_error: float | None
    coefficient_of_variation: float | None
    population_support: float
    contributing_tracts: int
    #: True when a derived rate's margin used the ratio formula because the
    #: proportion formula's radicand went negative. The result is the Census
    #: Bureau's conservative alternative, so the margin is an overstatement
    #: rather than an error, and saying so keeps it from reading as one.
    moe_is_conservative: bool = False

    @property
    def present(self) -> bool:
        return self.value is not None

    @property
    def high_uncertainty(self) -> bool:
        """Above the 0.30 threshold of sections 7 and 12. Still used."""
        cv = self.coefficient_of_variation
        return cv is not None and cv > HIGH_UNCERTAINTY_CV

    @classmethod
    def absent(cls, h3: str, variable: str, kind: Kind) -> "HexValue":
        """No contributing tract had a value. Not zero, not the median."""
        return cls(
            h3=h3,
            variable=variable,
            kind=kind,
            value=None,
            margin_of_error=None,
            coefficient_of_variation=None,
            population_support=0.0,
            contributing_tracts=0,
        )


def standard_error(margin_of_error: float) -> float:
    """Recover a standard error from a published 90 percent margin."""
    return margin_of_error / ACS_MOE_Z


def combine_in_quadrature(terms: Iterable[float]) -> float:
    """The Census Bureau's approximation for the margin of a derived sum.

        MOE(sum of a_i * X_i)  ~  sqrt( sum of (a_i * MOE(X_i))^2 )

    Pass the already-weighted margins. The approximation assumes the component
    estimates are independent, which for distinct census tracts is close enough
    to true to be the Bureau's own published guidance, and it is what section 7
    specifies.
    """
    return math.sqrt(math.fsum(term * term for term in terms))


def coefficient_of_variation(estimate: float | None, margin_of_error: float | None) -> float | None:
    """CV = standard error / estimate, undefined at an estimate of zero.

    Returned as None rather than infinity when the estimate is zero or absent.
    A zero count with a non-zero margin is a real and common ACS outcome, and
    the honest statement about it is that the ratio does not exist, not that
    uncertainty is infinite. Section 12's spatial term treats an undefined CV
    as unknown rather than as worst-case.
    """
    if estimate is None or margin_of_error is None:
        return None
    if estimate == 0:
        return None
    return standard_error(margin_of_error) / abs(estimate)


def proportion_moe(
    numerator: float,
    numerator_moe: float,
    denominator: float,
    denominator_moe: float,
) -> tuple[float, bool]:
    """Margin of error for a rate derived from two interpolated counts.

    Section 7 requires that where a rate has a published numerator and
    denominator, both are interpolated as extensive quantities and the rate is
    derived once at the end. The margin for that final division is the Census
    Bureau's proportion formula, for a numerator that is a subset of its
    denominator:

        MOE(P)  ~  (1 / Y) * sqrt( MOE(X)^2 - P^2 * MOE(Y)^2 )

    When the radicand is negative the Bureau directs the analyst to the ratio
    formula instead, which adds where the proportion formula subtracts:

        MOE(R)  ~  (1 / Y) * sqrt( MOE(X)^2 + P^2 * MOE(Y)^2 )

    Returns the margin and whether that fallback was taken. The fallback
    overstates the margin rather than understating it, which is the direction
    an honest confidence score should err in.
    """
    if denominator == 0:
        raise ZeroDivisionError("a rate with a zero denominator has no margin of error")
    ratio = numerator / denominator
    subtractive = numerator_moe**2 - (ratio**2) * (denominator_moe**2)
    if subtractive >= 0:
        return math.sqrt(subtractive) / abs(denominator), False
    additive = numerator_moe**2 + (ratio**2) * (denominator_moe**2)
    return math.sqrt(additive) / abs(denominator), True
