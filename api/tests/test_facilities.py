"""Turning a neighbour-query row into what the drill-down panel prints.

No database. The query itself is covered by tests/test_facility_hex_sql.py,
which needs one; this is the presentation on top of it, which does not.
"""

from typing import Any

from app.facilities import PANEL_LIMIT, program_label, to_facility

ROW: dict[str, Any] = {
    "facility_id": "110000449337",
    "registry_id": "110000449337",
    "name": "BIRLA CARBON USA INC - NORTH BEND PLANT",
    "distance_m": 4321.6,
    "decay_weight": 5.35e-08,
    "is_containing": False,
    "is_major_source": True,
    "has_title_v": True,
    "is_rcra_lqg": False,
    "is_rcra_tsdf": False,
    "geocode_quality": "suspect",
    "echo_url": "https://echo.epa.gov/detailed-facility-report?fid=110000449337",
    "quarters_in_noncompliance": 12,
    "formal_actions": 1,
    "penalty_usd": 25000,
}


def row(**overrides: Any) -> dict[str, Any]:
    return {**ROW, **overrides}


# ---- the permit label ---------------------------------------------------


def test_title_v_subsumes_major_source_rather_than_listing_both() -> None:
    """Every Title V source is a major source, so naming both is noise."""
    assert program_label(row()) == "CAA Title V"


def test_a_major_source_without_title_v_says_so() -> None:
    assert program_label(row(has_title_v=False)) == "CAA major source"


def test_hazardous_waste_programs_are_listed_alongside_the_air_permit() -> None:
    label = program_label(row(is_rcra_lqg=True, is_rcra_tsdf=True))

    assert label.startswith("CAA Title V")
    assert "RCRA large-quantity generator" in label
    assert "RCRA treatment, storage and disposal" in label


def test_a_facility_with_no_flags_is_still_a_clean_air_act_facility() -> None:
    """It is in the panel because it is in the ECHO air feed. That is a program."""
    label = program_label(row(has_title_v=False, is_major_source=False))

    assert label == "Clean Air Act"


# ---- the row ------------------------------------------------------------


def test_distance_is_reported_in_kilometres_without_false_precision() -> None:
    """The coordinates behind this are self-reported, most with km-scale accuracy."""
    assert to_facility(row()).distance_km == 4.32


def test_the_containing_hexagon_is_distinguished_from_a_nearby_one() -> None:
    assert to_facility(row(is_containing=True)).in_hex
    assert not to_facility(row()).in_hex


def test_a_facility_without_an_frs_id_falls_back_to_its_internal_id() -> None:
    """A TRI-only facility has no registry id, and the panel still has to link somewhere."""
    facility = to_facility(row(registry_id=None, facility_id="tri:70805BRLCR1234"))

    assert facility.registry_id == "tri:70805BRLCR1234"


def test_the_compliance_and_enforcement_counts_reach_the_panel() -> None:
    facility = to_facility(row())

    assert facility.quarters_in_noncompliance == 12
    assert facility.formal_actions_5yr == 1


def test_a_zero_count_is_carried_as_zero_rather_than_dropped() -> None:
    """Nobody found a violation is a fact. It is not the same as no data."""
    facility = to_facility(row(quarters_in_noncompliance=0, formal_actions=0))

    assert facility.quarters_in_noncompliance == 0
    assert facility.formal_actions_5yr == 0


def test_the_panel_limit_is_a_display_cap_not_a_scoring_one() -> None:
    """Documented here so a later reader does not mistake it for the 10 km cutoff."""
    assert PANEL_LIMIT == 50
