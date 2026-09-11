"""The two formulas of methodology section 7, and the rule about rates.

Extensive quantities are counts and sum across space, so they are apportioned:

    V(h) = sum over t, sum over blocks b in t of
               V(t) * [ P(b) / P(t) ] * [ area(b n h) / area(b) ]

which, once `pipeline.dasymetric.weights` has folded the block layer into
`pop_weight`, is one multiplication per tract-hex pair.

Intensive quantities are rates, ratios, and modeled risks. They do not sum, so
they are combined as a population-weighted mean of the source values
overlapping the hex:

    R(h) = [ sum over t of R(t) * P(t n h) ] / [ sum over t of P(t n h) ]

Section 7 also forbids recomputing a rate from independently interpolated parts
without care, and requires the opposite discipline where the parts exist: where
a rate has a published numerator and denominator, both are interpolated as
extensive quantities and the rate is derived once at the end. `derive_rate` is
that ending, and it is the preferred path for every ACS rate in section 8.4.
The population-weighted mean is for the values that arrive as rates already,
with no numerator to be had, such as the AirToxScreen cancer risk and
respiratory hazard surfaces.

Preferring the derived path is not pedantry. The population-weighted mean
weights each tract by its total population, but a rate's own denominator is
rarely total population: the poverty rate's denominator is the population for
whom poverty status is determined, the unemployment rate's is the civilian
labour force, the housing cost burden's is low-income households. Weighting by
the wrong denominator biases the hex value whenever the two differ across the
tracts meeting in that hex. Interpolating the published numerator and
denominator separately and dividing once at the end has no such error, and the
unit tests hold the two paths against each other on a case where they must
agree.
"""

import math
from collections.abc import Iterable, Mapping

from pipeline.dasymetric.quantities import (
    HexValue,
    Kind,
    KindMismatch,
    TractEstimate,
    coefficient_of_variation,
    combine_in_quadrature,
    proportion_moe,
)
from pipeline.dasymetric.weights import Crosswalk, TractHexWeight


def _one_variable(
    estimates: Iterable[TractEstimate], kind: Kind
) -> tuple[str, dict[str, TractEstimate]]:
    """Index estimates by tract, insisting they are one variable of one kind."""
    by_tract: dict[str, TractEstimate] = {}
    name: str | None = None
    for estimate in estimates:
        estimate.require(kind)
        if name is None:
            name = estimate.variable
        elif estimate.variable != name:
            raise ValueError(
                f"interpolate one variable at a time; got {name!r} and {estimate.variable!r}"
            )
        if estimate.tract_geoid in by_tract:
            raise ValueError(
                f"tract {estimate.tract_geoid} appears twice for {estimate.variable!r}"
            )
        by_tract[estimate.tract_geoid] = estimate
    if name is None:
        raise ValueError("no estimates to interpolate")
    return name, by_tract


def _support(rows: Iterable[TractHexWeight], supported: Iterable[str]) -> float:
    """Share of a hex's population sitting under a tract that reported."""
    rows = tuple(rows)
    total = math.fsum(row.population for row in rows)
    if total <= 0:
        return 0.0
    names = set(supported)
    return math.fsum(row.population for row in rows if row.tract_geoid in names) / total


