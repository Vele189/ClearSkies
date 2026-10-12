"""Section 9's denominator belongs to a state, and this is what keeps it there.

The failure these tests exist for is silent. Ranking two states against one
denominator does not raise; it returns percentiles computed over a set nobody
asked for, and section 13.2's pre-registered criterion -- eight of ten
documented sites in the *statewide* top decile -- carries on reporting a pass
or a fail against it. So the two things worth asserting are that partitioning
changes nothing while there is one state, and that it changes the right thing
as soon as there are two.

Every indicator is given the same value for a given hex, so a hex's rank in
each of the fifteen is the rank of its one number. That makes the expected
percentiles arithmetic rather than a fixture nobody can check by eye.
"""

from collections.abc import Mapping

import pytest

from burden.component import compute
from burden.eligibility import eligible
from burden.percentile import rank_indicators
from burden.pollution import POLLUTION_BURDEN
from burden.population import POPULATION_CHARACTERISTICS
from burden.score import burden_score
from burden.states import score_by_state

#: All fifteen, so every group clears its `minimum_present` and a hex scores.
INDICATORS = (
    "E1",
    "E2",
    "E3",
    "E4",
    "F1",
    "F2",
    "F3",
    "F4",
    "S1",
    "S2",
    "P1",
    "P2",
    "P3",
    "P4",
    "P5",
)

POPULATION = 500.0


def values_for(levels: Mapping[str, float]) -> dict[str, dict[str, float | None]]:
    """One number per hex, repeated across every indicator."""
    return {indicator: dict(levels) for indicator in INDICATORS}


def all_inside(levels: Mapping[str, float]) -> dict[str, bool]:
    """Every hex centred in its own state, which is the ordinary case."""
    return dict.fromkeys(levels, True)


def unpartitioned(levels: Mapping[str, float]):
    """The run as it was computed before 0031: one universe, one denominator."""
    cover = {h3: POPULATION for h3 in levels}
    values = values_for(levels)
    eligibility = eligible(cover)
    scored = eligibility.scored
    rankings = rank_indicators(values, scored=scored)
    return burden_score(
        eligibility=eligibility,
        pollution=compute(POLLUTION_BURDEN, rankings, scored=scored),
        population=compute(POPULATION_CHARACTERISTICS, rankings, scored=scored),
    )


def rows(run) -> list[tuple[str, float | None, float | None, float | None, float | None]]:
    return [
        (h.h3, h.score, h.percentile, h.pollution_burden, h.population_characteristics)
        for h in run.hexes
    ]


# ---- One state ----------------------------------------------------------


def test_one_state_reproduces_the_unpartitioned_run_exactly() -> None:
    """The regression that has to hold before any second state is loaded.

    Partitioning a single state is the identity. If any stored percentile moves
    here, the partition is wrong, and it is far cheaper to learn that against
    Louisiana alone than after a second state has been published against it.
    """
    levels = {"a": 1.0, "b": 4.0, "c": 9.0, "d": 16.0, "e": 25.0}
    cover = {h3: POPULATION for h3 in levels}

    before = unpartitioned(levels)
    after = score_by_state(
        cover=cover,
        state_of=dict.fromkeys(levels, "22"),
        centroid_in_state=all_inside(levels),
        values=values_for(levels),
    )

    assert len(after) == 1
    assert after[0].state_fips == "22"
    assert rows(after[0].run) == rows(before)


def test_one_state_keeps_the_distributions_it_was_ranked_against() -> None:
    levels = {"a": 1.0, "b": 2.0, "c": 3.0}
    after = score_by_state(
        cover={h3: POPULATION for h3 in levels},
        centroid_in_state=all_inside(levels),
        state_of=dict.fromkeys(levels, "22"),
        values=values_for(levels),
    )
    assert set(after[0].rankings) == set(INDICATORS)
    assert after[0].rankings["E1"].distribution.n == 3


# ---- Two states ---------------------------------------------------------


def test_each_state_is_ranked_against_itself_and_not_the_other() -> None:
    """The point of the whole change.

    Louisiana's values here are an order of magnitude below the other state's.
    Under one denominator every Louisiana hex lands in the bottom half and its
    worst-burdened cell reads as unremarkable. Ranked within its own state, the
    worst cell in each state takes the same top percentile -- which is what
    "statewide percentile" has always meant, and what section 15 warns is not
    comparable between them.
    """
    la = {"la_low": 1.0, "la_mid": 2.0, "la_high": 3.0}
    wv = {"wv_low": 100.0, "wv_mid": 200.0, "wv_high": 300.0}
    levels = {**la, **wv}
    state_of = {**dict.fromkeys(la, "22"), **dict.fromkeys(wv, "54")}

    runs = {
        run.state_fips: run
        for run in score_by_state(
            cover={h3: POPULATION for h3 in levels},
            centroid_in_state=all_inside(levels),
            state_of=state_of,
            values=values_for(levels),
        )
    }

    assert set(runs) == {"22", "54"}

    la_rows = runs["22"].run.by_h3()
    wv_rows = runs["54"].run.by_h3()

    # Each state ranked three hexes, not six.
    assert runs["22"].rankings["E1"].distribution.n == 3
    assert runs["54"].rankings["E1"].distribution.n == 3

    # The worst cell in each state sits at the same place in its own state.
    assert la_rows["la_high"].percentile == wv_rows["wv_high"].percentile
    assert la_rows["la_low"].percentile == wv_rows["wv_low"].percentile

    # And under a single denominator it would not have: every Louisiana hex
    # would rank below every other, which is the reading being prevented.
    pooled = unpartitioned(levels).by_h3()
    assert pooled["la_high"].percentile < pooled["wv_low"].percentile


