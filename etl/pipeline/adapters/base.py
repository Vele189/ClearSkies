"""The data source adapter interface.

Every source ClearSkies ingests implements this one class. Four stages, in
order, run by `pipeline.runner`:

    fetch      get bytes from upstream and say what release they are
    validate   accept or reject one raw record
    normalize  turn one accepted raw record into normalized records
    load       write normalized records through the sink

An adapter supplies domain knowledge: which URL, which columns, what a bad row
looks like, how a tract value becomes a hex value. It does not supply
infrastructure. Retries, rate limiting, checksums, snapshot fallback, transaction
boundaries, partial-failure tolerance and the provenance manifest are the
runner's, identical for all five sources and for the sixth.

The stage split is what makes that possible. `fetch` is the only stage allowed to
touch the network, so the runner can retry it as a unit and fall back to a
snapshot without the adapter knowing. `validate` and `normalize` are pure and
per record, so the runner can count losses and apply one tolerance rule across
every source. `load` is the only stage allowed to write, and the runner opens
and closes the transaction around it, so a pull that fails halfway leaves last
night's data intact.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from pipeline.context import RunContext
from pipeline.metadata import Artifact, KnownGap, SourceSpec
from pipeline.policy import DEFAULT_POLICY, SourcePolicy
from pipeline.quality.checks import SourceExpectations
from pipeline.records import NormalizedRecord, group_by_table


@dataclass(frozen=True, slots=True)
class FetchResult[Raw]:
    """What `fetch` hands back.

    `Raw` is the adapter's own row type: a dict, a dataclass, a parsed CSV line.
    It never leaves the adapter, so it can be whatever the source makes
    convenient.

    `vintage` is not optional and not a timestamp. It is the upstream release
    identifier — `2023` for a TRI reporting year, `2020_v2` for an AirToxScreen
    run, `acs5_2019_2023` for a Census release, a date for a daily API. The
    recency term in the confidence score is computed from the vintage, not from
    when the file happened to be downloaded, because downloading a six-year-old
    file today does not make it current.
    """

    records: Sequence[Raw]
    vintage: str
    artifacts: Sequence[Artifact] = ()
    known_gaps: Sequence[KnownGap] = ()
    notes: Sequence[str] = ()


class SourceAdapter[Raw](ABC):
    """Base class for every ClearSkies data source.

    Subclasses set `spec`, may narrow `policy`, and implement three methods.
    `load` has a working default and is overridden only by a source that needs
    something the sink protocol cannot express.
    """

    spec: ClassVar[SourceSpec]

    # Override only to change numbers, and say why in the commit message. The
    # field expected to vary is `rate_limit`, because each upstream publishes
    # its own. See pipeline/policy.py.
    policy: ClassVar[SourcePolicy] = DEFAULT_POLICY

    # What a good load of this source looks like: how many rows to expect, which
    # fields may be null and how often, what values are physically plausible.
    # `policy` decides whether a pull lost too many records; this decides whether
    # the records it kept are believable, which needs domain knowledge and so
    # belongs with the adapter that has it. See pipeline/quality/checks.py.
    #
    # Left unset a source is checked only by the generic tolerance rule, and the
    # gate reports that as a gap rather than a pass.
    expectations: ClassVar[SourceExpectations | None] = None

    @property
    def name(self) -> str:
        return self.spec.name

    @abstractmethod
    async def fetch(self, ctx: RunContext) -> FetchResult[Raw]:
        """Download the source and parse it into raw records.

        Use `ctx.http` for every request; it applies the retry policy, the rate
        limit, and the checksum, and it records the snapshot that a later
        unavailable-upstream night will fall back to. Use `ctx.now` for any
        timestamp.

        Raise `TransientSourceError` if the source looks temporarily unwell and
        `PermanentSourceError` if it has moved, been withdrawn, or changed shape
        beyond recognition. Both are handled by the runner; neither should be
        caught here in order to return partial data quietly.
        """

    @abstractmethod
    def validate(self, record: Raw, ctx: RunContext) -> None:
        """Check one raw record. Return None to accept it.

        Raise `RecordRejected` to drop it, with a reason short enough to be a
        useful histogram key: "latitude outside pilot state", not the row.
        Rejections are counted, sampled into the manifest, and weighed against
        `PartialFailurePolicy`, so a schema change upstream fails the run
        instead of quietly shrinking the map.

        Validate what makes a record unusable, not what makes it unusual. A
        facility with zero reported releases is valid. A facility whose
        coordinates fall in open water is not (methodology section 6).
        """

    @abstractmethod
    def normalize(self, record: Raw, ctx: RunContext) -> Iterable[NormalizedRecord]:
        """Turn one accepted raw record into zero or more normalized records.

        This is where source geography becomes project geography: a facility's
        lat/lon becomes an H3 resolution 8 cell, a tract value becomes hex
        values, a monitor reading becomes a measurement with a station id.

        Two rules the type system enforces where it can. Missing is not zero:
        emit `Measurement.absent()`, never `Measurement.of(0.0)`, for a value
        upstream did not report. And natural keys must be stable across runs, so
        tonight's pull updates last night's rows rather than duplicating them.

        May raise `RecordRejected`, which is counted exactly as a validation
        rejection is.
        """

    async def load(self, records: Sequence[NormalizedRecord], ctx: RunContext) -> int:
        """Write normalized records through the sink. Returns rows written.

        The default batches by table and upserts on the natural key, which is
        what every source built so far needs. The runner has already opened the
        transaction and will commit or roll it back, so an override must not
        commit on its own.
        """
        written = 0
        for table, batch in group_by_table(records).items():
            written += await ctx.sink.write(table, batch)
        return written

    def known_gaps(self, ctx: RunContext) -> Sequence[KnownGap]:
        """Gaps that are true of this source every time, whatever the pull found.

        OpenAQ's uneven monitor coverage belongs here. A gap discovered during a
        particular pull, such as a county missing from this year's release,
        belongs on the `FetchResult` instead. Both end up in the manifest and in
        docs/provenance.md.
        """
        return ()