def interpolate_extensive(
    crosswalk: Crosswalk,
    estimates: Iterable[TractEstimate],
) -> dict[str, HexValue]:
    """Apportion a count onto hexes through the crosswalk's population weights.

    A tract without an estimate contributes nothing and is not imputed, per
    section 11. The share of the hex's population that such tracts represent is
    reported as a shortfall in `population_support`, so a hex assembled over a
    reporting gap is distinguishable from one assembled over complete data
    rather than both arriving as confident totals.

    The margin of error is the quadrature sum of the weighted tract margins,
    which is the Census Bureau's approximation for a derived sum and what
    section 7 specifies. If any contributing tract has an estimate but no
    published margin, the hex margin is None: quadrature over the subset that
    does have margins would understate the uncertainty, and understating it is
    the one direction that matters here, because the coefficient of variation
    feeds a confidence score.
    """
    variable, by_tract = _one_variable(estimates, Kind.EXTENSIVE)

    values: dict[str, HexValue] = {}
    for h3 in crosswalk.hexes():
        rows = crosswalk.for_hex(h3)
        contributing = [
            (row, by_tract[row.tract_geoid])
            for row in rows
            if row.tract_geoid in by_tract and by_tract[row.tract_geoid].present
        ]
        if not contributing:
            values[h3] = HexValue.absent(h3, variable, Kind.EXTENSIVE)
            continue

        total = math.fsum(
            row.pop_weight * float(estimate.estimate or 0.0) for row, estimate in contributing
        )

        if any(estimate.margin_of_error is None for _, estimate in contributing):
            margin: float | None = None
        else:
            margin = combine_in_quadrature(
                row.pop_weight * float(estimate.margin_of_error or 0.0)
                for row, estimate in contributing
            )

        values[h3] = HexValue(
            h3=h3,
            variable=variable,
            kind=Kind.EXTENSIVE,
            value=total,
            margin_of_error=margin,
            coefficient_of_variation=coefficient_of_variation(total, margin),
            population_support=_support(rows, (row.tract_geoid for row, _ in contributing)),
            contributing_tracts=len(contributing),
        )
    return values


def interpolate_intensive(
    crosswalk: Crosswalk,
    estimates: Iterable[TractEstimate],
) -> dict[str, HexValue]:
    """Combine a rate onto hexes as a population-weighted mean.

    Weights are renormalized over the tracts that actually reported, so a hex
    whose second tract is missing takes the first tract's rate rather than a
    mean dragged toward zero. The population it was missing is still visible in
    `population_support`.

    The margins are combined in quadrature with the normalized population
    weights treated as constants. That is exact rather than an approximation
    here, which is a direct benefit of the ancillary layer section 7 chose: the
    weights come from 2020 Decennial PL 94-171 counts, which are counts and
    carry no sampling variance of their own. Had the weights been ACS
    population estimates, this step would have needed a ratio-variance
    correction.

    A hex with no block population at all falls back to tract area share.
    Section 5 leaves such cells unscored below 25 people, so this only affects
    values that are displayed rather than ranked, and `population_support` is
    0.0 whenever it happens.
    """
    variable, by_tract = _one_variable(estimates, Kind.INTENSIVE)

    values: dict[str, HexValue] = {}
    for h3 in crosswalk.hexes():
        rows = crosswalk.for_hex(h3)
        contributing = [
            (row, by_tract[row.tract_geoid])
            for row in rows
            if row.tract_geoid in by_tract and by_tract[row.tract_geoid].present
        ]
        if not contributing:
            values[h3] = HexValue.absent(h3, variable, Kind.INTENSIVE)
            continue

        support = math.fsum(row.population for row, _ in contributing)
        if support > 0:
            weights = [row.population / support for row, _ in contributing]
        else:
            areal = math.fsum(row.area_weight for row, _ in contributing)
            weights = (
                [row.area_weight / areal for row, _ in contributing]
                if areal > 0
                else [1.0 / len(contributing)] * len(contributing)
            )

        mean = math.fsum(
            weight * float(estimate.estimate or 0.0)
            for weight, (_, estimate) in zip(weights, contributing, strict=True)
        )

        if any(estimate.margin_of_error is None for _, estimate in contributing):
            margin: float | None = None
        else:
            margin = combine_in_quadrature(
                weight * float(estimate.margin_of_error or 0.0)
                for weight, (_, estimate) in zip(weights, contributing, strict=True)
            )

        values[h3] = HexValue(
            h3=h3,
            variable=variable,
            kind=Kind.INTENSIVE,
            value=mean,
            margin_of_error=margin,
            coefficient_of_variation=coefficient_of_variation(mean, margin),
            population_support=_support(rows, (row.tract_geoid for row, _ in contributing)),
            contributing_tracts=len(contributing),
        )
    return values


