"""The statewide run of methodology section 7, against an in-memory database.

`test_dasymetric.py` checks the arithmetic on a case small enough to do by
hand. This file checks the order that arithmetic runs in: counties are
discovered, each is intersected and stored inside its own transaction, and the
statewide population total is then re-derived from the rows that were actually
written.

The fake connection below is a real store rather than a set of canned answers.
`store_crosswalk` writes into it and `load_crosswalk` reads back out of it, so
the statewide check exercises the round trip instead of re-checking a crosswalk
that never left memory. That distinction is the point of the check: a crosswalk
verified in memory would pass even if the insert had written something else.

The fixture is the one from `test_dasymetric.py`, extended by a second county
so the per-county loop has more than one pass to make. Every expected number
here is still derivable on paper, and the working is in the comments.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest

from pipeline.dasymetric import postgis
from pipeline.dasymetric.build import (
    TOTAL_POPULATION,
    build_and_verify,
    build_county_crosswalk,
    build_state_crosswalk,
    verify_statewide_population,
)
from pipeline.dasymetric.quantities import KindMismatch
from pipeline.dasymetric.reconcile import ReconciliationFailed
from pipeline.dasymetric.weights import BlockOverlap

STATE = "22"
COUNTY_A = "22001"
COUNTY_B = "22003"
VINTAGE = "2019-2023"

T1 = "22001000100"
T2 = "22001000200"
T3 = "22003000100"
H1 = "8844c0b301fffff"
H2 = "8844c0b303fffff"
H3 = "8844c0b305fffff"

# County 22001 is the hand-checked fixture of test_dasymetric.py:
#   P(T1 n H1) = 175, P(T1 n H2) = 225, P(T1) = 400  -> weights 0.4375 / 0.5625
#   P(T2 n H2) = 200, P(T2) = 200                    -> weight 1.0
# County 22003 adds one tract of one block, wholly inside a third hexagon, so
# the second pass of the county loop has something to find.
OVERLAPS = [
    BlockOverlap("220010001001000", T1, H1, 100, 100.0, 100.0),
    BlockOverlap("220010001001001", T1, H1, 300, 200.0, 50.0),
    BlockOverlap("220010001001001", T1, H2, 300, 200.0, 150.0),
    BlockOverlap("220010002001000", T2, H2, 200, 100.0, 100.0),
    BlockOverlap("220030001001000", T3, H3, 500, 400.0, 400.0),
]

# Published ACS counts. They differ from the 2020 block populations on purpose:
# the block layer says where people are, the ACS says how many there are, and
# section 7 uses the first to place the second.
ACS_POPULATION = {T1: 440.0, T2: 210.0, T3: 500.0}
ACS_MOE = {T1: 40.0, T2: 30.0, T3: 50.0}


class FakeConnection:
    """An in-memory stand-in for the slice of asyncpg `postgis` declares.

    Queries are matched on the table they read, not by identity, so a harmless
    edit to the SQL does not quietly turn these tests into assertions about
    nothing.
    """

    def __init__(
        self,
        overlaps: Sequence[BlockOverlap] = (),
        estimates: Mapping[str, float] | None = None,
        margins: Mapping[str, float] | None = None,
        *,
        is_extensive: bool = True,
        fail_county: str | None = None,
    ) -> None:
        self.overlaps = list(overlaps)
        self.estimates = dict(estimates or {})
        self.margins = dict(margins or {})
        self.is_extensive = is_extensive
        self.fail_county = fail_county
        self.weights: dict[tuple[str, str], dict[str, Any]] = {}
        self.depth = 0
        self.max_depth = 0
        self.writes_outside_a_transaction = 0
        self.deletes: list[str] = []

    # --- the protocol ----------------------------------------------------

    async def fetch(self, query: str, *args: Any) -> Sequence[Mapping[str, Any]]:
        if "FROM census_tract" in query:
            state = str(args[0])
            counties = {o.tract_geoid[:5] for o in self.overlaps if o.tract_geoid.startswith(state)}
            return [{"county": c} for c in sorted(counties)]

        if "FROM census_block" in query:
            county = str(args[0])
            if county == self.fail_county:
                raise RuntimeError(f"intersection failed in {county}")
            return [
                {
                    "block_geoid": o.block_geoid,
                    "tract_geoid": o.tract_geoid,
                    "h3": o.h3,
                    "block_population": o.block_population,
                    "block_area_m2": o.block_area_m2,
                    "overlap_area_m2": o.overlap_area_m2,
                }
                for o in self.overlaps
                if o.tract_geoid[:5] == county
            ]

        if "FROM tract_demographics" in query:
            variable, vintage = str(args[0]), str(args[1])
            if vintage != VINTAGE:
                return []
            return [
                {
                    "tract_geoid": tract,
                    "variable": variable,
                    "estimate": value,
                    "margin_of_error": self.margins.get(tract),
                    "is_extensive": self.is_extensive,
                }
                for tract, value in sorted(self.estimates.items())
            ]

        if "FROM tract_hex_weight" in query:
            return [dict(row) for _, row in sorted(self.weights.items())]

        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, query: str, *args: Any) -> Any:
        assert "DELETE FROM tract_hex_weight" in query
        county = str(args[0])
        self.deletes.append(county)
        for key in [k for k in self.weights if k[0].startswith(county)]:
            del self.weights[key]
        return "DELETE"

    async def executemany(self, query: str, args: Iterable[Sequence[Any]]) -> Any:
        assert "INSERT INTO tract_hex_weight" in query
        if self.depth == 0:
            self.writes_outside_a_transaction += 1
        for row in args:
            tract, h3 = str(row[0]), str(row[1])
            self.weights[(tract, h3)] = {
                "tract_geoid": tract,
                "h3": h3,
                "population": float(row[2]),
                "pop_weight": float(row[3]),
                "area_weight": float(row[4]),
                "block_count": int(row[5]),
                "mean_block_area_m2": float(row[6]),
            }
        return "INSERT"

    def transaction(self) -> Any:
        @asynccontextmanager
        async def _txn() -> Any:
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            try:
                yield self
            finally:
                self.depth -= 1

        return _txn()


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection(OVERLAPS, ACS_POPULATION, ACS_MOE)


def test_the_fake_satisfies_the_protocol_the_module_declares(conn: FakeConnection) -> None:
    # Otherwise these tests could drift from what `postgis` actually asks for.
    assert isinstance(conn, postgis.Connection)


# --- the county loop -----------------------------------------------------


async def test_every_county_with_tracts_is_built(conn: FakeConnection) -> None:
    state = await build_state_crosswalk(conn, state_fips=STATE)
    assert [c.county_fips for c in state.counties] == [COUNTY_A, COUNTY_B]
    # T1 reaches two hexes, T2 and T3 one each.
    assert state.rows_written == 4
    assert state.ok


async def test_the_stored_weights_are_the_hand_checked_ones(conn: FakeConnection) -> None:
    await build_state_crosswalk(conn, state_fips=STATE)
    assert conn.weights[(T1, H1)]["pop_weight"] == pytest.approx(0.4375)
    assert conn.weights[(T1, H2)]["pop_weight"] == pytest.approx(0.5625)
    # Area share would have said 0.5 and 0.5. That gap is the whole ticket.
    assert conn.weights[(T1, H1)]["area_weight"] == pytest.approx(0.5)
    assert conn.weights[(T2, H2)]["population"] == pytest.approx(200.0)


async def test_the_delete_and_the_insert_share_one_transaction(conn: FakeConnection) -> None:
    # Between them the county has no crosswalk, and a reader that saw that
    # state would score the county as empty rather than as mid-rebuild.
    await build_state_crosswalk(conn, state_fips=STATE)
    assert conn.writes_outside_a_transaction == 0
    assert conn.max_depth == 1


async def test_rebuilding_one_county_leaves_the_others_alone(conn: FakeConnection) -> None:
    await build_state_crosswalk(conn, state_fips=STATE)
    before = dict(conn.weights)

    await build_county_crosswalk(conn, county_fips=COUNTY_A)

    assert conn.deletes == [COUNTY_A, COUNTY_B, COUNTY_A]
    assert conn.weights == before  # same rows, rewritten in place


async def test_a_rebuild_drops_weights_a_tract_no_longer_earns(conn: FakeConnection) -> None:
    # The delete is what stops a tract's weights summing to more than 1 after
    # the grid changes under it.
    await build_county_crosswalk(conn, county_fips=COUNTY_A)
    conn.overlaps = [o for o in OVERLAPS if o.h3 != H2 or o.tract_geoid != T1]

    await build_county_crosswalk(conn, county_fips=COUNTY_A)

    assert (T1, H2) not in conn.weights
    assert conn.weights[(T1, H1)]["pop_weight"] == pytest.approx(1.0)


async def test_counties_already_built_survive_a_later_failure() -> None:
    # The failure is in one county's geometry. Re-running should start from the
    # county that broke, not from the beginning, so the earlier ones stay.
    conn = FakeConnection(OVERLAPS, ACS_POPULATION, fail_county=COUNTY_B)
    with pytest.raises(RuntimeError):
        await build_state_crosswalk(conn, state_fips=STATE)
    assert (T1, H1) in conn.weights
    assert not any(tract.startswith(COUNTY_B) for tract, _ in conn.weights)


async def test_the_summary_reports_what_the_ancillary_layer_could_not_place() -> None:
    stranded = BlockOverlap("220030001001999", T3, H3, 70, 100.0, 0.0)
    conn = FakeConnection([*OVERLAPS, stranded], ACS_POPULATION)
    state = await build_state_crosswalk(conn, state_fips=STATE)
    assert state.unassigned_population == 70
    assert state.total_block_population == 1170  # 100 + 300 + 200 + 500 + 70
    assert "unassigned 70" in state.describe()


async def test_a_progress_callback_sees_each_county_as_it_lands(conn: FakeConnection) -> None:
    seen: list[str] = []
    await build_state_crosswalk(
        conn, state_fips=STATE, on_county=lambda c: seen.append(c.county_fips)
    )
    assert seen == [COUNTY_A, COUNTY_B]


# --- the statewide acceptance criterion ----------------------------------


async def test_the_statewide_total_survives_interpolation(conn: FakeConnection) -> None:
    # The acceptance criterion of CS-106 and of section 7. By hand:
    #   H1 = 440 * 0.4375                  = 192.5
    #   H2 = 440 * 0.5625 + 210 * 1.0      = 247.5 + 210 = 457.5
    #   H3 = 500 * 1.0                     = 500
    #   total = 1150 = 440 + 210 + 500
    await build_state_crosswalk(conn, state_fips=STATE)
    check = await verify_statewide_population(conn, acs_vintage=VINTAGE)

    assert check.ok
    assert check.reconciliation.tract_total == pytest.approx(1150.0)
    assert check.reconciliation.hex_total == pytest.approx(1150.0)
    assert check.reconciliation.relative_residual <= 1e-6
    assert check.tract_count == 3
    assert check.hex_count == 3


async def test_the_check_reads_the_rows_that_were_written(conn: FakeConnection) -> None:
    # A check against an in-memory crosswalk would pass even if the insert had
    # written something else. This one tampers with the stored rows and the
    # check notices, which is what says it read them.
    await build_state_crosswalk(conn, state_fips=STATE)
    conn.weights[(T1, H1)]["pop_weight"] = 0.20  # was 0.4375; T1 now loses people

    check = await verify_statewide_population(conn, acs_vintage=VINTAGE)

    assert not check.ok
    assert "OUT OF TOLERANCE" in check.reconciliation.describe()


async def test_a_tract_the_grid_never_reached_is_named_not_read_as_drift() -> None:
    # T3's county is absent from the crosswalk, so its 500 people land nowhere.
    # That is a hole in the grid, not arithmetic that lost people, and the two
    # have different fixes.
    conn = FakeConnection(OVERLAPS, ACS_POPULATION, ACS_MOE)
    await build_county_crosswalk(conn, county_fips=COUNTY_A)

    check = await verify_statewide_population(conn, acs_vintage=VINTAGE)

    assert check.reconciliation.raw_difference == pytest.approx(-500.0)
    assert check.reconciliation.explained == pytest.approx(500.0)
    assert check.reconciliation.residual == pytest.approx(0.0)
    assert check.reconciliation.detail == (T3,)
    assert check.ok


async def test_margins_reach_the_hex_and_are_not_invented(conn: FakeConnection) -> None:
    # Quadrature over the weighted tract margins, per section 7. For H2:
    #   sqrt( (0.5625 * 40)^2 + (1.0 * 30)^2 ) = sqrt(506.25 + 900)
    await build_state_crosswalk(conn, state_fips=STATE)
    estimates = await postgis.load_tract_estimates(
        conn, variable=TOTAL_POPULATION, acs_vintage=VINTAGE
    )
    crosswalk = await postgis.load_crosswalk(conn)
    from pipeline.dasymetric.interpolate import interpolate_extensive

    values = interpolate_extensive(crosswalk, estimates)
    assert values[H2].margin_of_error == pytest.approx(math.sqrt(0.5625**2 * 1600 + 900))


async def test_an_absent_estimate_stays_absent_through_the_loader() -> None:
    conn = FakeConnection(OVERLAPS, {T1: 440.0, T2: 210.0, T3: None})  # type: ignore[dict-item]
    rows = await postgis.load_tract_estimates(conn, variable=TOTAL_POPULATION, acs_vintage=VINTAGE)
    absent = [row for row in rows if row.tract_geoid == T3]
    assert absent and absent[0].estimate is None  # not 0.0


# --- what the check refuses to do ----------------------------------------


async def test_a_rate_cannot_be_reconciled_as_a_total(conn: FakeConnection) -> None:
    # Section 7's central distinction, enforced at the last place it could be
    # lost: intensive quantities do not sum, so they have no statewide total to
    # match.
    conn.is_extensive = False
    with pytest.raises(KindMismatch):
        await verify_statewide_population(conn, acs_vintage=VINTAGE)


async def test_a_variable_with_no_rows_is_an_error_not_a_silent_pass(
    conn: FakeConnection,
) -> None:
    with pytest.raises(ValueError, match="nothing to check"):
        await verify_statewide_population(conn, acs_vintage="2018-2022")


async def test_build_and_verify_refuses_a_crosswalk_that_did_not_close(
    conn: FakeConnection,
) -> None:
    # `build_and_verify` applies `require`, so a caller that reaches its return
    # value has a crosswalk whose totals closed. Here T2 loses half its weight
    # between the build and the check, and the run stops rather than loading.
    await build_state_crosswalk(conn, state_fips=STATE)
    original = conn.executemany

    async def drop_half(query: str, args: Iterable[Sequence[Any]]) -> Any:
        result = await original(query, args)
        if (T2, H2) in conn.weights:
            conn.weights[(T2, H2)]["pop_weight"] = 0.5
        return result

    conn.executemany = drop_half  # type: ignore[method-assign]

    with pytest.raises(ReconciliationFailed):
        await build_and_verify(conn, state_fips=STATE, acs_vintage=VINTAGE)


async def test_build_and_verify_runs_both_halves(conn: FakeConnection) -> None:
    state, check = await build_and_verify(conn, state_fips=STATE, acs_vintage=VINTAGE)
    assert state.rows_written == 4
    assert check.ok
    assert f"{TOTAL_POPULATION}" in check.describe()
