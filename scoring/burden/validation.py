"""Methodology section 13: the pre-registered validation protocol, as a gate.

The claim this project makes is that the score flags known environmental justice
sites **on its own**, without having been tuned to them. Section 13 makes that
claim falsifiable by fixing the sites, their cells and the pass criteria in
`docs/validation/sites.yml` before any scoring code existed, and CI enforces that
ordering by commit ancestry. This module is the other half: it takes a scored run
and the frozen fixture and answers, without discretion, whether the run cleared
the bar.

**It evaluates frozen cells, never a radius.** Each site resolved to an explicit
set of H3 cells once, from its anchor, before a score existed, and those cells
are in the fixture. Re-deriving them at scoring time from a radius would hand
whoever runs the gate a dial: nudge k from 1 to 2 and a site that missed the top
decile acquires eighteen more chances to hit it. The whole point of freezing them
is that the gate cannot be widened after seeing the result.

**Four categories, two of which gate.**

*High burden.* At least one of the site's pre-registered cells in the statewide
top decile. Eight of the ten active Louisiana sites must pass. This is the Phase
2 exit condition.

*Negative controls.* Every scored cell below the statewide median, for all four.
"At least one" would be far too weak here: a control site passes only if the
score declines to flag any part of it, which is what makes it a control.

*Stress case A, not a poverty map.* Three high-poverty low-industry Delta
parishes, expected roughly between the 40th and 75th percentiles. Reported, not
gating; a result outside the band triggers a documented investigation.

*Stress case B, not an emissions map.* Three high-emission low-population
industrial sites, expected below the top decile. Reported, not gating.

**A site with no scored cell is `not_applicable`, and never a pass.** Section 5
leaves cells under 25 people unscored, which is expected to affect the
low-population stress cases in particular. The fixture says this outright, and
it matters because the alternative — quietly dropping such a site from the
denominator — would let the gate be cleared by a run that scored almost nothing.
The primary gate is eight of *ten*, and the ten is the registered count, not the
count that happened to produce numbers.

**Insufficient-confidence cells are excluded before anything is counted.**
Section 12 bars them from validation statistics, and CS-205 enforces that rather
than advising it. A site whose cells are all insufficient therefore comes out
`not_applicable` rather than passing on a number the system says it does not
trust.

**Where the fixture gives a band but not a statistic.** The two gating criteria
name their own statistic: "at least one cell" for high burden, "every scored
cell" for the controls. The two stress cases give an expected percentile band
without saying which of a site's cells it applies to. This module uses the
site's **highest** scored percentile for both, for two reasons: it is the same
statistic the primary gate uses, so the four categories stay comparable, and
both stress cases are about the score over-flagging a place, which is a question
about a site's worst cell rather than its typical one. The median is reported
beside it so an investigation has both. This is an implementation choice on a
criterion the fixture left open, not a reading of a rule it fixed.

**Nothing here adjusts anything.** Section 13.7's failure protocol permits three
responses to a failing gate: fix a defect in the code, fix a defect in the data
handling, or revise the methodology with a rationale that stands independently
of the validation outcome, then re-run every check from the beginning. Loosening
a criterion is not among them, which is why the criteria arrive from the fixture
rather than being written here.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

Outcome = Literal["pass", "fail", "not_applicable"]

HIGH_BURDEN = "high_burden"
NEGATIVE_CONTROL = "negative_control"
STRESS_POVERTY = "stress_not_a_poverty_map"
STRESS_EMISSIONS = "stress_not_an_emissions_map"

GATING_CATEGORIES = (HIGH_BURDEN, NEGATIVE_CONTROL)


@dataclass(frozen=True, slots=True)
class ScoredCell:
    """One hex as the gate needs it: where it ranked and whether it is usable.

    `band` is section 12's confidence band. It is required rather than optional
    because a validation result computed from a run whose confidence was never
    calculated cannot honour section 12's exclusion, and quietly including those
    cells would be the failure the exclusion exists to prevent.
    """

    percentile: float
    band: str


@dataclass(frozen=True, slots=True)
class Site:
    """One registered site, exactly as the fixture froze it."""

    id: str
    name: str
    category: str
    state: str
    active: bool
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Criteria:
    """The thresholds, read from the fixture rather than written here.

    Section 13.7 does not permit loosening a criterion in response to a result,
    and a default living in the code is a criterion one edit away from being
    loosened without the fixture changing.
    """

    high_burden_percentile: float
    high_burden_required: int
    high_burden_of: int
    negative_control_percentile: float
    negative_control_required: int
    negative_control_of: int
    poverty_band: tuple[float, float]
    emissions_below_percentile: float


@dataclass(frozen=True, slots=True)
class SiteResult:
    """What the gate found for one site, and enough to explain a miss."""

    site_id: str
    name: str
    category: str
    outcome: Outcome
    gating: bool
    cells_registered: int
    cells_scored: int
    cells_unscored: int
    cells_excluded_low_confidence: int
    best_percentile: float | None
    median_percentile: float | None
    worst_percentile: float | None
    detail: str


@dataclass(frozen=True, slots=True)
class CategoryResult:
    category: str
    gating: bool
    passed: int
    required: int
    of: int
    results: tuple[SiteResult, ...] = field(default_factory=tuple)

    @property
    def met(self) -> bool:
        """Whether this category cleared its bar. Always true for a reported one."""
        return not self.gating or self.passed >= self.required


@dataclass(frozen=True, slots=True)
class GateResult:
    """The whole protocol's answer for one run."""

    categories: tuple[CategoryResult, ...]
    methodology_version: str

    @property
    def sites(self) -> tuple[SiteResult, ...]:
        return tuple(result for category in self.categories for result in category.results)

    @property
    def passed(self) -> bool:
        """The Phase 2 exit condition: every gating category met its bar."""
        return all(category.met for category in self.categories)

    def category(self, name: str) -> CategoryResult:
        for entry in self.categories:
            if entry.category == name:
                return entry
        raise KeyError(f"{name} is not a category of this run")

    def misses(self) -> tuple[SiteResult, ...]:
        """Sites that did not pass, gating or not, for the write-up."""
        return tuple(result for result in self.sites if result.outcome != "pass")


