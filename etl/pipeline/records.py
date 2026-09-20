"""What `normalize` produces.

Adapters emit records, not rows. A record knows the table it belongs to and its
natural key, which is what lets the runner and the sink treat every source the
same way: batch by table, upsert by key, count what landed.

The `Measurement` type exists to make one rule structurally impossible to break.
Methodology section 11: a missing value is stored as missing, never as zero. Zero
TRI releases within 10 km is an observation. No AirToxScreen value for the tract
is an absence. Imputing the second to zero would systematically pull unmonitored
high-burden areas toward the middle, which is the failure this project exists to
avoid. So a measurement carries both the number and whether it was observed, and
the model rejects the combinations that would lose the distinction.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, model_validator


class Measurement(BaseModel):
    """A value that knows whether it was observed."""

    model_config = ConfigDict(frozen=True)

    value: float | None = None
    observed: bool = False

    @model_validator(mode="after")
    def _absent_means_none(self) -> Self:
        if self.observed and self.value is None:
            raise ValueError("an observed measurement must carry a value")
        if not self.observed and self.value is not None:
            raise ValueError("an absent measurement must not carry a value; use Measurement.of()")
        return self

    @classmethod
    def of(cls, value: float) -> "Measurement":
        """An observation. Zero is a perfectly good observation."""
        return cls(value=value, observed=True)

    @classmethod
    def absent(cls) -> "Measurement":
        """Upstream had nothing to say about this. Not zero, not the median."""
        return cls(value=None, observed=False)


class NormalizedRecord(BaseModel, ABC):
    """Base for everything an adapter loads.

    Subclasses set `table` and implement `natural_key`. The key is what makes a
    nightly re-pull idempotent: the same upstream row must produce the same key
    on every run, so re-ingesting a source updates rows instead of duplicating
    them.
    """

    model_config = ConfigDict(frozen=True)

    table: ClassVar[str]

    @abstractmethod
    def natural_key(self) -> tuple[str, ...]:
        """Stable identity of this record within its table."""


def group_by_table(
    records: Iterable[NormalizedRecord],
) -> dict[str, list[NormalizedRecord]]:
    grouped: dict[str, list[NormalizedRecord]] = {}
    for record in records:
        grouped.setdefault(type(record).table, []).append(record)
    return grouped


def duplicate_keys(records: Sequence[NormalizedRecord]) -> list[tuple[str, ...]]:
    """Natural keys appearing more than once. A non-empty result is a bug."""
    seen: set[tuple[str, ...]] = set()
    repeated: list[tuple[str, ...]] = []
    for record in records:
        key = (type(record).table, *record.natural_key())
        if key in seen:
            repeated.append(key)
        seen.add(key)
    return repeated
