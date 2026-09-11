"""CS-213: how the burden score tracks racial composition, and why that means anything.

Methodology section 13.6. This is the project's headline finding, and two things
about it need care in roughly equal measure: computing it correctly, and framing
it correctly.

**It is a reported result, not a validation target.** Nothing in this module
returns a verdict, and nothing that calls it may gate on the number. There is no
threshold the correlation must clear. A weaker-than-expected result is a finding
worth publishing, and the moment it becomes something the build can fail on,
somebody eventually tunes a weight until it passes and the finding is worth
nothing. The quality gate of CS-108 is the opposite shape on purpose: it exists
to fail. This exists to report.

**The independence argument travels with the number.** `DisparityReport` carries
`framing` and `independence` as required fields, so no consumer can serialise the
coefficient without also receiving the sentences that keep it from being read as
circular. That is a boundary of the same kind migration 0013 draws when it puts
race in its own table: a rule a reviewer can see beats a convention everyone is
asked to remember. The API, the architecture write-up and the public site all
read these fields rather than restating the argument in their own words, so there
is one place to correct if it is ever wrong.

**Why the argument holds.** Race is not an input to the score anywhere: not as an
indicator, not as a weight, not as a tiebreak. Section 14 makes the case, and the
schema enforces it, with `tract_race_ethnicity` held apart from the table every
indicator reads and the three `hex_demographics` share columns commented as
displayed and never scored. So a correlation found here is a property of the
pollution and vulnerability data, not an artifact of the construction.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, field_validator

from pipeline.analysis import statistics as st
from pipeline.metadata import Frozen, UtcDatetime

#: Stated wherever the number is shown. Section 13.6 asks for this in so many
#: words, and the report model makes it impossible to omit.
FRAMING = (
    "This is a reported result, not a validation target. There is no threshold it "
    "must meet. A weaker correlation than expected is a finding worth publishing, "
    "not a defect to fix, and no weight in the score may be adjusted on the "
    "strength of what is reported here."
)

INDEPENDENCE = (
    "Race and ethnicity are not inputs to the burden score. The score is built "
    "from emissions, modelled risk, facility proximity, compliance records, age "
    "structure and economic hardship; racial composition enters neither an "
    "indicator, nor a weight, nor a tiebreak, and the schema keeps it in a "
    "separate table that no scoring query reads. Any correlation reported here is "
    "therefore a property of the pollution and vulnerability data rather than an "
    "artifact of how the score was constructed. That is what makes it evidence: "
    "had race been an ingredient, the correlation would be guaranteed by "
    "construction and would prove nothing. See methodology sections 13.6 and 14."
)

#: The share of the statewide scored population held by the hexes the contrast
#: calls "most burdened". A decile because section 13.2 already judges validation
#: sites against the top decile, and two different definitions of "worst" in one
#: document is one too many.
TOP_DECILE = 90.0


class Measure(StrEnum):
    """The two population shares section 13.6 asks about."""

    BLACK = "black_share"
    PEOPLE_OF_COLOUR = "people_of_colour_share"


#: Where each measure comes from. The column spellings are the schema's, which is
#: American; the prose spelling is the methodology's, which is not.
MEASURE_COLUMN: Mapping[Measure, str] = {
    Measure.BLACK: "black_pct",
    Measure.PEOPLE_OF_COLOUR: "people_of_color_pct",
}

MEASURE_LABEL: Mapping[Measure, str] = {
    Measure.BLACK: "Black population share",
    Measure.PEOPLE_OF_COLOUR: "people-of-colour share",
}

Method = Literal["pearson", "spearman"]

#: Both are reported rather than one being chosen. The score percentile is
#: already a rank, so Pearson against it is a rank-against-value association and
#: is the more legible of the two; the shares are heavily right-skewed, so
#: Spearman is the more robust. Where they agree the finding does not rest on the
#: choice, and where they diverge that divergence is itself worth seeing.
METHODS: tuple[Method, ...] = ("pearson", "spearman")


@dataclass(frozen=True)
class HexRow:
    """One scored hex, as the analysis needs it.

    A plain dataclass rather than a `NormalizedRecord` because nothing here is
    being loaded anywhere: this is a read over rows two other tickets wrote.
    """

    h3: str
    percentile: float
    population: float
    black_pct: float | None
    people_of_color_pct: float | None
    confidence_band: str | None
    cluster: str

    def share(self, measure: Measure) -> float | None:
        if measure is Measure.BLACK:
            return self.black_pct
        return self.people_of_color_pct


class CohortSummary(Frozen):
    """Who the statistic was computed over, and who it left out."""

    name: str
    description: str
    n_hexes: int
    population: float
    n_clusters: int = Field(description="Parishes present, the unit the bootstrap resamples")
    n_effective: float | None = Field(
        default=None,
        description="Kish effective sample size: how many independent observations the "
        "weighted sample is worth, which is far fewer than the hex count",
    )
    excluded: tuple[str, ...] = Field(
        default=(), description="One line per reason a scored hex was left out, with counts"
    )


class Interval(Frozen):
    low: float
    high: float
    method: str = Field(description="How the interval was obtained, e.g. parish cluster bootstrap")
    level: float = st.DEFAULT_LEVEL


class CorrelationResult(Frozen):
    """One coefficient, with the interval that should be quoted beside it."""

    cohort: str
    measure: Measure
    method: Method
    coefficient: float
    interval: Interval
    comparison: Interval | None = Field(
        default=None,
        description="The independence-assuming Fisher interval, published only to show "
        "how much narrower it is than the truth",
    )
    n_hexes: int
    population: float

    def line(self) -> str:
        return (
            f"{MEASURE_LABEL[self.measure]}, {self.method}: {self.coefficient:+.3f} "
            f"({self.interval.level:.0%} CI {self.interval.low:+.3f} to {self.interval.high:+.3f})"
        )


class ContrastResult(Frozen):
    """The same finding as a number a reader without statistics can hold.

    A correlation coefficient is the right summary and the wrong sentence. This
    is the population-weighted share in the worst-scoring decile against the rest
    of the state, which is what the public site and the architecture write-up
    will actually lead with, carrying the same parish bootstrap interval.
    """

    cohort: str
    measure: Measure
    top_decile_share: float
    elsewhere_share: float
    difference: float
    difference_interval: Interval
    ratio: float
    ratio_interval: Interval
    top_decile_population: float
    elsewhere_population: float

    def line(self) -> str:
        return (
            f"{MEASURE_LABEL[self.measure]} is {self.top_decile_share:.1f}% in the "
            f"top-decile hexes against {self.elsewhere_share:.1f}% elsewhere, a ratio of "
            f"{self.ratio:.2f} ({self.ratio_interval.level:.0%} CI "
            f"{self.ratio_interval.low:.2f} to {self.ratio_interval.high:.2f})"
        )


class DisparityReport(Frozen):
    """Everything one disparity run produced, framing included.

    `framing` and `independence` are required and defaulted to the constants
    above rather than being left to the caller. A report that serialises the
    coefficient without them cannot be constructed, which is how section 13.6's
    "stated wherever the number is shown" is enforced rather than remembered.
    """

    run_id: int | None
    analysed_at: UtcDatetime
    methodology_version: str
    acs_vintage: str | None = None
    status: Literal["computed", "not_computable"]
    reason: str | None = Field(
        default=None, description="Why nothing was computed. Set exactly when status says so"
    )
    cohorts: tuple[CohortSummary, ...] = ()
    correlations: tuple[CorrelationResult, ...] = ()
    contrasts: tuple[ContrastResult, ...] = ()
    notes: tuple[str, ...] = ()
    framing: str = FRAMING
    independence: str = INDEPENDENCE

    @field_validator("framing", "independence")
    @classmethod
    def _must_say_something(cls, value: str) -> str:
        """An empty argument is the same as no argument.

        Defaults alone would leave "state the independence argument wherever the
        number is shown" as a convention a caller could opt out of by passing an
        empty string. This makes it a rule the constructor enforces.
        """
        if not value.strip():
            raise ValueError(
                "framing and independence travel with the coefficient; section 13.6 "
                "requires the argument wherever the number is shown"
            )
        return value

    @property
    def primary_cohort(self) -> str | None:
        return self.cohorts[0].name if self.cohorts else None

    def headline(self) -> CorrelationResult | None:
        """Black share against score percentile, Pearson, on the primary cohort."""
        primary = self.primary_cohort
        for result in self.correlations:
            if (
                result.cohort == primary
                and result.measure is Measure.BLACK
                and result.method == "pearson"
            ):
                return result
        return None

    def summary(self) -> str:
        if self.status == "not_computable":
            return f"disparity analysis not computable: {self.reason}"
        headline = self.headline()
        if headline is None:
            return "disparity analysis computed, no headline coefficient available"
        return f"disparity analysis: {headline.line()}"

    def markdown(self) -> str:
        """The report as a page, framing first and numbers second.

        Deliberately in that order. A reader who stops after the first screen
        should have read the independence argument, not the coefficient.
        """
        stamp = self.analysed_at.strftime("%Y-%m-%d %H:%M")
        lines = [
            "# Disparity analysis",
            "",
            f"Run `{self.run_id if self.run_id is not None else 'none'}` analysed at "
            f"{stamp} UTC against methodology {self.methodology_version}"
            + (f", ACS {self.acs_vintage}" if self.acs_vintage else "")
            + ".",
            "",
            "## How to read this",
            "",
            self.framing,
            "",
            self.independence,
        ]

        if self.status == "not_computable":
            lines += [
                "",
                "## Not computed",
                "",
                f"{self.reason}",
            ]
            for note in self.notes:
                lines += ["", f"> {note}"]
            return "\n".join(lines) + "\n"

        lines += ["", "## Correlations", ""]
        lines += [
            "| Cohort | Measure | Method | Coefficient | 95% CI | "
            "Fisher CI (independence assumed) |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.correlations:
            comparison = (
                f"{r.comparison.low:+.3f} to {r.comparison.high:+.3f}"
                if r.comparison is not None
                else "-"
            )
            lines.append(
                f"| {r.cohort} | {MEASURE_LABEL[r.measure]} | {r.method} | "
                f"{r.coefficient:+.3f} | {r.interval.low:+.3f} to {r.interval.high:+.3f} | "
                f"{comparison} |"
            )

        if self.contrasts:
            lines += ["", "## Top decile against the rest of the state", ""]
            lines += [
                "| Cohort | Measure | Top decile | Elsewhere | Difference | Ratio | "
                "95% CI on ratio |",
                "|---|---|---|---|---|---|---|",
            ]
            for c in self.contrasts:
                lines.append(
                    f"| {c.cohort} | {MEASURE_LABEL[c.measure]} | {c.top_decile_share:.1f}% | "
                    f"{c.elsewhere_share:.1f}% | {c.difference:+.1f} pp | {c.ratio:.2f} | "
                    f"{c.ratio_interval.low:.2f} to {c.ratio_interval.high:.2f} |"
                )

        lines += ["", "## Cohorts", ""]
        lines += [
            "| Cohort | Hexes | Population | Parishes | Effective n | What it is |",
            "|---|---|---|---|---|---|",
        ]
        for cohort in self.cohorts:
            effective = "-" if cohort.n_effective is None else f"{cohort.n_effective:.0f}"
            lines.append(
                f"| {cohort.name} | {cohort.n_hexes} | {cohort.population:.0f} | "
                f"{cohort.n_clusters} | {effective} | {cohort.description} |"
            )
        for cohort in self.cohorts:
            if cohort.excluded:
                lines += ["", f"Excluded from `{cohort.name}`:", ""]
                lines += [f"- {line}" for line in cohort.excluded]

        for note in self.notes:
            lines += ["", f"> {note}"]
        return "\n".join(lines) + "\n"


# --- assembling cohorts -------------------------------------------------------


@dataclass(frozen=True)
class Cohort:
    name: str
    description: str
    rows: tuple[HexRow, ...]
    excluded: tuple[str, ...]


def build_cohorts(rows: Sequence[HexRow]) -> tuple[Cohort, ...]:
    """Split the scored hexes into the cohort that is reported and its sensitivity.

    `confident` is the headline. Section 12 bars hexes in the insufficient
    confidence band from validation statistics, and the disparity analysis sits
    in section 13 with the rest of them; a number the project leads with should
    not rest partly on scores the project says it does not trust.

    `all_scored` is computed anyway and published beside it, because an exclusion
    rule that is never shown to move the answer is indistinguishable from an
    exclusion rule chosen because it moved the answer. If the two cohorts
    disagree materially, that disagreement is the finding.
    """
    confident: list[HexRow] = []
    insufficient = 0
    for row in rows:
        if row.confidence_band == "insufficient":
            insufficient += 1
            continue
        confident.append(row)

    excluded: tuple[str, ...] = ()
    if insufficient:
        excluded = (f"{insufficient} hexes in the insufficient confidence band, per section 12",)
    return (
        Cohort(
            name="confident",
            description="Scored hexes outside the insufficient confidence band. Reported.",
            rows=tuple(confident),
            excluded=excluded,
        ),
        Cohort(
            name="all_scored",
            description="Every scored hex, including low-confidence ones. Sensitivity check.",
            rows=tuple(rows),
            excluded=(),
        ),
    )


def _clusters_for(
    rows: Sequence[HexRow], measure: Measure, method: Method
) -> tuple[list[st.Moments], st.Moments]:
    """Per-parish moments for one measure, plus their total.

    Ranking for Spearman happens once over the whole cohort and the ranks are
    then treated as the data. Re-ranking inside every bootstrap resample would be
    the purist's version; it is also a hundred and eighty thousand rows sorted
    two thousand times, and the difference it makes to an interval endpoint at
    this sample size is far below the precision the finding is reported to.
    """
    usable = [row for row in rows if row.share(measure) is not None and row.population > 0]
    if not usable:
        return [], st.Moments()

    percentiles = [row.percentile for row in usable]
    shares = [_share(row, measure) for row in usable]
    weights = [row.population for row in usable]

    if method == "spearman":
        percentiles = st.weighted_ranks(percentiles, weights)
        shares = st.weighted_ranks(shares, weights)

    centre_x = st.weighted_mean(percentiles, weights)
    centre_y = st.weighted_mean(shares, weights)

    grouped: dict[str, list[int]] = {}
    for index, row in enumerate(usable):
        grouped.setdefault(row.cluster, []).append(index)

    clusters = [
        st.moments_about(
            [percentiles[i] for i in members],
            [shares[i] for i in members],
            [weights[i] for i in members],
            centre_x=centre_x,
            centre_y=centre_y,
        )
        for members in grouped.values()
    ]
    return clusters, st.combine(clusters)


def _share(row: HexRow, measure: Measure) -> float:
    value = row.share(measure)
    if value is None:  # pragma: no cover - callers filter first
        raise st.NotComputable("hex has no share for this measure")
    return value


def correlations_for(
    cohort: Cohort,
    *,
    resamples: int = st.DEFAULT_RESAMPLES,
    seed: int = st.DEFAULT_SEED,
    level: float = st.DEFAULT_LEVEL,
) -> tuple[list[CorrelationResult], list[str]]:
    """Every measure against every method for one cohort, with what could not be done."""
    results: list[CorrelationResult] = []
    notes: list[str] = []
    for measure in Measure:
        for method in METHODS:
            clusters, total = _clusters_for(cohort.rows, measure, method)
            try:
                coefficient = st.correlation(total)
            except st.NotComputable as exc:
                notes.append(
                    f"{cohort.name} / {MEASURE_LABEL[measure]} / {method}: not computed, {exc}"
                )
                continue
            try:
                low, high = st.bootstrap_interval(
                    clusters, level=level, resamples=resamples, seed=seed
                )
                interval = Interval(
                    low=low,
                    high=high,
                    method=f"parish cluster bootstrap, {resamples} resamples",
                    level=level,
                )
            except st.NotComputable as exc:
                notes.append(
                    f"{cohort.name} / {MEASURE_LABEL[measure]} / {method}: no bootstrap "
                    f"interval, {exc}"
                )
                continue
            comparison: Interval | None = None
            try:
                n_effective = st.effective_sample_size(total)
                f_low, f_high = st.fisher_interval(coefficient, n_effective, level=level)
                comparison = Interval(
                    low=f_low, high=f_high, method="Fisher z on Kish effective n", level=level
                )
            except st.NotComputable:
                # The comparison interval is a courtesy, not the result. Its
                # absence is not worth a note beside the number it compares to.
                comparison = None
            results.append(
                CorrelationResult(
                    cohort=cohort.name,
                    measure=measure,
                    method=method,
                    coefficient=coefficient,
                    interval=interval,
                    comparison=comparison,
                    n_hexes=total.n,
                    population=total.w,
                )
            )
    return results, notes


def contrasts_for(
    cohort: Cohort,
    *,
    threshold: float = TOP_DECILE,
    resamples: int = st.DEFAULT_RESAMPLES,
    seed: int = st.DEFAULT_SEED,
    level: float = st.DEFAULT_LEVEL,
) -> tuple[list[ContrastResult], list[str]]:
    results: list[ContrastResult] = []
    notes: list[str] = []
    for measure in Measure:
        usable = [
            row for row in cohort.rows if row.share(measure) is not None and row.population > 0
        ]
        if not usable:
            notes.append(f"{cohort.name} / {MEASURE_LABEL[measure]}: no hexes carry this share")
            continue
        shares = [_share(row, measure) for row in usable]
        weights = [row.population for row in usable]
        inside = [row.percentile >= threshold for row in usable]

        grouped: dict[str, list[int]] = {}
        for index, row in enumerate(usable):
            grouped.setdefault(row.cluster, []).append(index)
        clusters = [
            st.group_sums(
                [shares[i] for i in members],
                [weights[i] for i in members],
                [inside[i] for i in members],
            )
            for members in grouped.values()
        ]
        total = st.GroupSums()
        for cluster in clusters:
            total = total + cluster
        try:
            top, rest = st.group_means(total)
            (d_low, d_high), (r_low, r_high) = st.bootstrap_contrast(
                clusters, level=level, resamples=resamples, seed=seed
            )
        except st.NotComputable as exc:
            notes.append(f"{cohort.name} / {MEASURE_LABEL[measure]}: no contrast, {exc}")
            continue
        results.append(
            ContrastResult(
                cohort=cohort.name,
                measure=measure,
                top_decile_share=top,
                elsewhere_share=rest,
                difference=top - rest,
                difference_interval=Interval(
                    low=d_low,
                    high=d_high,
                    method=f"parish cluster bootstrap, {resamples} resamples",
                    level=level,
                ),
                ratio=top / rest if rest > 0 else float("inf"),
                ratio_interval=Interval(
                    low=r_low,
                    high=r_high,
                    method=f"parish cluster bootstrap, {resamples} resamples",
                    level=level,
                ),
                top_decile_population=total.weight_in,
                elsewhere_population=total.weight_out,
            )
        )
    return results, notes


def summarise_cohort(cohort: Cohort) -> CohortSummary:
    population = sum(row.population for row in cohort.rows)
    clusters = {row.cluster for row in cohort.rows}
    _, total = _clusters_for(cohort.rows, Measure.BLACK, "pearson")
    try:
        effective: float | None = st.effective_sample_size(total)
    except st.NotComputable:
        effective = None
    return CohortSummary(
        name=cohort.name,
        description=cohort.description,
        n_hexes=len(cohort.rows),
        population=population,
        n_clusters=len(clusters),
        n_effective=effective,
        excluded=cohort.excluded,
    )


def analyse(
    rows: Sequence[HexRow],
    *,
    now: datetime,
    run_id: int | None,
    methodology_version: str,
    acs_vintage: str | None = None,
    resamples: int = st.DEFAULT_RESAMPLES,
    seed: int = st.DEFAULT_SEED,
    level: float = st.DEFAULT_LEVEL,
    notes: Sequence[str] = (),
) -> DisparityReport:
    """Compute the whole report from rows already loaded. No database, no I/O.

    Returns a `not_computable` report rather than raising when there is nothing
    to analyse, which is the same choice the quality gate makes when it skips a
    check: a run that could not measure something should say so in the artifact
    it produces, not vanish behind a traceback.
    """
    usable = [row for row in rows if row.population > 0]
    if not usable:
        return DisparityReport(
            run_id=run_id,
            analysed_at=now,
            methodology_version=methodology_version,
            acs_vintage=acs_vintage,
            status="not_computable",
            reason=(
                "No scored hex carries population. The disparity analysis reads hex_score "
                "and hex_demographics, and scoring (CS-204) has not produced rows for this run."
            ),
            notes=tuple(notes),
        )

    cohorts = build_cohorts(usable)
    correlations: list[CorrelationResult] = []
    contrasts: list[ContrastResult] = []
    collected: list[str] = list(notes)
    for cohort in cohorts:
        found, cohort_notes = correlations_for(cohort, resamples=resamples, seed=seed, level=level)
        correlations.extend(found)
        collected.extend(cohort_notes)
        contrast, contrast_notes = contrasts_for(
            cohort, resamples=resamples, seed=seed, level=level
        )
        contrasts.extend(contrast)
        collected.extend(contrast_notes)

    if not correlations:
        return DisparityReport(
            run_id=run_id,
            analysed_at=now,
            methodology_version=methodology_version,
            acs_vintage=acs_vintage,
            status="not_computable",
            reason=(
                "No correlation was computable on any cohort. The notes say what each "
                "measure ran into."
            ),
            cohorts=tuple(summarise_cohort(c) for c in cohorts),
            notes=tuple(collected),
        )

    return DisparityReport(
        run_id=run_id,
        analysed_at=now,
        methodology_version=methodology_version,
        acs_vintage=acs_vintage,
        status="computed",
        cohorts=tuple(summarise_cohort(c) for c in cohorts),
        correlations=tuple(correlations),
        contrasts=tuple(contrasts),
        notes=tuple(collected),
    )


# --- reading the warehouse ----------------------------------------------------


@runtime_checkable
class Connection(Protocol):
    """The slice of asyncpg this module needs.

    A protocol rather than an import, for the reason `pipeline.dasymetric.postgis`
    gives: the analysis should be testable and importable without a database
    driver, and the ETL package does not otherwise depend on asyncpg.
    """

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]: ...

    async def fetchrow(self, query: str, *args: Any) -> Mapping[str, Any] | None: ...


CURRENT_RUN_SQL = """
SELECT run_id, methodology_version
FROM pipeline_run
WHERE is_current
"""

# hex_demographics is joined on run_id as well as h3: the table is keyed by run
# precisely so an earlier score can still be read against the inputs it was built
# from, and joining on h3 alone would silently pair this run's scores with
# whichever run's demographics happened to sort first.
#
# The three share columns are read here and only here. Nothing in this query
# computes a score, which is the condition migration 0013's comment attaches to
# reading them at all.
ROWS_SQL = """
SELECT s.h3::text            AS h3,
       s.percentile          AS percentile,
       s.confidence_band     AS confidence_band,
       d.population          AS population,
       d.black_pct           AS black_pct,
       d.people_of_color_pct AS people_of_color_pct,
       d.acs_vintage         AS acs_vintage,
       COALESCE(h.parish_name, h.county_fips, 'unknown') AS cluster
