"""Methodology section 13.5: the interpolation the paper rejected, built on purpose.

Section 7 opens by rejecting simple areal weighting, because distributing a
tract's value by area share "would assign an unpopulated third of a rural tract
the same per-area population as its town". Section 13.5 asks for the score
recomputed that way anyway, to quantify how much the ancillary layer actually
changes. An argument that the block layer is worth its cost is worth more with a
number beside it, and a project that never measured the thing it rejected would
be asking a reader to take section 7 on faith.

**What the counterfactual holds fixed, and what it changes.** Exactly one thing
changes: the population estimator. Section 7 estimates P(t ∩ h) from 2020
Decennial block counts; this module estimates it by assuming population is
uniform within the tract:

    P_areal(t ∩ h) = P(t) · area(t ∩ h) / area(t)

Both section 7 formulas then run unchanged over it. Extensive quantities are
apportioned through that share, which is simple areal weighting written out:

    V(h) = Σ_t V(t) · [ area(t ∩ h) / area(t) ]

Intensive quantities stay a population-weighted mean, now weighted by the
uniform-density estimate rather than the block-derived one. That is deliberate
and it is the more conservative comparison. Weighting a rate by raw overlap area
instead would change two things at once — the population estimator *and* the
formula — and the resulting divergence could not be attributed to either. This
way, every difference the check reports is attributable to the ancillary layer,
which is the only question section 13.5 asks.

**Nothing here is a fallback.** This is not a degraded mode the pipeline enters
when blocks are missing; `build_crosswalk` already handles that case, per-tract,
and marks the rows it did it to. This is a whole second crosswalk built to be
compared against and then discarded. It is never written to `tract_hex_weight`,
never scored for publication, and reaches nothing outside
`burden.robustness.interpolation_sensitivity`.

**It is still made of people.** `population` on the returned rows carries the
areally-apportioned population estimate, not an area, so `Crosswalk.population`
answers in residents and section 5's 25-person threshold reads it correctly.
That matters more than it looks: the two methods disagree about which cells clear
that threshold, and which hexes get scored at all is the largest single
consequence of the choice. A crosswalk whose population column held square
metres would have hidden it behind a unit error.

**The tract total is conserved, which is what makes the comparison fair.** Area
shares sum to 1 over the hexes a tract touches, exactly as population shares do,
so a tract's people all land somewhere under both methods and the statewide
reconciliation of section 7 closes for both. The two differ in *where* the people
go, never in how many there are, and `reconcile` will say so for either.
"""

import math
from collections.abc import Mapping

from pipeline.dasymetric.weights import (
    Crosswalk,
    TractHexWeight,
    crosswalk_from_weights,
    tract_populations,
)

#: How far a tract's area shares may fall from summing to 1 before the crosswalk
#: is refused. The shares come out of `build_crosswalk` normalized per block, so
#: the residual here is floating-point accumulation over a tract's hexes and
#: nothing else. A gap larger than this means the crosswalk is missing rows,
#: and apportioning a tract's population across a subset of its own hexes would
#: quietly lose people to a bug somewhere upstream.
AREA_SHARE_TOLERANCE = 1e-6


class PartialCrosswalk(Exception):
    """A tract's area shares do not sum to 1, so it cannot be re-apportioned.

    Raised rather than renormalized. Renormalizing would produce a crosswalk
    that looks complete and quietly redistributes a tract's whole population
    across whichever of its hexes happened to be loaded, and the resulting
    comparison would report a loading bug as a property of section 7.
    """


def areal_counterpart(crosswalk: Crosswalk) -> Crosswalk:
    """The same crosswalk with the ancillary layer taken away.

    Takes a dasymetric crosswalk — freshly built by `build_crosswalk` or read
    back from `tract_hex_weight` through `crosswalk_from_weights`, which behave
    identically — and returns the crosswalk simple areal weighting would have
    produced from the same geometry.

    `pop_weight_from_area` is set on every row. That flag already means "this
    weight is an area share rather than a population share", which is exactly
    what is true here, so a consumer that already distinguishes the two needs no
    new thing to check.
    """
    totals = tract_populations(crosswalk)
    _require_complete(crosswalk)

    rows = tuple(
        TractHexWeight(
            tract_geoid=row.tract_geoid,
            h3=row.h3,
            # P(t) · area(t n h) / area(t): the tract's people spread by area,
            # which is what "uniform within the tract" means.
            population=totals[row.tract_geoid] * row.area_weight,
            pop_weight=row.area_weight,
            area_weight=row.area_weight,
            # Geometry, untouched. The blocks a hex was built from are a fact
            # about the grid, not about which weighting reads it, and c_spatial
            # in section 12 should describe the same cell under both methods.
            block_count=row.block_count,
            mean_block_area_m2=row.mean_block_area_m2,
            pop_weight_from_area=True,
        )
        for row in crosswalk.weights
    )

    return crosswalk_from_weights(rows)


def divergence(dasymetric: Crosswalk, areal: Crosswalk) -> Mapping[str, float]:
    """Per hex, how many people the two methods disagree about placing there.

    The raw material of section 13.5's third check, before any score exists. A
    hex where the two agree is one the ancillary layer did nothing for; the
    hexes where they disagree are where section 7 earned its cost, and their
    distribution is more informative than any single summary of it.

    Signed, so that a reader can see the direction: positive where areal
    weighting puts more people than the block layer does, which is the rural
    over-assignment section 7 opens by describing.
    """
    hexes = set(dasymetric.hexes()) | set(areal.hexes())
    return {h3: areal.population(h3) - dasymetric.population(h3) for h3 in sorted(hexes)}


def _require_complete(crosswalk: Crosswalk) -> None:
    shares: dict[str, float] = {}
    for row in crosswalk.weights:
        shares[row.tract_geoid] = shares.get(row.tract_geoid, 0.0) + row.area_weight

    for tract, total in sorted(shares.items()):
        if not math.isclose(total, 1.0, abs_tol=AREA_SHARE_TOLERANCE):
            raise PartialCrosswalk(
                f"tract {tract} holds area shares summing to {total!r} rather than 1, "
                f"so its rows are not the whole tract; re-apportioning its population "
                f"across them would lose or invent people"
            )