def evaluate(
    sites: Iterable[Site],
    cells: Mapping[str, ScoredCell],
    *,
    criteria: Criteria,
    methodology_version: str,
) -> GateResult:
    """Run the section 13 protocol over one scored run.

    `cells` maps H3 index to the scored cell. A registered cell absent from it
    was not scored, which the fixture expects for low-population sites and which
    is reported rather than treated as a miss of its own.
    """
    by_category: dict[str, list[SiteResult]] = {
        HIGH_BURDEN: [],
        NEGATIVE_CONTROL: [],
        STRESS_POVERTY: [],
        STRESS_EMISSIONS: [],
    }

    for site in sites:
        if site.category not in by_category:
            raise ValueError(f"site {site.id} has a category the protocol does not define")
        # Section 13 gates on the active set. An out-of-state site is registered
        # now precisely so that it cannot be chosen later once a score exists.
        if not site.active:
            continue
        by_category[site.category].append(_evaluate_site(site, cells, criteria))

    categories = (
        CategoryResult(
            category=HIGH_BURDEN,
            gating=True,
            passed=_count_passes(by_category[HIGH_BURDEN]),
            required=criteria.high_burden_required,
            of=criteria.high_burden_of,
            results=tuple(by_category[HIGH_BURDEN]),
        ),
        CategoryResult(
            category=NEGATIVE_CONTROL,
            gating=True,
            passed=_count_passes(by_category[NEGATIVE_CONTROL]),
            required=criteria.negative_control_required,
            of=criteria.negative_control_of,
            results=tuple(by_category[NEGATIVE_CONTROL]),
        ),
        CategoryResult(
            category=STRESS_POVERTY,
            gating=False,
            passed=_count_passes(by_category[STRESS_POVERTY]),
            required=0,
            of=len(by_category[STRESS_POVERTY]),
            results=tuple(by_category[STRESS_POVERTY]),
        ),
        CategoryResult(
            category=STRESS_EMISSIONS,
            gating=False,
            passed=_count_passes(by_category[STRESS_EMISSIONS]),
            required=0,
            of=len(by_category[STRESS_EMISSIONS]),
            results=tuple(by_category[STRESS_EMISSIONS]),
        ),
    )

    return GateResult(categories=categories, methodology_version=methodology_version)


def _evaluate_site(site: Site, cells: Mapping[str, ScoredCell], criteria: Criteria) -> SiteResult:
    usable: list[float] = []
    unscored = 0
    insufficient = 0

    for h3 in site.cells:
        cell = cells.get(h3)
        if cell is None:
            unscored += 1
            continue
        # Section 12 keeps an untrusted hex out of validation statistics. This
        # is the enforcement point, not a suggestion the caller may skip.
        if cell.band == "insufficient":
            insufficient += 1
            continue
        usable.append(cell.percentile)

    gating = site.category in GATING_CATEGORIES
    base = dict(
        site_id=site.id,
        name=site.name,
        category=site.category,
        gating=gating,
        cells_registered=len(site.cells),
        cells_scored=len(usable),
        cells_unscored=unscored,
        cells_excluded_low_confidence=insufficient,
    )

    if not usable:
        return SiteResult(
            **base,  # type: ignore[arg-type]
            outcome="not_applicable",
            best_percentile=None,
            median_percentile=None,
            worst_percentile=None,
            detail=_no_cells_detail(len(site.cells), unscored, insufficient),
        )

    best = max(usable)
    worst = min(usable)
    middle = float(median(usable))
    outcome, detail = _judge(site.category, usable, criteria)

    return SiteResult(
        **base,  # type: ignore[arg-type]
        outcome=outcome,
        best_percentile=best,
        median_percentile=middle,
        worst_percentile=worst,
        detail=detail,
    )


