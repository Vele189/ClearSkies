"""What a quality check produces, and the report they add up to.

One shape for every check, source-specific and cross-source alike, because the
report has to be readable by someone who did not write the check that failed.
A result says what was measured, what was expected, and what it means: a
`CheckResult` that only carries a boolean is a log line, and the point of this
ticket is that a bad load stops being a log line.

Four statuses rather than two. `skip` is the one that earns its place: a check
that could not run is not a check that passed, and a gate that quietly reports
"all green" because half its checks found no data is exactly the silent poisoning
CS-108 exists to prevent. Skips are counted, printed, and persisted like
everything else, and a skip whose source was expected to be present is promoted
to a failure by the gate.
"""

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import Field

from pipeline.metadata import Frozen, UtcDatetime

# pass  the measurement was inside the expectation
# warn  outside, but not far enough to throw away the load
# fail  outside far enough that loading would poison the score
# skip  the check could not run; the reason says why
CheckStatus = Literal["pass", "warn", "fail", "skip"]

# What a check is worth when it is violated. Declared on the expectation, not
# decided at the point of failure, so the severity of a threshold is reviewable
# next to the threshold itself.
Severity = Literal["warn", "fail"]

# A run is only as good as its worst check.
_RANK: dict[CheckStatus, int] = {"pass": 0, "skip": 1, "warn": 2, "fail": 3}

_ICON: dict[CheckStatus, str] = {"pass": "ok", "skip": "skipped", "warn": "warn", "fail": "FAIL"}


class CheckResult(Frozen):
    """One measurement against one expectation."""

    check: str = Field(description="Stable id, e.g. row_count or null_rate.latitude")
    scope: str = Field(description="Source registry name, or 'cross' for a cross-source check")
    status: CheckStatus
    detail: str = Field(description="One sentence a reader who did not write the check can act on")
    table: str | None = None
    field: str | None = None
    observed: float | None = Field(
        default=None, description="The number measured, kept so trends are queryable"
    )
    expected: str | None = Field(
        default=None, description="The bound, rendered for humans, e.g. '1200 to 1600'"
    )

    @property
    def ok(self) -> bool:
        return self.status in ("pass", "skip")

    @property
    def label(self) -> str:
        """The check's full name, including what it was measured on."""
        parts = [self.scope, self.check]
        if self.table is not None:
            parts.insert(1, self.table)
        return " / ".join(parts)

    def line(self) -> str:
        return f"[{_ICON[self.status]}] {self.label}: {self.detail}"

    def row(self) -> str:
        """One row for the Markdown table in the run report."""
        observed = "-" if self.observed is None else f"{self.observed:g}"
        return (
            f"| {_ICON[self.status]} | {self.scope} | {self.table or '-'} | "
            f"{self.check} | {observed} | {self.expected or '-'} | {self.detail} |"
        )


class QualityReport(Frozen):
    """Every check one pipeline run ran, and the verdict they add up to.

    The verdict is the worst status present, with `skip` treated as better than
    `warn`: a skipped check is a gap in coverage, not evidence of bad data. The
    gate is what decides whether a particular gap is tolerable, and it says so by
    turning that skip into a failure before the report is built.
    """

    run_id: str
    checked_at: UtcDatetime
    results: tuple[CheckResult, ...] = ()
    sources: tuple[str, ...] = Field(
        default=(), description="Registry names the gate was asked to check"
    )
    notes: tuple[str, ...] = ()

    @property
    def status(self) -> CheckStatus:
        if not self.results:
            return "skip"
        return max((r.status for r in self.results), key=lambda s: _RANK[s])

    @property
    def passed(self) -> bool:
        """Whether the run may load. A warning is visible but not blocking."""
        return self.status != "fail"

    def with_status(self, status: CheckStatus) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == status)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return self.with_status("fail")

    @property
    def warnings(self) -> tuple[CheckResult, ...]:
        return self.with_status("warn")

    @property
    def skipped(self) -> tuple[CheckResult, ...]:
        return self.with_status("skip")

    def tally(self) -> dict[CheckStatus, int]:
        counts: dict[CheckStatus, int] = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for result in self.results:
            counts[result.status] += 1
        return counts

    def summary(self) -> str:
        counts = self.tally()
        return (
            f"quality gate {self.status}: {counts['pass']} passed, "
            f"{counts['warn']} warned, {counts['fail']} failed, {counts['skip']} skipped"
        )

    def markdown(self) -> str:
        """The report as a page.

        Written to the GitHub Actions step summary by the nightly job, so a
        failed load is a thing a reader sees on the run page rather than a line
        somebody has to go looking for in the log.
        """
        counts = self.tally()
        verdict = "PASSED" if self.passed else "FAILED"
        lines = [
            f"# Data quality gate: {verdict}",
            "",
            f"Run `{self.run_id}` at {self.checked_at.strftime('%Y-%m-%d %H:%M')} UTC "
            f"over {len(self.sources)} source(s): {', '.join(self.sources) or 'none'}.",
            "",
            f"{counts['pass']} passed · {counts['warn']} warned · "
            f"{counts['fail']} failed · {counts['skip']} skipped",
        ]
        for note in self.notes:
            lines += ["", f"> {note}"]

        for heading, group in (
            ("Failures", self.failures),
            ("Warnings", self.warnings),
            ("Skipped", self.skipped),
        ):
            if not group:
                continue
            lines += ["", f"## {heading}", ""]
            lines += [f"- **{r.label}** — {r.detail}" for r in group]

        lines += [
            "",
            "## Every check",
            "",
            "| | Source | Table | Check | Observed | Expected | Detail |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [r.row() for r in self.results]
        return "\n".join(lines) + "\n"

    def annotations(self) -> tuple[str, ...]:
        """GitHub Actions workflow commands, one per failure and warning.

        These render against the run itself rather than inside the log, which is
        the difference between a failure somebody notices and a failure somebody
        finds a week later.
        """
        commands = []
        for result in self.failures:
            commands.append(f"::error title=Quality gate: {result.label}::{result.detail}")
        for result in self.warnings:
            commands.append(f"::warning title=Quality gate: {result.label}::{result.detail}")
        return tuple(commands)


def worst(results: Iterable[CheckResult]) -> CheckStatus:
    statuses = [r.status for r in results]
    if not statuses:
        return "skip"
    return max(statuses, key=lambda s: _RANK[s])


def promote_skips(results: Sequence[CheckResult], *, required: Iterable[str]) -> list[CheckResult]:
    """Turn a skipped check on a required source into a failure.

    A source the nightly job was told to load, whose checks all skipped because
    nothing arrived, is the single most dangerous state this gate can be in: the
    report is green and the data is missing. Naming the required sources up front
    is what closes it.
    """
    names = set(required)
    promoted = []
    for result in results:
        if result.status == "skip" and result.scope in names:
            promoted.append(
                result.model_copy(
                    update={
                        "status": "fail",
                        "detail": f"{result.detail} ({result.scope} was required for this run)",
                    }
                )
            )
        else:
            promoted.append(result)
    return promoted
