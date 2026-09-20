"""Methodology section 7: source geography onto the hexagon grid.

Three of the five sources publish at census tract level. Moving a tract value to
a hexagon is the most consequential transformation in the pipeline and section 7
is emphatic that there are two different transformations, not one:

*Extensive* quantities are counts and sum across space — population, households,
number of people in poverty. They are apportioned through the population share
of the overlap.

    V(h) = Σ_t V(t) · [ P(t ∩ h) / P(t) ]

*Intensive* quantities are rates, ratios and modeled risks and do not sum —
poverty rate, AirToxScreen cancer risk, percent without a high school diploma.
They are combined as a population-weighted mean of the source values overlapping
the hex.

    R(h) = [ Σ_t R(t) · P(t ∩ h) ] / [ Σ_t P(t ∩ h) ]

Both live here, next to each other, because section 7 calls confusing them the
most common source of error in this step and a reader choosing between two
functions in one file is far likelier to notice the choice than a reader
importing whichever one their adapter already had. Neither function area-weights
anything, and neither reconstructs a rate from separately interpolated parts:
where a rate has a published numerator and denominator, both are apportioned
with `apportion` and the division happens once, at the end, in the caller.

**Absence is a result, not a gap in the output.** Every hex in the universe the
caller supplies comes back with a `HexValue`, and a hex that could not be given a
number carries a reason why rather than being missing from the list or quietly
set to zero. Section 11 is the reason: imputing an absent modeled risk to zero or
to the median pulls exactly the unmonitored high-burden areas this project exists
to find back toward the middle.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pipeline.records import Measurement

# Why a hex ended up with no value. Each is counted separately because they mean
# different things: the first is a hole in the grid's own crosswalk, the second
# is upstream not covering the tract, and the third is a hex where the
# population-weighted mean is undefined rather than unknown.
AbsenceReason = Literal["no_overlapping_source", "no_source_value", "no_population"]


@dataclass(frozen=True, slots=True)
class Overlap:
    """One source-unit and hex overlap: a row of `tract_hex_weight`.

    `population` is P(t ∩ h), the block-apportioned population of the overlap,
    and is the weight for intensive quantities. `pop_weight` is that population
    as a share of the whole source unit's, P(t ∩ h) / P(t), and is the weight for
    extensive ones. Storing both is what lets either formula be one pass over
    this list.
    """

    source_id: str
    h3: str
    population: float
    pop_weight: float


@runtime_checkable
class Crosswalk(Protocol):
    """The stored result of section 7 steps 1 and 2.

    Built by CS-007 from 2020 Decennial block populations and read here. It is a
    protocol rather than a query so that nothing in `pipeline.adapters` has to
    depend on PostGIS, which is the same reason `Sink` is one.
    """

    def hexes(self) -> Sequence[str]:
        """Every hex the caller expects an answer for, in the pilot state."""
        ...

    def overlaps(self) -> Sequence[Overlap]:
        """Every source-unit and hex overlap."""
        ...


@dataclass(frozen=True, slots=True)
class HexValue:
    """One hex's answer. Either a value, or a reason there is not one."""

    h3: str
    value: Measurement
    source_count: int
    population: float
    absence: AbsenceReason | None = None


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the mapping did and did not manage to cover.

    Produced alongside the values so the count reaches the run manifest. A count
    discovered later, per record, could never be published, and section 6
    requires the absence count to be published rather than inferred from a
    shorter map.
    """

    hexes: int
    observed: int
    absences: Mapping[AbsenceReason, int]
    unmatched_sources: tuple[str, ...]

    @property
    def absent(self) -> int:
        return sum(self.absences.values())

    def summary(self) -> str:
        breakdown = ", ".join(
            f"{reason} {count}" for reason, count in sorted(self.absences.items())
        )
        return (
            f"{self.observed} of {self.hexes} hexes received a value; "
            f"{self.absent} absent ({breakdown or 'none'})"
        )


def _group(overlaps: Iterable[Overlap]) -> dict[str, list[Overlap]]:
    grouped: dict[str, list[Overlap]] = {}
    for overlap in overlaps:
        grouped.setdefault(overlap.h3, []).append(overlap)
    return grouped


def _unmatched(values: Mapping[str, Measurement], overlaps: Iterable[Overlap]) -> tuple[str, ...]:
    """Source units that carry a value but appear nowhere in the crosswalk.

    Non-empty means the crosswalk and the source disagree about what geography
    exists — most often because they are on different census vintages — and the
    values concerned reach no hexagon at all. Silently dropping them is the
    failure this return value exists to prevent.
    """
    known = {overlap.source_id for overlap in overlaps}
    return tuple(sorted(source_id for source_id in values if source_id not in known))


def _finish(
    hexes: Sequence[str], results: Mapping[str, HexValue], unmatched: tuple[str, ...]
) -> tuple[tuple[HexValue, ...], Coverage]:
    absences: dict[AbsenceReason, int] = {}
    observed = 0
    for h3 in hexes:
        entry = results[h3]
        if entry.absence is None:
            observed += 1
        else:
            absences[entry.absence] = absences.get(entry.absence, 0) + 1
    values = tuple(results[h3] for h3 in hexes)
    coverage = Coverage(
        hexes=len(hexes),
        observed=observed,
        absences=absences,
        unmatched_sources=unmatched,
    )
    return values, coverage


def population_weighted_mean(
    values: Mapping[str, Measurement], crosswalk: Crosswalk
) -> tuple[tuple[HexValue, ...], Coverage]:
    """Intensive quantities: rates, ratios and modeled risks.

        R(h) = [ Σ_t R(t) · P(t ∩ h) ] / [ Σ_t P(t ∩ h) ]

    A source unit that reported nothing is left out of the numerator **and the
    denominator**. Leaving it in the denominator would be imputing its value to
    zero by arithmetic rather than by assignment, which section 11 forbids in
    exactly the direction that matters: it would drag a hex whose only measured
    neighbour is heavily burdened back toward the middle.

    Area is not used anywhere in this function, and that is the point. Section 7
    opens by rejecting area share precisely because it would hand an unpopulated
    third of a rural tract the same weight as its town.
    """
    grouped = _group(crosswalk.overlaps())
    results: dict[str, HexValue] = {}

    for h3 in crosswalk.hexes():
        overlaps = grouped.get(h3, ())
        if not overlaps:
            results[h3] = HexValue(h3, Measurement.absent(), 0, 0.0, "no_overlapping_source")
            continue

        weighted = 0.0
        weight = 0.0
        contributing = 0
        for overlap in overlaps:
            measurement = values.get(overlap.source_id)
            if measurement is None or not measurement.observed or measurement.value is None:
                continue
            contributing += 1
            weighted += measurement.value * overlap.population
            weight += overlap.population

        if contributing == 0:
            results[h3] = HexValue(h3, Measurement.absent(), 0, 0.0, "no_source_value")
        elif weight <= 0.0:
            # Every contributing source unit had zero population in this hex, so
            # the mean is undefined rather than unknown. Falling back to an
            # unweighted or area-weighted mean here would be the area-averaging
            # section 7 rules out, so the hex is absent and the count is
            # published. These are unpopulated cells, which section 11 leaves
            # unscored anyway.
            results[h3] = HexValue(h3, Measurement.absent(), contributing, 0.0, "no_population")
        else:
            results[h3] = HexValue(h3, Measurement.of(weighted / weight), contributing, weight)

    return _finish(list(crosswalk.hexes()), results, _unmatched(values, crosswalk.overlaps()))


def apportion(
    values: Mapping[str, Measurement], crosswalk: Crosswalk
) -> tuple[tuple[HexValue, ...], Coverage]:
    """Extensive quantities: counts that sum across space.

        V(h) = Σ_t V(t) · [ P(t ∩ h) / P(t) ]

    Used by the ACS adapter (CS-105), which stores every published numerator and
    denominator as its own extensive quantity and derives each rate once at the
    end. It is here rather than there so that the two halves of section 7 are
    read together; using this one on a rate, or `population_weighted_mean` on a
    count, is the error section 7 warns about.
    """
    grouped = _group(crosswalk.overlaps())
    results: dict[str, HexValue] = {}

    for h3 in crosswalk.hexes():
        overlaps = grouped.get(h3, ())
        if not overlaps:
            results[h3] = HexValue(h3, Measurement.absent(), 0, 0.0, "no_overlapping_source")
            continue

        total = 0.0
        population = 0.0
        contributing = 0
        for overlap in overlaps:
            measurement = values.get(overlap.source_id)
            if measurement is None or not measurement.observed or measurement.value is None:
                continue
            contributing += 1
            total += measurement.value * overlap.pop_weight
            population += overlap.population

        if contributing == 0:
            results[h3] = HexValue(h3, Measurement.absent(), 0, 0.0, "no_source_value")
        else:
            # A count of zero is an observation, so unlike the intensive case a
            # zero-population overlap is not an absence: no people in the hex
            # means no people apportioned to it, which is a fact.
            results[h3] = HexValue(h3, Measurement.of(total), contributing, population)

    return _finish(list(crosswalk.hexes()), results, _unmatched(values, crosswalk.overlaps()))


@dataclass(frozen=True, slots=True)
class StaticCrosswalk:
    """A crosswalk held in memory. Used by the tests and by `--dry-run`."""

    cells: tuple[str, ...]
    rows: tuple[Overlap, ...]

    def hexes(self) -> Sequence[str]:
        return self.cells

    def overlaps(self) -> Sequence[Overlap]:
        return self.rows
