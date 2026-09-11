"""Steps 1 and 2 of methodology section 7: building the tract-to-hex crosswalk.

Section 7 moves tract-level values onto hexagons through an ancillary layer of
2020 Decennial Census block population counts (PL 94-171). Blocks are roughly
two orders of magnitude finer than tracts, and their populations are counts
rather than estimates, which is the whole reason they are trusted to distribute
tract values. Doing this naively by area share instead would give an
unpopulated third of a rural tract the same per-area population as its town.

This module does the arithmetic half of the transformation. The geometry half,
intersecting blocks with the hex grid, is PostGIS work and lives in
`pipeline.dasymetric.postgis`; it hands back one `BlockOverlap` per block-hex
pair and everything from there is ordinary numbers. The split is deliberate:
bad geometry announces itself, bad arithmetic does not, so the arithmetic is
the part that is pure and unit tested against a case that can be checked by
hand.

The output is `tract_hex_weight`, defined in migration 0003. It is stored
rather than recomputed because every tract-sourced indicator reads it.

**Known error, carried rather than restated.** Section 7 already records it:
step 2 assumes population is uniform within a census block, which is wrong for
large rural blocks; it is a far smaller error than assuming uniformity within a
tract, blocks are the finest free geography available, and the residual error is
largest exactly where blocks are largest, which is where the spatial term of the
confidence score is already lowest. `TractHexWeight.mean_block_area_m2` is what
carries that fact forward into `c_spatial`, so the limitation is measured per
hex rather than only described in prose.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# Frozen slotted dataclasses rather than pydantic models throughout this
# package. These are bulk geometry rows: Louisiana has on the order of a
# million block-hex overlaps, and the validation each row needs is a handful of
# sign checks that `build_crosswalk` applies once, in one place, with a message
# that names the offending block.

#: A block's hex shares should sum to 1. Polygon clipping leaves slivers, so
#: they will not, quite. Anything inside this band of 1 is precision and is
#: normalized away; anything outside it is a hole in the grid and is reported.
COVERAGE_SLIVER_TOLERANCE = 0.005


@dataclass(frozen=True, slots=True)
class BlockOverlap:
    """One 2020 census block's intersection with one hexagon.

    `block_population` and `block_area_m2` repeat on every row for a given
    block. That is how the PostGIS join returns them, and carrying them along
    keeps this module free of a second lookup table.
    """

    block_geoid: str
    tract_geoid: str
    h3: str
    block_population: int
    block_area_m2: float
    overlap_area_m2: float


@dataclass(frozen=True, slots=True)
class TractHexWeight:
    """One row of `tract_hex_weight`, the stored result of section 7 steps 1-2.

    Two weights, because the two formulas in section 7 need different ones.

    `pop_weight` is P(t n h) / P(t), the share of the tract's population that
    falls in this hex. It is the multiplier for extensive quantities.

    `population` is P(t n h) itself, the block-apportioned population of the
    overlap. It is the weight for intensive quantities, which are combined as a
    population-weighted mean rather than apportioned.

    `area_weight` is the share of the tract's area in this hex. It is not a
    substitute for `pop_weight` and is never used as one; it is stored because
    it is the only ancillary information left for a tract whose 2020 block
    population is zero everywhere, and because the gap between the two weights
    is the quantity that says how much the dasymetric step actually did.
    """

    tract_geoid: str
    h3: str
    population: float
    pop_weight: float
    area_weight: float
    block_count: int
    mean_block_area_m2: float
    #: True when the tract held no 2020 block population and `pop_weight` fell
    #: back to area share. Carried so a consumer can tell a dasymetric weight
    #: from an areal one rather than assuming every row is the former.
    pop_weight_from_area: bool = False


@dataclass(frozen=True, slots=True)
class UncoveredBlock:
    """A block whose hex shares did not add up, and by how much."""

    block_geoid: str
    tract_geoid: str
    population: int
    coverage: float


@dataclass(frozen=True, slots=True)
class CrosswalkReport:
    """What `build_crosswalk` saw that a caller should not have to infer.

    `unassigned_population` is the 2020 block population that found no hexagon
    at all. It is a statement about the ancillary layer, not about any ACS
    value: a stranded block leaves the tract's weights on both sides, so the
    surviving weights still sum to 1 and the tract's estimate still lands in
    full. What is lost there is spatial detail, and this is the number that
    measures how much.
    """

    block_count: int
    tract_count: int
    hex_count: int
    total_block_population: int
    unassigned_population: int
    uncovered_blocks: tuple[UncoveredBlock, ...] = ()
    #: Tracts with no 2020 block population at all, whose weights are areal.
    area_fallback_tracts: tuple[str, ...] = ()

    def describe(self) -> str:
        lines = [
            f"crosswalk: {self.block_count} blocks -> {self.hex_count} hexes "
            f"across {self.tract_count} tracts",
            f"  block population {self.total_block_population}, "
            f"unassigned {self.unassigned_population}",
        ]
        if self.uncovered_blocks:
            lines.append(f"  {len(self.uncovered_blocks)} blocks short of full hex coverage")
        if self.area_fallback_tracts:
            lines.append(
                f"  {len(self.area_fallback_tracts)} tracts had no 2020 block population; "
                "their weights are areal"
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Crosswalk:
    """The stored interpolation, indexed the two ways the formulas read it."""

    weights: tuple[TractHexWeight, ...]
    report: CrosswalkReport
    _by_tract: dict[str, tuple[TractHexWeight, ...]] = field(default_factory=dict, repr=False)
    _by_hex: dict[str, tuple[TractHexWeight, ...]] = field(default_factory=dict, repr=False)

    def for_tract(self, tract_geoid: str) -> tuple[TractHexWeight, ...]:
        """Every hex this tract touches. The inner sum of the section 7 formulas."""
        return self._by_tract.get(tract_geoid, ())

    def for_hex(self, h3: str) -> tuple[TractHexWeight, ...]:
        """Every tract touching this hex."""
        return self._by_hex.get(h3, ())

    def hexes(self) -> tuple[str, ...]:
        return tuple(self._by_hex)

    def tracts(self) -> tuple[str, ...]:
        return tuple(self._by_tract)

    def population(self, h3: str) -> float:
        """Block-apportioned population of a hex, summed over its tracts."""
        return sum(w.population for w in self.for_hex(h3))

    def mean_block_area_m2(self, h3: str) -> float | None:
        """Population-weighted mean source block area, for the c_spatial term.

        Weighted by population rather than by tract count because the
        uniformity error of section 7 matters in proportion to the number of
        people it misplaces, not to the number of tracts it touches.
        """
        rows = self.for_hex(h3)
        if not rows:
            return None
        support = sum(w.population for w in rows)
        if support <= 0:
            return sum(w.mean_block_area_m2 for w in rows) / len(rows)
        return sum(w.mean_block_area_m2 * w.population for w in rows) / support


def _validate(overlap: BlockOverlap) -> None:
    if overlap.block_population < 0:
        raise ValueError(
            f"block {overlap.block_geoid} has negative population "
            f"{overlap.block_population}; PL 94-171 counts are counts"
        )
    if overlap.block_area_m2 <= 0:
        raise ValueError(
            f"block {overlap.block_geoid} has non-positive area {overlap.block_area_m2}; "
            "a block with no area cannot apportion anything"
        )
    if overlap.overlap_area_m2 < 0:
        raise ValueError(
            f"block {overlap.block_geoid} x hex {overlap.h3} has negative overlap area "
            f"{overlap.overlap_area_m2}"
        )


def build_crosswalk(
    overlaps: Iterable[BlockOverlap],
    *,
    sliver_tolerance: float = COVERAGE_SLIVER_TOLERANCE,
) -> Crosswalk:
    """Fold block-hex overlaps into `tract_hex_weight` rows.

    Section 7, steps 1 and 2, in one pass:

        P(t n h)         = sum over blocks b in t of  P(b) * [ area(b n h) / area(b) ]
        pop_weight(t, h) = P(t n h) / P(t)

    so that an extensive value multiplied through `pop_weight` reproduces the
    section 7 formula exactly, and the weights for a tract sum to 1. That last
    property is what makes the statewide reconciliation an identity rather than
    an approximation, and it is why each block's shares are normalized to sum
    to 1 before anything is accumulated: a polygon clip against a hex grid
    leaves slivers, and left alone those slivers would leak a few people per
    block out of the statewide total for no reason anyone could later explain.

    Normalization is bounded on purpose. A block whose shares fall further than
    `sliver_tolerance` from 1 is not suffering from clipping precision, it is
    sitting over a hole in the hex grid, and scaling its shares up to 1 would
    paper over a real defect. Those blocks are reported instead, and the
    population of a block that intersects no hexagon at all is reported as
    unassigned so the reconciliation can account for it by name.
    """
    by_block: dict[str, list[BlockOverlap]] = defaultdict(list)
    for overlap in overlaps:
        _validate(overlap)
        by_block[overlap.block_geoid].append(overlap)

    # Accumulated per tract-hex pair, then divided through at the end.
    pop_in_cell: dict[tuple[str, str], float] = defaultdict(float)
    area_in_cell: dict[tuple[str, str], float] = defaultdict(float)
    blocks_in_cell: dict[tuple[str, str], set[str]] = defaultdict(set)
    block_area_sum_in_cell: dict[tuple[str, str], float] = defaultdict(float)

    tract_population: dict[str, float] = defaultdict(float)
    tract_area: dict[str, float] = defaultdict(float)

    uncovered: list[UncoveredBlock] = []
    unassigned_population = 0
    total_block_population = 0

    for block_geoid, rows in by_block.items():
        first = rows[0]
        tract = first.tract_geoid
        population = first.block_population
        block_area = first.block_area_m2
        total_block_population += population

        clipped = sum(row.overlap_area_m2 for row in rows)
        coverage = clipped / block_area

        if clipped <= 0:
            # The block intersects no hexagon, so it leaves the ancillary layer
            # entirely: its 2020 count is absent from every hex population, and
            # `unassigned_population` is what says so.
            #
            # Note what this does and does not do to a later ACS pass. The
            # block is removed from both sides of the tract's weights, so the
            # surviving weights still sum to 1 and the tract's ACS value still
            # lands in full, spread across the part of the tract that is
            # covered. Spatial detail is lost; the value is not. The
            # alternative, holding back a share of the tract's value to match
            # the lost block, would put a hole in the statewide total to record
            # a hole in the grid, and one defect is enough.
            uncovered.append(UncoveredBlock(block_geoid, tract, population, 0.0))
            unassigned_population += population
            continue

        if abs(coverage - 1.0) > sliver_tolerance:
            uncovered.append(UncoveredBlock(block_geoid, tract, population, coverage))

        # A tract's totals are built from the blocks that were actually
        # apportioned, so that the weights below sum to 1 over the hexes that
        # exist. A block dropped above is absent from both sides.
        tract_population[tract] += population
        tract_area[tract] += block_area

        for row in rows:
            if row.overlap_area_m2 <= 0:
                continue
            share = row.overlap_area_m2 / clipped
            cell = (tract, row.h3)
            pop_in_cell[cell] += population * share
            area_in_cell[cell] += block_area * share
            blocks_in_cell[cell].add(block_geoid)
            block_area_sum_in_cell[cell] += block_area

    weights: list[TractHexWeight] = []
    area_fallback: list[str] = []
    for cell, population_in_hex in sorted(pop_in_cell.items()):
        tract, h3 = cell
        area_share = area_in_cell[cell] / tract_area[tract]
        total_population = tract_population[tract]
        if total_population > 0:
            pop_share = population_in_hex / total_population
            from_area = False
        else:
            # P(b)/P(t) is 0/0. Section 7 does not reach this case because a
            # tract with people has blocks with people, but ACS vintages and
            # 2020 blocks do not always agree, and a tract the ACS thinks holds
            # a handful of people must still land somewhere or the statewide
            # total will not close. Area share is the only ancillary
            # information left, and the row records that this is what it is.
            pop_share = area_share
            from_area = True
            if tract not in area_fallback:
                area_fallback.append(tract)

        members = blocks_in_cell[cell]
        weights.append(
            TractHexWeight(
                tract_geoid=tract,
                h3=h3,
                population=population_in_hex,
                pop_weight=pop_share,
                area_weight=area_share,
                block_count=len(members),
                mean_block_area_m2=block_area_sum_in_cell[cell] / len(members),
                pop_weight_from_area=from_area,
            )
        )

    return _index(
        tuple(weights),
        CrosswalkReport(
            block_count=len(by_block),
            tract_count=len(tract_population),
            hex_count=len({h3 for _, h3 in pop_in_cell}),
            total_block_population=total_block_population,
            unassigned_population=unassigned_population,
            uncovered_blocks=tuple(uncovered),
            area_fallback_tracts=tuple(area_fallback),
        ),
    )


def _index(weights: Sequence[TractHexWeight], report: CrosswalkReport) -> Crosswalk:
    by_tract: dict[str, list[TractHexWeight]] = defaultdict(list)
    by_hex: dict[str, list[TractHexWeight]] = defaultdict(list)
    for weight in weights:
        by_tract[weight.tract_geoid].append(weight)
        by_hex[weight.h3].append(weight)
    return Crosswalk(
        weights=tuple(weights),
        report=report,
        _by_tract={k: tuple(v) for k, v in by_tract.items()},
        _by_hex={k: tuple(v) for k, v in by_hex.items()},
    )


def crosswalk_from_weights(weights: Iterable[TractHexWeight]) -> Crosswalk:
    """Rebuild a `Crosswalk` from stored `tract_hex_weight` rows.

    The crosswalk is expensive and is computed once; scoring runs read it back
    out of Postgres. This is that path, and it deliberately recalculates
    nothing, so a stored crosswalk and a freshly built one behave identically
    downstream.
    """
    rows = tuple(weights)
    tracts = {row.tract_geoid for row in rows}
    return _index(
        rows,
        CrosswalkReport(
            block_count=sum(row.block_count for row in rows),
            tract_count=len(tracts),
            hex_count=len({row.h3 for row in rows}),
            total_block_population=round(sum(row.population for row in rows)),
            unassigned_population=0,
        ),
    )


def tract_populations(crosswalk: Crosswalk) -> Mapping[str, float]:
    """Block population per tract, as the crosswalk apportioned it."""
    totals: dict[str, float] = defaultdict(float)
    for weight in crosswalk.weights:
        totals[weight.tract_geoid] += weight.population
    return totals
