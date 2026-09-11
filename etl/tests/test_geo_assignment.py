"""Facility-to-hex assignment and the section 6 coordinate verdicts.

Real coordinates throughout. A synthetic latitude proves the branch was taken;
a refinery's actual position proves the branch was taken for the right reason,
and these rules exist to keep a real refinery out of the wrong neighbourhood.
"""

import math

import h3
import pytest

from pipeline.geo import (
    HEX_RESOLUTION,
    INTERACTION_RADIUS_M,
    PILOT_BOUNDS,
    QUARANTINED,
    Envelope,
    classify,
    containing_cell,
    haversine_km,
    interaction_envelope,
)

# Places, so a failure names somewhere rather than a number.
BATON_ROUGE = (30.4515, -91.1871)
LAKE_CHARLES = (30.2266, -93.2174)
# ExxonMobil Beaumont refinery, Jefferson County, Texas. The case methodology
# section 5 names: out of state, close enough to matter to Louisiana.
BEAUMONT = (30.0838, -94.0916)
HOUSTON = (29.7604, -95.3698)


# ---- distance -----------------------------------------------------------


def test_haversine_matches_a_known_separation() -> None:
    # Baton Rouge to Lake Charles, about 196 km.
    assert haversine_km(*BATON_ROUGE, *LAKE_CHARLES) == pytest.approx(196, abs=3)


def test_a_point_is_no_distance_from_itself() -> None:
    assert haversine_km(*BATON_ROUGE, *BATON_ROUGE) == pytest.approx(0.0, abs=1e-9)


# ---- the envelope -------------------------------------------------------


def test_the_buffer_is_the_interaction_radius_at_both_ends_of_the_box() -> None:
    """Longitude degrees shrink towards the pole, so one constant is short at the top.

    Louisiana spans four degrees of latitude, which is enough for the cosine to
    matter: a longitude buffer computed once at the southern edge comes out
    about 4% narrow at the northern one. `buffered` resolves that by taking the
    cosine at whichever edge is furthest from the equator, so the buffer is
    never short and is at most a few percent generous at the other edge. Ten
    metres of tolerance on the lower bound, because the great circle between two
    points on a parallel cuts very slightly inside it.
    """
    box = PILOT_BOUNDS["LA"]
    wider = box.buffered(INTERACTION_RADIUS_M)
    radius_km = INTERACTION_RADIUS_M / 1000.0

    for latitude in (box.south, box.north):
        west_gap = haversine_km(latitude, box.west, latitude, wider.west)
        assert west_gap >= radius_km - 0.01
        assert west_gap <= radius_km * 1.05


def test_the_buffer_is_not_extravagant() -> None:
    """Loose enough not to flag a coastal facility, tight enough to mean something."""
    box = PILOT_BOUNDS["LA"]
    wider = box.buffered(INTERACTION_RADIUS_M)

    assert haversine_km(box.south, box.west, wider.south, box.west) < 15.0


def test_an_unknown_pilot_state_says_so_rather_than_accepting_everything() -> None:
    with pytest.raises(KeyError, match="PILOT_BOUNDS"):
        interaction_envelope("ZZ")


def test_the_envelope_is_case_insensitive() -> None:
    assert interaction_envelope("la") == interaction_envelope("LA")


def test_a_box_excludes_its_outside() -> None:
    box = Envelope(south=0.0, north=1.0, west=0.0, east=1.0)

    assert box.contains(0.5, 0.5)
    assert box.contains(0.0, 1.0)
    assert not box.contains(1.5, 0.5)


# ---- the six verdicts ---------------------------------------------------


def test_no_coordinate_is_missing_not_zero() -> None:
    verdict = classify(None, None, state="LA")

    assert verdict.status == "missing"
    assert verdict.quality == "absent"
    assert not verdict.usable
    assert not verdict.has_point


def test_a_zeroed_coordinate_is_told_apart_from_a_wrong_one() -> None:
    """Null Island is a placeholder somebody wrote into an empty field.

    The envelope would reject (0, 0) anyway. It is named separately because the
    fix for a zeroed field and the fix for a transcription error are different,
    and section 6 publishes the counts rather than one total.
    """
    zeroed = classify(0.0, 0.0, state="LA")

    assert zeroed.status == "null_island"
    assert zeroed.quality == "absent"
    assert not zeroed.has_point


def test_a_coordinate_just_off_null_island_is_judged_on_its_position() -> None:
    """The tolerance is about 55 m, not a region. A real facility there is still wrong."""
    nearby = classify(0.01, 0.01, state="LA")

    assert nearby.status == "outside_state"


def test_an_impossible_latitude_is_out_of_range_not_merely_out_of_state() -> None:
    for latitude, longitude in ((91.0, -91.0), (-90.5, -91.0), (30.0, 181.0)):
        verdict = classify(latitude, longitude, state="LA")
        assert verdict.status == "out_of_range"
        assert not verdict.has_point


def test_a_non_finite_coordinate_does_not_reach_the_comparisons() -> None:
    """math.nan compares false against everything, so it would pass a range check."""
    assert classify(math.nan, -91.0, state="LA").status == "out_of_range"
    assert classify(30.0, math.inf, state="LA").status == "out_of_range"


def test_a_coordinate_in_another_state_entirely_is_quarantined() -> None:
    verdict = classify(*HOUSTON, state="LA")

    assert verdict.status == "outside_state"
    assert verdict.quality == "suspect"
    # Kept as a point: a reviewer asking why this row was excluded has to be
    # able to see where upstream put it.
    assert verdict.has_point


