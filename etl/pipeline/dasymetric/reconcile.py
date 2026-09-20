"""Does the state still hold as many people after interpolation as before.

Interpolation rearranges population, it does not create or destroy it. Because
`build_crosswalk` normalizes each block's hex shares to sum to 1, and because a
block that reaches no hexagon is removed from both sides of its tract's totals,
the weights for a tract sum to 1 exactly. The statewide total after
interpolation is therefore the statewide total before it, as an algebraic
identity rather than as an empirical hope.

Only two things can separate the two totals, and this module names which:

  * **Tracts the crosswalk never reached.** A tract whose every block fell
    outside the hex grid produces no weights at all, so its estimate lands
    nowhere and the hex total falls short by exactly that tract's value. Pass
    the crosswalk and this is measured and subtracted before the tolerance is
    applied, so a gap in coverage is never allowed to hide inside a rounding
    allowance, nor to be reported as drift.

  * **Floating-point accumulation.** What is left after that. Summing on the
    order of a hundred thousand hex values in float64 accumulates relative
    error near 1e-12, and `math.fsum` throughout the interpolation keeps it
    lower still.

A block stranded inside an otherwise covered tract is neither of these. It
costs spatial detail rather than population: the tract's surviving weights
still sum to 1 and its estimate still lands in full. That loss is real and is
reported, but it is reported by `reconcile_crosswalk` against the ancillary
layer, which is where it happens, and not here.

**The documented tolerance is 1e-6 relative**, one person in a million. It sits
six orders of magnitude above the drift the arithmetic can produce and far
below the resolution of any ACS estimate, which is to say it is loose enough
never to fire on rounding and tight enough that anything which does fire is a
bug worth stopping the run for. Section 7's acceptance is that statewide totals
match within a documented tolerance; this is the documentation and
`reconcile_population` is the check.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pipeline.dasymetric.quantities import HexValue
from pipeline.dasymetric.weights import Crosswalk

#: One person in a million. See the module docstring for why this number.
DEFAULT_RELATIVE_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """The before and after, and what accounts for the gap."""

    tract_total: float
    hex_total: float
    #: The part of the gap that has a known cause. Explained, not excused: it
    #: is subtracted before the tolerance is applied and named in `describe`,
    #: so it can never be mistaken for arithmetic that lost people.
    explained: float
    relative_tolerance: float
    explanation: str = ""
    detail: tuple[str, ...] = field(default=())

    @property
    def raw_difference(self) -> float:
        """Hex total minus tract total, before anything is explained."""
        return self.hex_total - self.tract_total

    @property
    def residual(self) -> float:
        """What is left once the known cause is accounted for."""
        return self.raw_difference + self.explained

    @property
    def relative_residual(self) -> float:
        if self.tract_total == 0:
            return 0.0 if self.residual == 0 else math.inf
        return abs(self.residual) / abs(self.tract_total)

    @property
    def ok(self) -> bool:
        return self.relative_residual <= self.relative_tolerance

    def describe(self) -> str:
        verdict = "within tolerance" if self.ok else "OUT OF TOLERANCE"
        lines = [
            f"population reconciliation: {verdict}",
            f"  tract total {self.tract_total:,.3f}",
            f"  hex total   {self.hex_total:,.3f}",
            f"  difference  {self.raw_difference:,.3f}",
        ]
        if self.explained:
            lines.append(f"  of which {self.explained:,.3f} is {self.explanation}")
        lines.append(
            f"  residual {self.residual:,.6f} "
            f"({self.relative_residual:.2e} relative, tolerance {self.relative_tolerance:.0e})"
        )
        return "\n".join(lines)


class ReconciliationFailed(ValueError):
    """The totals did not match. The run should not load its results."""

    def __init__(self, reconciliation: Reconciliation) -> None:
        super().__init__(reconciliation.describe())
        self.reconciliation = reconciliation


def reconcile_population(
    tract_estimates: Mapping[str, float],
    hex_values: Iterable[HexValue],
    *,
    crosswalk: Crosswalk | None = None,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Reconciliation:
    """Compare an interpolated extensive total against its tract-level source.

    `tract_estimates` is the published value per tract and `hex_values` is what
    came out of `interpolate_extensive`. Passing `crosswalk` lets the check
    distinguish a tract that was never offered to the interpolation, because no
    block of it meets the hex grid, from arithmetic that lost people. Without
    it, both read as a failure, which is the safe default but a less useful
    message.

    This works for any extensive quantity, not only population. Population is
    the one section 7 names because it is the quantity every other apportioned
    count is weighted by, so if it closes, the rest closes with it.
    """
    tract_total = math.fsum(tract_estimates.values())
    hex_total = math.fsum(float(value.value or 0.0) for value in hex_values if value.present)

    unreached: tuple[str, ...] = ()
    unreached_total = 0.0
    if crosswalk is not None:
        reached = set(crosswalk.tracts())
        unreached = tuple(sorted(t for t in tract_estimates if t not in reached))
        unreached_total = math.fsum(tract_estimates[t] for t in unreached)

    return Reconciliation(
        tract_total=tract_total,
        hex_total=hex_total,
        explained=unreached_total,
        relative_tolerance=relative_tolerance,
        explanation=f"the value of {len(unreached)} tracts the crosswalk never reached",
        detail=unreached,
    )


def reconcile_crosswalk(
    crosswalk: Crosswalk,
    *,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> Reconciliation:
    """Check the crosswalk against its own ancillary layer.

    The 2020 block population that went in should be the hex population that
    came out, less whatever `build_crosswalk` reported as sitting in blocks
    that met no hexagon. This runs before any ACS value is interpolated, which
    is where it earns its keep: it separates a broken crosswalk from a broken
    estimate, and only one of those two is worth re-running the geometry for.
    """
    report = crosswalk.report
    stranded = tuple(sorted(b.block_geoid for b in report.uncovered_blocks if b.coverage == 0))
    return Reconciliation(
        tract_total=float(report.total_block_population),
        hex_total=math.fsum(w.population for w in crosswalk.weights),
        explained=float(report.unassigned_population),
        relative_tolerance=relative_tolerance,
        explanation=f"2020 block population in {len(stranded)} blocks meeting no hexagon",
        detail=stranded,
    )


def require(reconciliation: Reconciliation) -> Reconciliation:
    """Raise unless the totals match. For the pipeline gate of CS-108."""
    if not reconciliation.ok:
        raise ReconciliationFailed(reconciliation)
    return reconciliation
