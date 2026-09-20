"""The error vocabulary the runner reacts to.

Adapters do not decide what to retry, what aborts a run, or what counts as a
tolerable loss. They raise from this small set and the runner applies the policy
in `pipeline.policy` uniformly. An adapter that invents its own control flow
around failure is the thing this module exists to prevent.
"""


class SourceError(Exception):
    """Base for every ingestion failure."""


class TransientSourceError(SourceError):
    """Worth trying again: a timeout, a connection reset, a 5xx, a 429.

    `retry_after` carries the upstream Retry-After hint in seconds when the
    server sent one; the retry policy prefers it over its own backoff.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentSourceError(SourceError):
    """Not worth trying again: a 404, a withdrawn dataset, a changed schema.

    Several EPA datasets were withdrawn from public hosting during 2025
    (methodology section 6), so this is an expected outcome rather than a bug.
    The runner falls back to the last good snapshot where one exists instead of
    treating it as a crash.
    """


class RecordRejected(SourceError):
    """One record failed validation or normalization. The run continues.

    Raised per record by `validate` and `normalize`. The runner counts these,
    keeps a sample for the manifest, and lets `PartialFailurePolicy` decide
    whether the accumulated losses invalidate the pull.
    """

    def __init__(
        self, reason: str, *, field: str | None = None, record_id: str | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.field = field
        self.record_id = record_id


class PartialFailureExceeded(SourceError):
    """Too many records were rejected for the pull to be trusted."""


class SinkError(SourceError):
    """The destination store rejected the write."""