FROM hex_score s
JOIN hex_demographics d ON d.run_id = s.run_id AND d.h3 = s.h3
JOIN hex h              ON h.h3 = s.h3
WHERE s.run_id = $1
  AND s.score IS NOT NULL
  AND s.percentile IS NOT NULL
"""


async def load_rows(conn: Connection, run_id: int) -> tuple[list[HexRow], str | None]:
    """Read one run's scored hexes with the shares they are analysed against."""
    records = await conn.fetch(ROWS_SQL, run_id)
    rows: list[HexRow] = []
    vintages: set[str] = set()
    for record in records:
        vintage = record.get("acs_vintage")
        if vintage is not None:
            vintages.add(str(vintage))
        rows.append(
            HexRow(
                h3=str(record["h3"]),
                percentile=float(record["percentile"]),
                population=float(record["population"]),
                black_pct=_optional_float(record.get("black_pct")),
                people_of_color_pct=_optional_float(record.get("people_of_color_pct")),
                confidence_band=(
                    None
                    if record.get("confidence_band") is None
                    else str(record["confidence_band"])
                ),
                cluster=str(record["cluster"]),
            )
        )
    # More than one vintage in a single run means the interpolation step mixed
    # ACS releases, which is a defect CS-105 owns rather than something to
    # average over here. Reported rather than resolved.
    vintage = sorted(vintages)[0] if len(vintages) == 1 else None
    return rows, vintage


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


