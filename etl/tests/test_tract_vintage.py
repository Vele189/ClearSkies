"""Crossing 2010 tract geography to 2020 (`pipeline.tract_vintage`).

The property that matters is that an intensive quantity stays intensive: a rate
carried across a boundary change must not be summed, inflated by a tract split,
or diluted by a merge. The rest is bookkeeping about what failed to cross, which
exists so a source covering three quarters of a state says so.
"""

from __future__ import annotations

import pytest

from pipeline.tract_vintage import (
    TractRelationship,
    parse_relationship,
    rekey_intensive,
    relationship_from_text,
)

HEADER = "OID_TRACT_20|GEOID_TRACT_20|GEOID_TRACT_10|AREALAND_PART"


def file_of(*rows: tuple[str, str, int]) -> str:
    return "\n".join([HEADER, *(f"oid|{new}|{old}|{area}" for new, old, area in rows)])


def test_parse_keeps_only_the_requested_state() -> None:
    relationship = relationship_from_text(
        file_of(
            ("22001960101", "22001960100", 100),
            ("01001020100", "01001020100", 100),
        ),
        state_fips="22",
    )
    assert relationship.tracts_2020() == ("22001960101",)


def test_parse_drops_pairs_that_share_no_land() -> None:
    """Two tracts can touch along a boundary and share no area."""
    relationship = relationship_from_text(
        file_of(("22001960101", "22001960100", 0), ("22001960101", "22001960200", 500)),
        state_fips="22",
    )
    assert relationship.parts["22001960101"] == (("22001960200", 500.0),)


def test_parse_survives_a_short_row() -> None:
    text = HEADER + "\n" + "oid|22001960101\n" + "oid|22001960101|22001960100|100"
    relationship = relationship_from_text(text, state_fips="22")
    assert relationship.parts["22001960101"] == (("22001960100", 100.0),)


def test_an_unchanged_tract_carries_its_value_exactly() -> None:
    """Most tracts do not move across a decade, and must not drift when they don't."""
    relationship = relationship_from_text(
        file_of(("22001960100", "22001960100", 5_000)), state_fips="22"
    )
    crossed = rekey_intensive({"22001960100": 42.5}, relationship)
    assert crossed.values == {"22001960100": 42.5}


def test_a_split_divides_the_area_and_not_the_rate() -> None:
    """One 2010 tract becoming two 2020 tracts: both inherit the rate, undiluted.

    The failure this guards against is treating a risk per million as extensive
    and apportioning it, which would halve a community's exposure because a
    census boundary moved.
    """
    relationship = relationship_from_text(
        file_of(
            ("22001960101", "22001960100", 6_000),
            ("22001960102", "22001960100", 4_000),
        ),
        state_fips="22",
    )
    crossed = rekey_intensive({"22001960100": 80.0}, relationship)
    assert crossed.values == {"22001960101": 80.0, "22001960102": 80.0}


def test_a_merge_takes_the_area_weighted_mean() -> None:
    """Two 2010 tracts becoming one: the new value sits between them, by land."""
    relationship = relationship_from_text(
        file_of(
            ("22001960100", "22001960101", 3_000),
            ("22001960100", "22001960102", 1_000),
        ),
        state_fips="22",
    )
    crossed = rekey_intensive({"22001960101": 100.0, "22001960102": 20.0}, relationship)
    # (100*3000 + 20*1000) / 4000
    assert crossed.values["22001960100"] == pytest.approx(80.0)


def test_a_partly_covered_tract_uses_only_the_parts_that_have_a_value() -> None:
    relationship = relationship_from_text(
        file_of(
            ("22001960100", "22001960101", 3_000),
            ("22001960100", "22001960102", 1_000),
        ),
        state_fips="22",
    )
    crossed = rekey_intensive({"22001960101": 50.0}, relationship)
    assert crossed.values["22001960100"] == pytest.approx(50.0)
    assert crossed.uncovered == ()


def test_a_tract_no_source_value_reaches_is_uncovered_not_zero() -> None:
    """Section 11: an absence is an absence. A zero here would read as clean air."""
    relationship = relationship_from_text(
        file_of(("22001960100", "22001960101", 3_000)), state_fips="22"
    )
    crossed = rekey_intensive({}, relationship)
    assert crossed.values == {}
    assert crossed.uncovered == ("22001960100",)


def test_a_source_tract_with_no_counterpart_is_counted() -> None:
    """The 273 Louisiana tracts that do not survive to 2020 must be visible."""
    relationship = relationship_from_text(
        file_of(("22001960100", "22001960101", 3_000)), state_fips="22"
    )
    crossed = rekey_intensive({"22001960101": 10.0, "22999999999": 99.0}, relationship)
    assert crossed.unmatched == ("22999999999",)
    assert "22999999999" not in crossed.values


def test_the_summary_names_the_approximation() -> None:
    """Whoever reads a manifest should learn this was area weighted, not population."""
    relationship = relationship_from_text(
        file_of(("22001960100", "22001960101", 3_000)), state_fips="22"
    )
    crossed = rekey_intensive({"22001960101": 10.0}, relationship)
    assert crossed.area_weighted is True
    assert "land area" in crossed.summary()


def test_an_empty_relationship_translates_nothing() -> None:
    crossed = rekey_intensive({"22001960101": 10.0}, TractRelationship())
    assert crossed.values == {}
    assert crossed.unmatched == ("22001960101",)


def test_parse_accepts_an_iterator_for_streaming() -> None:
    lines = iter(file_of(("22001960100", "22001960101", 10)).splitlines())
    relationship = parse_relationship(lines, state_fips="22")
    assert relationship.tracts_2010() == ("22001960101",)
