"""The spread the CS-308 audit draws from.

The gate names what fifty drafts have to cover, and a harness that quietly
covered less would report a pass that means less. These are the criteria,
checked without running the gate.
"""

from __future__ import annotations

from app.assistant.audit import (
    DRAFTABLE_BANDS,
    PROFILES,
    facilities_for,
    indicators_for,
    plan,
)
from app.assistant.documents import DOCUMENT_MODELS

TYPES = list(DOCUMENT_MODELS)

FACILITIES = [
    {"registry_id": f"1100000{i:05d}", "name": f"FACILITY {i}", "has_title_v": i % 3 == 0}
    for i in range(25)
]


def test_the_spread_covers_every_band_that_can_be_drafted_from() -> None:
    assert {p.band for p in PROFILES} == set(DRAFTABLE_BANDS)


def test_the_insufficient_band_is_absent() -> None:
    """Such a hexagon cannot be drafted from at all, so including one would
    measure the band check rather than the citations."""
    assert "insufficient" not in {p.band for p in PROFILES}


def test_the_spread_runs_down_to_hexagons_with_one_facility() -> None:
    """Thin evidence is where a model has least to work with and most
    temptation to pad with something it remembers."""
    assert min(p.facilities for p in PROFILES) == 1
    assert sum(1 for p in PROFILES if p.thin) >= 3


def test_the_spread_includes_a_densely_industrial_hexagon() -> None:
    assert max(p.facilities for p in PROFILES) >= 14


def test_every_profile_says_why_it_is_in_the_set() -> None:
    for profile in PROFILES:
        assert profile.note, profile.name


def test_profile_names_are_unique() -> None:
    assert len({p.name for p in PROFILES}) == len(PROFILES)


def test_fifty_drafts_cover_all_four_document_types() -> None:
    covered = {document_type for _, document_type, _ in plan(50, TYPES)}

    assert covered == set(TYPES)


def test_fifty_drafts_reach_every_profile() -> None:
    covered = {profile.name for profile, _, _ in plan(50, TYPES)}

    assert covered == {p.name for p in PROFILES}


def test_every_band_is_drafted_in_more_than_one_document_type() -> None:
    """Thirteen profiles and four types advance independently so the cycles do
    not lock into step. A single index would pair each band with one type and
    the spread would be narrower than it looks."""
    by_band: dict[str, set[str]] = {}
    for profile, document_type, _ in plan(50, TYPES):
        by_band.setdefault(profile.band, set()).add(document_type)

    for band, types in by_band.items():
        assert len(types) > 1, band


def test_the_low_band_is_drafted_from_at_least_ten_times() -> None:
    """The gate asks the spread to run to the low band, not to touch it once."""
    low = [p for p, _, _ in plan(50, TYPES) if p.band == "low"]

    assert len(low) >= 10


def test_an_unobserved_indicator_appears_outside_the_high_band() -> None:
    """Section 11: missing is dropped, never imputed. A draft that treats an
    absent monitor reading as a low one is the failure that rule prevents, so
    the audit has to contain the case."""
    low = next(p for p in PROFILES if p.band == "low")

    absent = [i for i in indicators_for(low) if not i["observed"]]
    assert absent
    assert absent[0]["value"] is None


def test_facilities_are_real_rows_from_the_table() -> None:
    profile = next(p for p in PROFILES if p.facilities == 1)

    attached = facilities_for(profile, FACILITIES, 0)

    assert len(attached) == 1
    assert attached[0]["registry_id"] in {f["registry_id"] for f in FACILITIES}


def test_the_window_moves_so_fifty_drafts_do_not_cite_one_facility() -> None:
    profile = PROFILES[0]

    first = {f["registry_id"] for f in facilities_for(profile, FACILITIES, 0)}
    later = {f["registry_id"] for f in facilities_for(profile, FACILITIES, 3)}

    assert first != later


def test_a_profile_gets_the_number_of_facilities_it_asks_for() -> None:
    for profile in PROFILES:
        assert len(facilities_for(profile, FACILITIES, 1)) == profile.facilities


def test_an_empty_facility_table_produces_no_facilities_rather_than_an_error() -> None:
    assert facilities_for(PROFILES[0], [], 0) == []
