"""Runs an adapter's four stages and produces its provenance manifest.

This is the half of the interface that adapters do not implement. It is written
once so that all five sources fail the same way:

- an unreachable source falls back to the last good snapshot and reports `stale`
  rather than skipping the night or inventing values,
- rejected records are counted and weighed against one tolerance rule,
- a pull that loses too much is not loaded at all, leaving last night's data in
  place,
- every outcome, including failure, produces a `PullMetadata` row for
  docs/provenance.md.

`run_adapter` returns rather than raises for the failures a public data source is
expected to produce: unavailable, moved, reshaped, or partly unusable. A bug in
an adapter still raises, loudly.
"""

import time

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.context import RunContext
from pipeline.errors import (
    PermanentSourceError,
    RecordRejected,
    SinkError,
    SourceError,
    TransientSourceError,
)
from pipeline.metadata import (
    REJECTION_SAMPLE_LIMIT,
    KnownGap,
    PullMetadata,
    RecordCounts,
    Rejection,
    RunStatus,
    tally,
)
from pipeline.records import NormalizedRecord, duplicate_keys

UNAVAILABLE = "unavailable"


async def run_adapter[Raw](adapter: SourceAdapter[Raw], ctx: RunContext) -> PullMetadata:
    """Run one adapter end to end. Always returns a manifest."""
    started = time.monotonic()

    result: FetchResult[Raw] | None = None
    counts = RecordCounts()
    rejections: list[Rejection] = []
    reasons: list[str] = []
    extra_gaps: list[KnownGap] = []
    notes: list[str] = []
    static_gaps = tuple(adapter.known_gaps(ctx))

    def manifest(status: RunStatus) -> PullMetadata:
        return PullMetadata(
            source=adapter.spec.name,
            source_title=adapter.spec.title,
            vintage=result.vintage if result is not None else UNAVAILABLE,
            pulled_at=ctx.now,
            status=status,
            counts=counts,
            known_gaps=static_gaps
            + tuple(result.known_gaps if result is not None else ())
            + tuple(extra_gaps),
            artifacts=tuple(result.artifacts) if result is not None else (),
            rejections=tuple(rejections[:REJECTION_SAMPLE_LIMIT]),
            rejection_reasons=tally(reasons),
            duration_s=time.monotonic() - started,
            notes=tuple(notes) + tuple(result.notes if result is not None else ()),
        )

    # ---- fetch ---------------------------------------------------------
    stale = False
    try:
        result = await adapter.fetch(ctx)
    except (TransientSourceError, PermanentSourceError) as exc:
        ctx.log.warning("%s: fetch failed (%s)", adapter.name, exc)
        result = await _fetch_from_snapshot(adapter, ctx, notes)
        if result is None:
            notes.append(f"fetch failed: {exc}")
            return manifest("failed")
        stale = True
        extra_gaps.append(staleness_gap(adapter.spec.title))

    # ---- validate and normalize ---------------------------------------
    normalized: list[NormalizedRecord] = []
    accepted = 0

    for index, raw in enumerate(result.records):
        try:
            adapter.validate(raw, ctx)
            produced = list(adapter.normalize(raw, ctx))
        except RecordRejected as exc:
            rejections.append(
                Rejection(index=index, reason=exc.reason, field=exc.field, record_id=exc.record_id)
            )
            reasons.append(exc.reason)
            continue
        accepted += 1
        normalized.extend(produced)

    counts = RecordCounts(
        fetched=len(result.records),
        validated=accepted,
        rejected=len(rejections),
        normalized=len(normalized),
    )

    # A repeated natural key means tonight's pull would overwrite part of itself,
    # and which row survived would depend on iteration order. That is a defect in
    # the adapter, not a tolerable loss.
    repeated = duplicate_keys(normalized)
    if repeated:
        notes.append(f"{len(repeated)} duplicate natural keys, first {repeated[0]}")
        return manifest("failed")

    verdict = ctx.policy.partial_failure.verdict(accepted=accepted, rejected=len(rejections))
    if verdict == "failed":
        notes.append(
            f"rejected {len(rejections)} of {counts.fetched} records, "
            "above the configured tolerance; nothing was loaded"
        )
        return manifest("failed")

    status: RunStatus = "stale" if stale else verdict
    if stale and verdict == "partial":
        notes.append("records were also rejected; see rejection_reasons")

    # ---- load ----------------------------------------------------------
    if ctx.dry_run:
        notes.append("dry run: nothing was written")
        return manifest(status)

    await ctx.sink.begin(ctx.source)
    try:
        loaded = await adapter.load(normalized, ctx)
        counts = counts.model_copy(update={"loaded": loaded})
        final = manifest(status)
        await ctx.sink.commit(final)
    except (SinkError, SourceError) as exc:
        await ctx.sink.rollback()
        counts = counts.model_copy(update={"loaded": 0})
        notes.append(f"load failed and was rolled back: {exc}")
        ctx.log.exception("%s: load failed, rolled back", adapter.name)
        return manifest("failed")

    ctx.log.info("%s", final.summary())
    return final


async def _fetch_from_snapshot[Raw](
    adapter: SourceAdapter[Raw], ctx: RunContext, notes: list[str]
) -> FetchResult[Raw] | None:
    """Re-run fetch against the last good snapshot instead of the network.

    The adapter is unchanged and unaware: `ctx.http` serves stored bytes and
    flags the artifacts `from_snapshot`. Methodology section 6 requires exactly
    this — continue on the last good snapshot, let the recency term degrade,
    never substitute a different source.
    """
    if not ctx.policy.stale_fallback:
        return None
    if not await ctx.http.can_serve_offline():
        notes.append("no snapshot available to fall back to")
        return None

    ctx.http.offline = True
    try:
        result = await adapter.fetch(ctx)
    except SourceError as exc:
        notes.append(f"snapshot fallback also failed: {exc}")
        return None
    finally:
        ctx.http.offline = False

    notes.append("upstream unavailable; served from the last good snapshot")
    ctx.log.warning("%s: serving snapshot, recency degraded", adapter.name)
    return result


def staleness_gap(source_title: str) -> KnownGap:
    """The gap a stale run records about itself."""
    return KnownGap(
        scope="temporal",
        detail=f"{source_title} was unavailable; this pull reused the previous snapshot",
    )