async def run_disparity(
    conn: Connection,
    *,
    now: datetime,
    run_id: int | None = None,
    methodology_version: str | None = None,
    resamples: int = st.DEFAULT_RESAMPLES,
    seed: int = st.DEFAULT_SEED,
    level: float = st.DEFAULT_LEVEL,
) -> DisparityReport:
    """Resolve the run, read its rows, and analyse them.

    Defaults to the current run, the one the API and the tiles serve, so the
    published finding describes the data a reader is looking at rather than
    whichever run happened to finish last.
    """
    resolved_version = methodology_version
    if run_id is None:
        record = await conn.fetchrow(CURRENT_RUN_SQL)
        if record is None:
            return DisparityReport(
                run_id=None,
                analysed_at=now,
                methodology_version=resolved_version or "unknown",
                status="not_computable",
                reason=(
                    "No pipeline run is marked current, so there are no scores to analyse. "
                    "Scoring (CS-204) has not run, or its run was never promoted."
                ),
            )
        run_id = int(record["run_id"])
        if resolved_version is None:
            resolved_version = str(record["methodology_version"])

    rows, vintage = await load_rows(conn, run_id)
    notes: tuple[str, ...] = ()
    if rows and vintage is None:
        notes = (
            "Hexes in this run carry more than one ACS vintage. The analysis proceeds, but "
            "the mixture is a data defect worth chasing in CS-105.",
        )
    return analyse(
        rows,
        now=now,
        run_id=run_id,
        methodology_version=resolved_version or "unknown",
        acs_vintage=vintage,
        resamples=resamples,
        seed=seed,
        level=level,
        notes=notes,
    )
