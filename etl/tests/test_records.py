from typing import ClassVar

import pytest
from pydantic import ValidationError

from pipeline.records import Measurement, NormalizedRecord, duplicate_keys, group_by_table


class Reading(NormalizedRecord):
    table: ClassVar[str] = "readings"
    key: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.key,)


class Facility(NormalizedRecord):
    table: ClassVar[str] = "facilities"
    key: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.key,)


def test_a_measured_zero_is_an_observation() -> None:
    # Zero TRI releases within 10 km is a fact about the world.
    zero = Measurement.of(0.0)
    assert zero.value == 0.0
    assert zero.observed


def test_an_absent_measurement_carries_no_value() -> None:
    # No AirToxScreen value for the tract is an absence, and stays one.
    absent = Measurement.absent()
    assert absent.value is None
    assert not absent.observed


def test_a_value_cannot_be_smuggled_in_as_absent() -> None:
    with pytest.raises(ValidationError):
        Measurement(value=0.0, observed=False)


def test_an_observation_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        Measurement(value=None, observed=True)


def test_records_group_by_their_declared_table() -> None:
    grouped = group_by_table([Reading(key="a"), Facility(key="b"), Reading(key="c")])
    assert sorted(grouped) == ["facilities", "readings"]
    assert len(grouped["readings"]) == 2


def test_duplicate_keys_are_reported() -> None:
    assert duplicate_keys([Reading(key="a"), Reading(key="a")]) == [("readings", "a")]


def test_the_same_key_in_different_tables_is_not_a_duplicate() -> None:
    assert duplicate_keys([Reading(key="a"), Facility(key="a")]) == []
