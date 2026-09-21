"""The 2020 block adapter (CS-112).

The network half is exercised by running it; what is worth pinning here is the
per-record logic the runner calls once per block, and the two rules that make
the layer usable by section 7: a block names the tract it sits in, and a
zero-population block is kept rather than dropped.
"""

from __future__ import annotations

from typing import Any

import pytest

from pipeline.adapters.census_block import (
    LOUISIANA_POPULATION_2020,
    CensusBlock,
    CensusBlockAdapter,
    RawBlock,
    _population_note,
    _raw_block,
)
from pipeline.errors import RecordRejected

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-92.0, 30.0], [-91.9, 30.0], [-91.9, 30.1], [-92.0, 30.1], [-92.0, 30.0]]],
}


def feature(geoid: str = "220019601011000", pop: Any = 42, geom: Any = SQUARE) -> dict[str, Any]:
    return {
        "properties": {"GEOID": geoid, "POP100": pop, "AREALAND": 12345, "TRACT": "960101"},
        "geometry": geom,
    }


def block(**overrides: Any) -> RawBlock:
    base = {
        "geoid": "220019601011000",
        "tract_geoid": "22001960101",
        "population": 42,
        "aland_m2": 12345,
        "polygons": ((((-92.0, 30.0), (-91.9, 30.0), (-91.9, 30.1), (-92.0, 30.0)),),),
    }
    return RawBlock(**{**base, **overrides})


def test_tract_geoid_is_composed_from_the_block_geoid() -> None:
    """TIGERweb's TRACT field is the six-digit code; the table wants eleven."""
    raw = _raw_block(feature())
    assert raw is not None
    assert raw.tract_geoid == "22001960101"
    assert raw.geoid.startswith(raw.tract_geoid)


def test_a_feature_without_an_identifier_is_skipped_not_raised() -> None:
    """There is nothing for a rejection to name, so it cannot be reported as one."""
    assert _raw_block({"properties": {}, "geometry": SQUARE}) is None


def test_missing_population_reads_as_zero_not_as_absent() -> None:
    """The Decennial census counts everyone; an empty block is empty."""
    raw = _raw_block(feature(pop=None))
    assert raw is not None
    assert raw.population == 0


def test_a_zero_population_block_is_kept() -> None:
    """Section 7 needs the zero: it stops marsh drawing people into a hexagon."""
    adapter = CensusBlockAdapter()
    adapter.validate(block(population=0), ctx=None)  # type: ignore[arg-type]
    records = list(adapter.normalize(block(population=0), ctx=None))  # type: ignore[arg-type]
    assert len(records) == 1
    assert isinstance(records[0], CensusBlock)
    assert records[0].population == 0


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        (block(geoid="2200196010"), "not 15"),
        (block(geoid="229999999999999", tract_geoid="22001960101"), "does not sit in the tract"),
        (block(population=-1), "reports population"),
        (block(polygons=()), "no usable geometry"),
    ],
)
def test_validate_rejects(bad: RawBlock, match: str) -> None:
    with pytest.raises(RecordRejected, match=match):
        CensusBlockAdapter().validate(bad, ctx=None)  # type: ignore[arg-type]


def test_normalize_carries_the_geometry_as_multipolygon_wkt() -> None:
    """census_block.geom is typed MultiPolygon and NOT NULL."""
    records = list(CensusBlockAdapter().normalize(block(), ctx=None))  # type: ignore[arg-type]
    assert records[0].geom_wkt.startswith("MULTIPOLYGON(")  # type: ignore[attr-defined]


def test_the_natural_key_is_the_block_geoid() -> None:
    record = CensusBlock(
        geoid="220019601011000",
        tract_geoid="22001960101",
        geom_wkt="MULTIPOLYGON(((0 0,1 0,1 1,0 0)))",
        population=1,
        aland_m2=None,
    )
    assert record.natural_key() == ("220019601011000",)
    assert record.table == "census_block"


def test_the_population_note_states_the_statewide_comparison() -> None:
    """CS-112 asks for the total to be recorded, not eyeballed."""
    exact = [block(population=LOUISIANA_POPULATION_2020)]
    assert "matches" in _population_note(exact)

    short = [block(population=1_000)]
    note = _population_note(short)
    assert "DOES NOT MATCH" in note
    assert "4,657,757" in note, "the published figure is named, not just the delta"


def test_the_adapter_declares_no_indicator() -> None:
    """Ancillary. The gate's group-minimum checks must not look for one."""
    assert CensusBlockAdapter.spec.provides == ()