def _judge(category: str, usable: Sequence[float], criteria: Criteria) -> tuple[Outcome, str]:
    best = max(usable)
    worst = min(usable)

    if category == HIGH_BURDEN:
        if best >= criteria.high_burden_percentile:
            return "pass", (
                f"best cell at the {best:.1f}th percentile, "
                f"at or above the {criteria.high_burden_percentile:.0f}th"
            )
        return "fail", (
            f"best cell only reached the {best:.1f}th percentile, short of the "
            f"{criteria.high_burden_percentile:.0f}th; the site scored but did not "
            f"rank"
        )

    if category == NEGATIVE_CONTROL:
        if best < criteria.negative_control_percentile:
            return "pass", (
                f"every scored cell below the {criteria.negative_control_percentile:.0f}th, "
                f"the highest at {best:.1f}"
            )
        above = sum(1 for value in usable if value >= criteria.negative_control_percentile)
        return "fail", (
            f"{above} of {len(usable)} scored cells reached the "
            f"{criteria.negative_control_percentile:.0f}th percentile or above, "
            f"the highest at {best:.1f}; a control passes only if the score "
            f"declines to flag any part of it"
        )

    if category == STRESS_POVERTY:
        low, high = criteria.poverty_band
        if low <= best <= high:
            return "pass", f"highest cell at {best:.1f}, inside the expected {low:.0f}–{high:.0f}"
        direction = "above" if best > high else "below"
        return "fail", (
            f"highest cell at {best:.1f}, {direction} the expected "
            f"{low:.0f}–{high:.0f}; reported, not gating, and section 13 asks for a "
            f"documented investigation rather than an adjustment"
        )

    low, high = worst, best
    if high < criteria.emissions_below_percentile:
        return "pass", (
            f"highest cell at {high:.1f}, below the "
            f"{criteria.emissions_below_percentile:.0f}th as expected"
        )
    return "fail", (
        f"highest cell at {high:.1f}, at or above the "
        f"{criteria.emissions_below_percentile:.0f}th; reported, not gating, and "
        f"section 13 asks for a documented investigation rather than an adjustment"
    )


def _no_cells_detail(registered: int, unscored: int, insufficient: int) -> str:
    parts = []
    if unscored:
        parts.append(f"{unscored} of {registered} cells carry no score")
    if insufficient:
        parts.append(f"{insufficient} were excluded as insufficient confidence")
    reason = "; ".join(parts) if parts else "no cells resolved"
    return f"not applicable: {reason}. Never counted as a pass."


def _count_passes(results: Sequence[SiteResult]) -> int:
    return sum(1 for result in results if result.outcome == "pass")


CATEGORY_TITLES: dict[str, str] = {
    HIGH_BURDEN: "Primary gate: high-burden sites",
    NEGATIVE_CONTROL: "Negative controls",
    STRESS_POVERTY: "Stress case A: not a poverty map",
    STRESS_EMISSIONS: "Stress case B: not an emissions map",
}


def report(gate: GateResult, *, scores_from: str) -> str:
    """The write-up section 13 asks for: what passed, what did not, and why.

    `scores_from` names where the scores came from and is printed at the top.
    A validation report whose provenance is not on its face invites being read
    as a result of the run someone happens to be looking at, and section 13.7
    turns on being able to say which run a verdict describes.
    """
    lines: list[str] = [
        "# ClearSkies validation run",
        "",
        f"- Methodology version: {gate.methodology_version}",
        f"- Scores from: {scores_from}",
        f"- Outcome: **{'PASS' if gate.passed else 'FAIL'}**",
        "",
    ]

    for category in gate.categories:
        lines.append(f"## {CATEGORY_TITLES[category.category]}")
        lines.append("")
        if category.gating:
            verdict = "met" if category.met else "NOT met"
            lines.append(
                f"Gating. {category.passed} of {category.of} passed, "
                f"{category.required} required: {verdict}."
            )
        else:
            lines.append(
                f"Reported, not gating. {category.passed} of {category.of} inside "
                f"the expected range."
            )
        lines.append("")
        lines.append("| Site | Outcome | Cells scored | Best | Median | Notes |")
        lines.append("|---|---|---|---|---|---|")
        for result in category.results:
            lines.append(
                f"| {result.site_id} {result.name} "
                f"| {result.outcome} "
                f"| {result.cells_scored} of {result.cells_registered} "
                f"| {_pct(result.best_percentile)} "
                f"| {_pct(result.median_percentile)} "
                f"| {result.detail} |"
            )
        lines.append("")

    misses = gate.misses()
    if misses:
        lines.append("## Sites that did not pass")
        lines.append("")
        for result in misses:
            lines.append(
                f"- **{result.site_id} {result.name}** ({result.category}): {result.detail}"
            )
        lines.append("")

    lines.append("## If this run failed")
    lines.append("")
    lines.append(
        "Section 13.7 permits three responses: fix a defect in the code, fix a "
        "defect in the data handling, or revise the methodology with a rationale "
        "that stands independently of this outcome, then re-run every check from "
        "the beginning. Adjusting a weight because it makes a site pass is not "
        "one of them, and the validation set itself is never edited."
    )
    lines.append("")

    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"
