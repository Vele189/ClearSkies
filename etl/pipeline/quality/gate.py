"""The gate: run every check, decide whether the load may stand, say so loudly.

`run_adapter` already refuses to load a pull that lost too many records. It runs
once per source and knows only that source, so what it cannot do is judge the
night as a whole. This does: it takes the manifests every adapter produced and
the rows they loaded, applies the per-source thresholds and the cross-source
checks, and returns one report with one verdict.

**What the verdict means.** `fail` means something loaded that should not be
scored. The gate does not roll anything back — each adapter's transaction closed
long before this ran, and unwinding four committed sources to punish the fifth
would be worse than saying so. It means the run does not become the current one:
the nightly job exits non-zero, `pipeline_run.is_current` stays where it was, and
the map keeps serving last night's data until somebody looks. `warn` loads and
is reported. `skip` is neither, and is the reason `required` exists.

**Nothing here is quiet.** A gate whose only output is a return value is a log
line with extra steps. The report renders to Markdown for the Actions run page,
to workflow annotations that attach to the run itself, and to rows in
`quality_check_result` so a threshold can be tightened from history rather than
from memory.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from pipeline.metadata import PullMetadata
from pipeline.quality.checks import check_table
from pipeline.quality.cross import run_cross_checks
from pipeline.quality.dataset import Dataset
from pipeline.quality.expectations import for_source
from pipeline.quality.results import CheckResult, CheckStatus, QualityReport, promote_skips

# A manifest status is not a threshold, but it is the first thing a reader wants
# in the report, and a source that fell back to a snapshot is a fact about the
# night that the per-table checks cannot see: the rows are fine, they are just
# not current (methodology section 6).
_MANIFEST_STATUS: dict[str, CheckStatus] = {
    "ok": "pass",
    "partial": "warn",
    "stale": "warn",
    "failed": "fail",
}


def run_id_for(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def run_gate(
    *,
    manifests: Sequence[PullMetadata],
    data: Dataset,
    now: datetime,
    run_id: str | None = None,
    required: Iterable[str] = (),
    adapters: Mapping[str, Any] | None = None,
    pilot_state: str = "LA",
) -> QualityReport:
    """Check one night's load and return the report.

    `required` names the sources this run was supposed to produce. A check that
    skipped for one of them becomes a failure, because a green report over
    missing data is the failure mode this ticket exists to close. A source in
    `required` that produced no manifest at all fails outright.
    """
    wanted = tuple(dict.fromkeys(required))
    seen = {m.source for m in manifests}
    results: list[CheckResult] = []
    notes: list[str] = []

    for name in wanted:
        if name not in seen:
            results.append(
                CheckResult(
                    check="manifest_present",
                    scope=name,
                    status="fail",
                    detail=f"{name} was required for this run and produced no manifest at all.",
                )
            )

    for manifest in manifests:
        results += _check_source(
            manifest,
            data,
            adapter=(adapters or {}).get(manifest.source),
            pilot_state=pilot_state,
        )

    results += run_cross_checks(data)

    if not data.table_names():
        notes.append(
            "Nothing was loaded, so every check needing rows skipped. A dry run "
            "reports this; a nightly run should not."
        )

    return QualityReport(
        run_id=run_id or run_id_for(now),
        checked_at=now,
        results=tuple(promote_skips(results, required=wanted)),
        sources=tuple(sorted(seen | set(wanted))),
        notes=tuple(notes),
    )


def _check_source(
    manifest: PullMetadata,
    data: Dataset,
    *,
    adapter: Any = None,
    pilot_state: str = "LA",
) -> list[CheckResult]:
    """Everything checkable about one source's contribution to the night."""
    source = manifest.source
    results: list[CheckResult] = [_manifest_check(manifest)]

    expectations = for_source(source, adapter)
    if expectations is None:
        results.append(
            CheckResult(
                check="expectations_declared",
                scope=source,
                status="warn",
                detail=(
                    f"{source} declares no quality expectations, so it is checked only by the "
                    "interface's generic tolerance rule. Add a SourceExpectations for it."
                ),
            )
        )
        return results

    loaded = set(data.table_names())
    for table in expectations.tables:
        if table.table not in loaded:
            optional = table.table in expectations.optional_tables
            results.append(
                CheckResult(
                    check="table_loaded",
                    scope=source,
                    table=table.table,
                    status="pass" if optional else "skip",
                    detail=(
                        f"{table.table} is empty, which this source permits."
                        if optional
                        else f"{table.table} holds no rows, so its checks could not run."
                    ),
                    observed=0.0,
                )
            )
            continue
        results += check_table(data.rows(table.table), table, scope=source, pilot_state=pilot_state)
    return results


def _manifest_check(manifest: PullMetadata) -> CheckResult:
    status = _MANIFEST_STATUS.get(manifest.status, "warn")
    detail = f"{manifest.status}: {manifest.summary()}"
    if manifest.status == "stale":
        detail += " Upstream was unavailable; the recency term degrades (section 6)."
    if manifest.notes:
        detail += f" {manifest.notes[0]}"
    return CheckResult(
        check="pull_status",
        scope=manifest.source,
        status=status,
        detail=detail,
        observed=float(manifest.counts.loaded),
        expected="ok",
    )


__all__ = ["run_gate", "run_id_for"]