def derive_rate(
    numerator: Mapping[str, HexValue],
    denominator: Mapping[str, HexValue],
    *,
    variable: str,
    scale: float = 1.0,
) -> dict[str, HexValue]:
    """Divide two interpolated counts, once, at the end.

    This is the section 7 rule for every rate whose parts are published: the
    numerator and the denominator are each interpolated as extensive
    quantities, and the division happens here and nowhere earlier. Dividing per
    tract and then averaging the quotients, or interpolating a published rate
    directly when its parts were available, both introduce the inconsistency
    section 7 is guarding against.

    `scale` is applied to the result, so a proportion becomes a percent with
    `scale=100.0`. The margin scales with it and the coefficient of variation,
    being a ratio, does not move.

    A hex whose denominator is zero or absent gets an absent rate. Zero people
    for whom poverty status is determined is not a poverty rate of zero; it is
    the absence of a poverty rate, and section 11 keeps the two apart.
    """
    for source, kind_name in ((numerator, "numerator"), (denominator, "denominator")):
        for value in source.values():
            if value.kind is not Kind.EXTENSIVE:
                raise KindMismatch(
                    f"the {kind_name} of a derived rate must be interpolated as an "
                    f"extensive quantity; {value.variable!r} is {value.kind.value}"
                )

    rates: dict[str, HexValue] = {}
    for h3, top in numerator.items():
        bottom = denominator.get(h3)
        if bottom is None or not top.present or not bottom.present or bottom.value == 0:
            rates[h3] = HexValue.absent(h3, variable, Kind.INTENSIVE)
            continue

        top_value = float(top.value or 0.0)
        bottom_value = float(bottom.value or 0.0)
        rate = scale * top_value / bottom_value

        conservative = False
        if top.margin_of_error is None or bottom.margin_of_error is None:
            margin: float | None = None
        else:
            unscaled, conservative = proportion_moe(
                top_value, top.margin_of_error, bottom_value, bottom.margin_of_error
            )
            margin = scale * unscaled

        rates[h3] = HexValue(
            h3=h3,
            variable=variable,
            kind=Kind.INTENSIVE,
            value=rate,
            margin_of_error=margin,
            coefficient_of_variation=coefficient_of_variation(rate, margin),
            population_support=min(top.population_support, bottom.population_support),
            contributing_tracts=max(top.contributing_tracts, bottom.contributing_tracts),
            moe_is_conservative=conservative,
        )
    return rates


def interpolate(
    crosswalk: Crosswalk,
    estimates: Iterable[TractEstimate],
) -> dict[str, dict[str, HexValue]]:
    """Interpolate many variables at once, each down the path its kind demands.

    Returns variable name to hex to value. The dispatch is on
    `TractEstimate.kind`, which comes straight from the `is_extensive` column
    of `tract_demographics`, so the decision that section 7 warns about is made
    once at ingest and is never re-guessed here.
    """
    grouped: dict[str, list[TractEstimate]] = {}
    kinds: dict[str, Kind] = {}
    for estimate in estimates:
        known = kinds.setdefault(estimate.variable, estimate.kind)
        if known is not estimate.kind:
            raise KindMismatch(
                f"{estimate.variable!r} arrives as both {known.value} and "
                f"{estimate.kind.value}; one variable has one kind"
            )
        grouped.setdefault(estimate.variable, []).append(estimate)

    out: dict[str, dict[str, HexValue]] = {}
    for variable, batch in grouped.items():
        if kinds[variable].is_extensive:
            out[variable] = interpolate_extensive(crosswalk, batch)
        else:
            out[variable] = interpolate_intensive(crosswalk, batch)
    return out


def max_coefficient_variation(values: Iterable[HexValue]) -> float | None:
    """Worst CV among the estimates behind one hex.

    This is `hex_demographics.max_coefficient_variation`. Above 0.30 the
    estimate is still used and `c_spatial` falls instead, per sections 7 and
    12. Undefined coefficients, from an estimate of zero, are skipped rather
    than treated as worst-case.
    """
    seen = [v.coefficient_of_variation for v in values if v.coefficient_of_variation is not None]
    return max(seen) if seen else None
