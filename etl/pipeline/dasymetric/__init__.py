"""Dasymetric areal interpolation from census tracts to hexagons.

Methodology section 7, implemented. Three of the five sources are tract-level,
and moving them to hexagons is the most consequential transformation in the
pipeline. Doing it naively by area share would assign an unpopulated third of a
rural tract the same per-area population as its town, so the tract values are
distributed through an ancillary layer of 2020 Decennial Census block
population counts (PL 94-171) instead.

The order of work, for one state:

    crosswalk, check = await build.build_and_verify(
        conn, state_fips="22", acs_vintage="2019-2023"
    )

which is `build.build_state_crosswalk` county by county, then the statewide
population check this ticket is accepted on. The steps it composes are usable
on their own, and the unit tests drive them directly:

    overlaps  = await postgis.load_block_overlaps(conn, county_fips=...)
    crosswalk = weights.build_crosswalk(overlaps)          # section 7 steps 1-2
    values    = interpolate.interpolate(crosswalk, tract_estimates)
    rate      = interpolate.derive_rate(numerator, denominator, variable="P1")
    report    = reconcile.require(reconcile.reconcile_population(...))

Four rules from section 7 are load-bearing, and each is enforced somewhere
rather than merely documented:

1. Counts are apportioned, rates are averaged over population, and the two are
   never confused. `Kind` travels on every value and the interpolation
   functions raise `KindMismatch` on the wrong one.

2. Where a rate has a published numerator and denominator, both are
   interpolated as counts and the rate is derived once at the end.
   `derive_rate` is that division and it refuses non-extensive inputs.

3. Margins of error are combined in quadrature under the Census Bureau's
   approximation for derived sums, and the resulting coefficient of variation
   travels with the value into the confidence score of section 12. Nothing is
   dropped for being uncertain; section 7 is explicit that dropping
   high-uncertainty estimates preferentially removes small and rural
   populations.

4. Statewide totals after interpolation match tract totals. `reconcile` states
   the tolerance, why that number, and what the two possible causes of a gap
   are.

The known error is section 7's own and is not restated here: step 2 assumes
population is uniform within a census block. `TractHexWeight.mean_block_area_m2`
carries the size of the blocks a hex was built from, which is what turns that
paragraph into the `c_spatial` term of section 12.
"""

from pipeline.dasymetric.build import (
    TOTAL_POPULATION,
    CountyCrosswalk,
    PopulationCheck,
    StateCrosswalk,
    build_and_verify,
    build_county_crosswalk,
    build_state_crosswalk,
    verify_statewide_population,
)
from pipeline.dasymetric.interpolate import (
    derive_rate,
    interpolate,
    interpolate_extensive,
    interpolate_intensive,
    max_coefficient_variation,
)
from pipeline.dasymetric.quantities import (
    ACS_MOE_Z,
    HIGH_UNCERTAINTY_CV,
    HexValue,
    Kind,
    KindMismatch,
    TractEstimate,
    coefficient_of_variation,
    combine_in_quadrature,
    proportion_moe,
    standard_error,
)
from pipeline.dasymetric.reconcile import (
    DEFAULT_RELATIVE_TOLERANCE,
    Reconciliation,
    ReconciliationFailed,
    reconcile_crosswalk,
    reconcile_population,
    require,
)
from pipeline.dasymetric.weights import (
    BlockOverlap,
    Crosswalk,
    CrosswalkReport,
    TractHexWeight,
    UncoveredBlock,
    build_crosswalk,
    crosswalk_from_weights,
    tract_populations,
)

__all__ = [
    "ACS_MOE_Z",
    "DEFAULT_RELATIVE_TOLERANCE",
    "HIGH_UNCERTAINTY_CV",
    "TOTAL_POPULATION",
    "BlockOverlap",
    "CountyCrosswalk",
    "Crosswalk",
    "CrosswalkReport",
    "HexValue",
    "Kind",
    "KindMismatch",
    "PopulationCheck",
    "Reconciliation",
    "ReconciliationFailed",
    "StateCrosswalk",
    "TractEstimate",
    "TractHexWeight",
    "UncoveredBlock",
    "build_and_verify",
    "build_county_crosswalk",
    "build_crosswalk",
    "build_state_crosswalk",
    "coefficient_of_variation",
    "combine_in_quadrature",
    "crosswalk_from_weights",
    "derive_rate",
    "interpolate",
    "interpolate_extensive",
    "interpolate_intensive",
    "max_coefficient_variation",
    "proportion_moe",
    "reconcile_crosswalk",
    "reconcile_population",
    "require",
    "standard_error",
    "tract_populations",
    "verify_statewide_population",
]