def test_a_state_is_rescaled_against_its_own_maximum() -> None:
    """Section 10 step 3's divisor is the highest value *in the state*, so the
    worst hex in each state reaches the top of the 0-to-10 range regardless of
    what the other state's numbers look like."""
    la = {"la_low": 1.0, "la_high": 3.0}
    wv = {"wv_low": 100.0, "wv_high": 300.0}
    levels = {**la, **wv}

    runs = {
        run.state_fips: run
        for run in score_by_state(
            cover={h3: POPULATION for h3 in levels},
            centroid_in_state=all_inside(levels),
            state_of={**dict.fromkeys(la, "22"), **dict.fromkeys(wv, "54")},
            values=values_for(levels),
        )
    }

    la_top = runs["22"].run.by_h3()["la_high"]
    wv_top = runs["54"].run.by_h3()["wv_high"]
    assert la_top.pollution_burden == wv_top.pollution_burden
    assert la_top.score == wv_top.score


def test_states_come_back_in_state_fips_order() -> None:
    levels = {"b": 1.0, "a": 2.0}
    runs = score_by_state(
        cover={h3: POPULATION for h3 in levels},
        centroid_in_state=all_inside(levels),
        state_of={"b": "54", "a": "22"},
        values=values_for(levels),
    )
    assert [run.state_fips for run in runs] == ["22", "54"]


# ---- What it refuses to do quietly --------------------------------------


def test_a_hex_with_no_state_is_an_error_rather_than_a_dropped_row() -> None:
    """A cell nobody can place is a cell nobody can rank. Dropping it would
    shrink a denominator without saying so."""
    levels = {"placed": 1.0, "orphan": 2.0}
    with pytest.raises(ValueError, match="no state to be ranked in"):
        score_by_state(
            cover={h3: POPULATION for h3 in levels},
            centroid_in_state=all_inside(levels),
            state_of={"placed": "22"},
            values=values_for(levels),
        )


def test_a_state_with_nothing_scored_still_accounts_for_its_hexes() -> None:
    """Section 5 excludes a hex under 25 residents. A state of nothing but
    those still has to return them: `hex_score` carries a reason for every cell
    the run knew about, and the map draws them rather than leaving a hole."""
    runs = {
        run.state_fips: run
        for run in score_by_state(
            cover={"la": POPULATION, "empty_1": 0.0, "empty_2": 1.0},
            state_of={"la": "22", "empty_1": "54", "empty_2": "54"},
            centroid_in_state={"la": True, "empty_1": True, "empty_2": True},
            values=values_for({"la": 1.0, "empty_1": 2.0, "empty_2": 3.0}),
        )
    }

    assert set(runs) == {"22", "54"}
    wv = runs["54"].run
    assert [h.h3 for h in wv.hexes] == ["empty_1", "empty_2"]
    assert all(h.score is None for h in wv.hexes)
    assert all(h.no_score_reason == "low_population" for h in wv.hexes)


# ---- The buffer is not part of any state's denominator ------------------


def test_a_buffer_cell_is_not_ranked_even_when_it_has_people() -> None:
    """Section 6: "percentiles are computed over included hexes only".

    The buffer exists so a facility across the line can reach a cell that is
    inside. Louisiana hid the omission because its buffer cells receive no
    interpolated population at all -- population arrives through census blocks,
    which stop at the line -- so they were excluded for being empty rather than
    for being outside. The District's boundary blocks straddle into the buffer,
    and 26 cells centred in Maryland and Virginia were ranked inside the
    District's denominator before this was passed in.
    """
    levels = {"in_1": 1.0, "in_2": 2.0, "in_3": 3.0, "over_the_line": 4.0}
    runs = score_by_state(
        cover={h3: POPULATION for h3 in levels},
        state_of=dict.fromkeys(levels, "11"),
        centroid_in_state={"in_1": True, "in_2": True, "in_3": True, "over_the_line": False},
        values=values_for(levels),
    )

    assert len(runs) == 1
    rows = runs[0].run.by_h3()

    # Ranked against three, not four.
    assert runs[0].rankings["E1"].distribution.n == 3
    assert rows["over_the_line"].score is None
    assert rows["over_the_line"].no_score_reason == "outside_scored_states"

    # And the cell with the highest value inside is the top of the state,
    # rather than second to a cell that is not in it.
    inside = {h3: row.percentile for h3, row in rows.items() if row.percentile is not None}
    assert max(inside, key=lambda h3: inside[h3]) == "in_3"


def test_a_buffer_cell_still_gets_a_row_saying_why() -> None:
    """It is in the grid, so hex_score has to account for it. The map draws it
    as not scored rather than leaving a hole."""
    levels = {"inside": 1.0, "outside": 2.0}
    runs = score_by_state(
        cover={h3: POPULATION for h3 in levels},
        state_of=dict.fromkeys(levels, "11"),
        centroid_in_state={"inside": True, "outside": False},
        values=values_for(levels),
    )
    assert sorted(h.h3 for h in runs[0].run.hexes) == ["inside", "outside"]


def test_a_hex_with_no_centroid_flag_is_an_error() -> None:
    with pytest.raises(ValueError, match="whether their centroid is inside"):
        score_by_state(
            cover={"a": POPULATION, "b": POPULATION},
            state_of={"a": "11", "b": "11"},
            centroid_in_state={"a": True},
            values=values_for({"a": 1.0, "b": 2.0}),
        )