def test_a_beaumont_facility_is_usable_because_it_can_reach_a_louisiana_hex() -> None:
    """Methodology section 5, the case it names.

    A hex on the Texas line near a Beaumont-area facility must not be
    artificially clean, so the coordinate check cannot be the thing that throws
    the facility away. Whether it is close enough to any particular hexagon is
    the neighbour query's question, on real geometry.
    """
    verdict = classify(*BEAUMONT, state="LA", accuracy_m=25.0)

    assert verdict.status == "ok"
    assert verdict.usable


def test_a_coordinate_far_from_its_reported_zip_is_quarantined() -> None:
    """Baton Rouge coordinates against a Lake Charles ZIP centroid."""
    verdict = classify(*BATON_ROUGE, state="LA", zip_centroid=LAKE_CHARLES)

    assert verdict.status == "zip_mismatch"
    assert verdict.quality == "suspect"
    assert verdict.zip_distance_km == pytest.approx(196, abs=3)


def test_a_check_that_could_not_run_is_not_a_check_that_passed() -> None:
    """No ZIP reported, or one the pinned gazetteer does not carry."""
    verdict = classify(*BATON_ROUGE, state="LA", zip_centroid=None, accuracy_m=10.0)

    assert verdict.status == "ok"
    assert verdict.quality == "unverified"
    assert not verdict.zip_checked
    assert verdict.zip_distance_km is None


# ---- the quality flag ---------------------------------------------------


def test_a_close_coordinate_with_a_tight_accuracy_estimate_is_verified() -> None:
    nearby = (BATON_ROUGE[0] + 0.005, BATON_ROUGE[1])
    verdict = classify(*nearby, state="LA", zip_centroid=BATON_ROUGE, accuracy_m=25.0)

    assert verdict.status == "ok"
    assert verdict.quality == "verified"
    assert verdict.accuracy_m == 25.0


def test_a_close_coordinate_epa_itself_calls_coarse_is_only_plausible() -> None:
    """Typical of the live extract: accuracy estimates of 10 km and 100 km appear."""
    nearby = (BATON_ROUGE[0] + 0.005, BATON_ROUGE[1])
    verdict = classify(*nearby, state="LA", zip_centroid=BATON_ROUGE, accuracy_m=10_000.0)

    assert verdict.quality == "plausible"


def test_a_missing_accuracy_estimate_is_plausible_rather_than_verified() -> None:
    nearby = (BATON_ROUGE[0] + 0.005, BATON_ROUGE[1])

    assert classify(*nearby, state="LA", zip_centroid=BATON_ROUGE).quality == "plausible"


def test_the_accuracy_estimate_survives_a_quarantine() -> None:
    """It is evidence about why the row was quarantined, so it is not discarded."""
    assert classify(*HOUSTON, state="LA", accuracy_m=50.0).accuracy_m == 50.0


# ---- quarantine is a filter, not a deletion -----------------------------


def test_every_verdict_but_ok_keeps_the_facility_out_of_proximity_indicators() -> None:
    """QUARANTINED and the SQL `coordinate_status = 'ok'` filter say the same thing."""
    verdicts = {
        classify(None, None, state="LA").status,
        classify(0.0, 0.0, state="LA").status,
        classify(200.0, -91.0, state="LA").status,
        classify(*HOUSTON, state="LA").status,
        classify(*BATON_ROUGE, state="LA", zip_centroid=LAKE_CHARLES).status,
    }

    assert verdicts == QUARANTINED
    assert "ok" not in QUARANTINED


# ---- the containing cell ------------------------------------------------


def test_a_facility_is_assigned_the_resolution_eight_cell_that_contains_it() -> None:
    cell = containing_cell(*BATON_ROUGE)

    assert cell is not None
    assert h3.is_valid_cell(cell)
    assert h3.get_resolution(cell) == HEX_RESOLUTION == 8
    assert h3.cell_to_latlng(cell) == pytest.approx(BATON_ROUGE, abs=0.01)


def test_the_cell_index_is_the_fifteen_character_string_the_schema_stores() -> None:
    """The h3_cell domain is text with a 15-hex-digit check, not h3-pg's h3index."""
    cell = containing_cell(*BATON_ROUGE)

    assert cell is not None
    assert len(cell) == 15
    assert all(c in "0123456789abcdef" for c in cell)


def test_a_facility_with_no_point_gets_no_cell() -> None:
    assert containing_cell(None, None) is None
    assert containing_cell(30.0, None) is None
    assert containing_cell(None, -91.0) is None


def test_an_out_of_state_facility_still_gets_its_own_cell() -> None:
    """The reason migration 0014 drops the foreign key from facility.h3 to hex.

    A Beaumont facility sits in a cell. That cell is not in the Louisiana grid,
    and the facility is still a real facility with a real location, so the
    column records where it is rather than refusing to.
    """
    cell = containing_cell(*BEAUMONT)

    assert cell is not None
    assert h3.is_valid_cell(cell)


def test_two_facilities_in_one_cell_agree_on_which_cell() -> None:
    """Resolution 8 averages 0.737 km2, so two points 100 m apart usually share one."""
    a = containing_cell(*BATON_ROUGE)
    b = containing_cell(BATON_ROUGE[0] + 0.0005, BATON_ROUGE[1])

    assert a == b
