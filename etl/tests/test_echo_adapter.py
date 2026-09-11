"""EPA ECHO adapter, against recorded fixtures. Nothing here touches the network.

The fixture is `tests/fixtures/echo/`: eight rows recorded from the live
Louisiana extract on 2026-09-11, plus seven synthetic rows covering edge cases
Louisiana's current extract does not contain. Synthetic rows say so in their
facility name.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import httpx
import pytest

from pipeline.adapters.echo import (
    GAZETTEER_URL,
    GET_FACILITIES,
    GET_QID,
    ComplianceQuarter,
    EnforcementAction,
    EpaEchoAdapter,
    Facility,
    quarter_start,
    twelve_quarters_ending,
)
from pipeline.context import RunContext
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.policy import PartialFailurePolicy, SourcePolicy
from pipeline.records import NormalizedRecord
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore
from tests.conftest import FIXED_NOW, FakeClock, make_context, make_fetcher

FIXTURES = Path(__file__).parent / "fixtures" / "echo"

# The fixture is 13 sites, two of them deliberately unusable. No real ECHO pull
# has a 15% rejection rate, so the production tolerance would rightly refuse to
# load it. Tests relax it; `test_the_shipped_policy_stays_strict` guards the
# real one against being loosened to match.
TEST_POLICY = SourcePolicy(
    rate_limit=EpaEchoAdapter.policy.rate_limit,
    partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
)


def echo_transport(
    *, facilities: str | None = None, qid: str | None = None, fail: set[str] | None = None
) -> httpx.MockTransport:
    down = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url in down:
            return httpx.Response(503)
        if url == GET_FACILITIES:
            body = facilities or (FIXTURES / "get_facilities.json").read_text()
            return httpx.Response(200, text=body, headers={"Content-Type": "application/json"})
        if url == GET_QID:
            page = request.url.params.get("pageno", "1")
            if page != "1":
                empty = {"Results": {"Message": "Success", "Facilities": []}}
                return httpx.Response(200, text=json.dumps(empty))
            body = qid or (FIXTURES / "get_qid_page1.json").read_text()
            return httpx.Response(200, text=body, headers={"Content-Type": "application/json"})
        if url == GAZETTEER_URL:
            return httpx.Response(
                200,
                content=(FIXTURES / "gazetteer_zcta.zip").read_bytes(),
                headers={"Content-Type": "application/zip"},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@asynccontextmanager
async def echo_context(
    sink: InMemorySink,
    *,
    transport: httpx.MockTransport | None = None,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
) -> AsyncIterator[RunContext]:
    async with build_client(TEST_POLICY, transport=transport or echo_transport()) as client:
        yield make_context(
            http=make_fetcher(
                client, source="epa_echo", policy=TEST_POLICY, snapshots=snapshots, clock=clock
            ),
            sink=sink,
            policy=TEST_POLICY,
            source="epa_echo",
        )


async def run(sink: InMemorySink, **kwargs: object) -> PullMetadata:
    async with echo_context(sink, **kwargs) as ctx:  # type: ignore[arg-type]
        return await run_adapter(EpaEchoAdapter(), ctx)


def facilities(sink: InMemorySink) -> dict[str, Facility]:
    return {r.registry_id: r for r in sink.rows(Facility.table) if isinstance(r, Facility)}


def quarters(sink: InMemorySink, registry_id: str) -> list[ComplianceQuarter]:
    rows = [
        r
        for r in sink.rows(ComplianceQuarter.table)
        if isinstance(r, ComplianceQuarter) and r.facility_id == registry_id
    ]
    return sorted(rows, key=lambda r: r.quarter)


def gaps_text(result: PullMetadata) -> str:
    return " ".join(gap.detail for gap in result.known_gaps)


def with_zeroed_coordinates(registry_id: str = "110000000005") -> str:
    """The shipped page with one site's coordinates replaced by a placeholder zero.

    Built from the fixture rather than added to it so the recorded Louisiana
    extract stays exactly what was recorded, and so the counts every other test
    asserts do not move.
    """
    page = json.loads((FIXTURES / "get_qid_page1.json").read_text())
    for row in page["Results"]["Facilities"]:
        if row.get("RegistryID") == registry_id:
            row["FacLat"], row["FacLong"] = "0", "0"
    return json.dumps(page)


@pytest.fixture
async def loaded(sink: InMemorySink) -> AsyncIterator[tuple[PullMetadata, InMemorySink]]:
    yield await run(sink), sink


# ---- the contract ------------------------------------------------------


async def test_the_adapter_is_registered_and_lists_the_indicators_it_feeds() -> None:
    from pipeline.adapters import get, names

    assert "epa_echo" in names()
    spec = get("epa_echo").spec
    assert spec.provides == ("F1", "F2", "F3", "F4")


async def test_a_pull_loads_facilities_quarters_and_enforcement(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert result.status == "partial"
    # 15 permit rows collapse to 13 sites, of which 2 are rejected.
    assert result.counts.fetched == 13
    assert result.counts.validated == 11
    assert result.counts.rejected == 2
    assert sink.count(Facility.table) == 11
    assert sink.count(ComplianceQuarter.table) == 11 * 12


async def test_several_permits_at_one_site_become_one_facility(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """The reason fetch groups rows.

    One FRS registry id can carry several air permits; 220 of 5,000 rows in the
    live Louisiana extract repeat one. facility_id is a primary key, and the
    runner fails a pull whose natural keys repeat, so grouping has to happen
    before normalize sees a record.
    """
    _, sink = loaded
    multi = facilities(sink)["110001248702"]

    assert len(multi.air_source_ids) == 3
    assert len(set(multi.air_source_ids)) == 3
    assert sum(1 for r in sink.rows(Facility.table) if r.natural_key() == ("110001248702",)) == 1


async def test_a_facility_carries_the_registry_id_the_public_link_is_built_from(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    facility = facilities(sink)["110000449337"]

    assert facility.registry_id == "110000449337"
    assert facility.facility_id == "110000449337"
    assert facility.echo_url == ("https://echo.epa.gov/detailed-facility-report?fid=110000449337")


# ---- compliance quarters, F2 -------------------------------------------


def test_the_twelve_quarters_end_with_the_quarter_containing_the_run() -> None:
    """Verified against a Detailed Facility Report, not assumed.

    EPA does not document the ordering of the twelve-character history string.
    The DFR for CITGO Lake Charles labels Qtr1Start 10/01/2023 and Qtr12Start
    07/01/2026 for a report run in September 2026, so position one is the
    oldest quarter.
    """
    starts = twelve_quarters_ending(date(2026, 9, 11))

    assert len(starts) == 12
    assert starts[0] == date(2023, 10, 1)
    assert starts[-1] == date(2026, 7, 1)
    assert starts == tuple(sorted(starts))
    assert all(start == quarter_start(start) for start in starts)


async def test_a_partial_history_dates_its_violations_oldest_first(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """CAMERON INTERSTATE reports 'SSSS________': four quarters, the oldest four."""
    _, sink = loaded
    rows = quarters(sink, "110058896388")

    assert [r.status for r in rows] == ["high_priority_violation"] * 4 + ["in_compliance"] * 8
    assert rows[0].quarter == date(2023, 10, 1)
    assert rows[3].quarter == date(2024, 7, 1)
    assert all(r.program == "CAA" for r in rows)


async def test_a_facility_in_violation_throughout_records_twelve_bad_quarters(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    rows = quarters(sink, "110000449337")

    assert [r.status for r in rows] == ["high_priority_violation"] * 12


async def test_an_unmonitored_quarter_is_unknown_and_not_compliant(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """The distinction the schema insists on: nobody looked is not the same as clean.

    ECHO writes '_' both for "no violation identified" and for a facility it
    holds no compliance record for at all. AIRComplStatus separates them.
    """
    _, sink = loaded
    unmonitored = quarters(sink, "110000000005")
    monitored = quarters(sink, "110000000004")

    assert {r.status for r in unmonitored} == {"unknown"}
    assert {r.status for r in monitored} == {"in_compliance"}


# ---- positional accuracy, methodology section 6 ------------------------


async def test_coordinates_are_judged_by_the_outcomes_the_schema_knows(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    found = facilities(sink)

    assert found["110000000001"].coordinate_status == "missing"
    assert found["110000000002"].coordinate_status == "outside_state"
    assert found["110000000003"].coordinate_status == "zip_mismatch"
    # The gazetteer has no 09999, so the check could not run. That is recorded
    # as 'ok' and counted, because not being checkable is not the same as failing.
    assert found["110000000004"].coordinate_status == "ok"


async def test_a_flagged_facility_keeps_its_row_and_its_coordinates(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Deleting them would hide the problem and make the exclusion count unrecoverable.

    Proximity indicators filter on coordinate_status = 'ok' instead.
    """
    _, sink = loaded
    texas = facilities(sink)["110000000002"]

    assert texas.latitude == pytest.approx(29.7604)
    assert texas.h3 is not None
    assert texas.coordinate_status == "outside_state"


async def test_a_facility_without_coordinates_gets_no_hex(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    nowhere = facilities(sink)["110000000001"]

    assert nowhere.latitude is None
    assert nowhere.h3 is None


async def test_real_louisiana_facilities_fail_the_zip_check(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Not a synthetic concern: three recorded rows sit over 2 km from their ZIP."""
    _, sink = loaded
    recorded = {"110058896388", "110000449337", "110013921435"}

    assert {facilities(sink)[r].coordinate_status for r in recorded} == {"zip_mismatch"}


async def test_the_exclusion_count_reaches_the_manifest(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Section 6 requires the count to be published, and the manifest is how."""
    result, _ = loaded
    text = gaps_text(result)

    assert "excluded from proximity indicators" in text
    assert "zip_mismatch" in text and "outside_state" in text and "missing" in text
    assert "could not be ZIP-checked" in text


async def test_a_zeroed_coordinate_is_quarantined_and_counted(sink: InMemorySink) -> None:
    """A placeholder zero is a quarantine, not a facility in the Gulf of Guinea.

    It reaches the manifest by the same path every other positional verdict
    does, so the count is published rather than discovered later by somebody
    wondering why a hexagon off the coast of Africa had a refinery in it.
    """
    result = await run(sink, transport=echo_transport(qid=with_zeroed_coordinates()))
    zeroed = facilities(sink)["110000000005"]

    assert zeroed.coordinate_status == "null_island"
    assert zeroed.geocode_quality == "absent"
    assert "null_island" in gaps_text(result)
    assert "excluded from proximity indicators" in gaps_text(result)


async def test_a_quarantined_row_keeps_what_upstream_actually_reported(
    sink: InMemorySink,
) -> None:
    """The verdict has to be auditable, so the rejected coordinate is kept beside it.

    The storable point goes, because writing (0, 0) into the geometry column
    would put a Louisiana facility in the Gulf of Guinea and every spatial query
    would then have to remember to distrust it.
    """
    await run(sink, transport=echo_transport(qid=with_zeroed_coordinates()))
    zeroed = facilities(sink)["110000000005"]

    assert zeroed.latitude is None and zeroed.longitude is None
    assert zeroed.h3 is None
    assert zeroed.reported_latitude == 0.0 and zeroed.reported_longitude == 0.0


async def test_epas_own_accuracy_estimate_is_stored_rather_than_discarded(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """CalculatedAccuracyMeters is requested by column id; it may as well be kept.

    It is the only independent evidence about a coordinate this pipeline gets,
    and section 12's spatial confidence term is the eventual consumer.
    """
    _, sink = loaded
    found = facilities(sink)

    assert found["110013921435"].geocode_accuracy_m == 50.0
    assert found["110001248702"].geocode_accuracy_m == 10_000.0


async def test_the_quality_flag_separates_checked_from_merely_uncheckable(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Three different states a usable coordinate can be in, kept apart on the row."""
    _, sink = loaded
    found = facilities(sink)

    # Sits on its ZIP centroid, but EPA's own accuracy estimate is 10 km.
    assert found["110001248702"].geocode_quality == "plausible"
    # ZIP 09999 is not in the pinned gazetteer, so the check could not run.
    assert found["110000000004"].geocode_quality == "unverified"
    # Failed the check outright.
    assert found["110000449337"].geocode_quality == "suspect"


# ---- rejections --------------------------------------------------------


async def test_unusable_records_are_rejected_for_stated_reasons(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded

    assert result.rejection_reasons == {
        "missing FRS registry id": 1,
        "reported state TX is not LA": 1,
    }


# ---- enforcement, F3 ---------------------------------------------------


async def test_a_formal_action_is_stored_with_its_date(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded
    actions = {
        r.facility_id: r
        for r in sink.rows(EnforcementAction.table)
        if isinstance(r, EnforcementAction)
    }
    action = actions["110000449337"]

    assert action.is_formal
    assert action.settled_on is not None
    assert action.program == "CAA"
    assert action.action_id.startswith("echo:110000449337:fea:")


async def test_the_enforcement_gap_is_declared_rather_than_papered_over(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """The bulk feed gives a five-year count and the latest date, not each action."""
    result, _ = loaded

    assert "not a record per action" in gaps_text(result)


# ---- provenance and policy ---------------------------------------------


async def test_the_manifest_records_every_artifact_with_a_checksum(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded
    urls = [a.url.split("?")[0] for a in result.artifacts]

    assert GET_FACILITIES in urls
    assert GET_QID in urls
    assert GAZETTEER_URL in urls
    assert all(len(a.sha256) == 64 for a in result.artifacts)
    assert not any(a.from_snapshot for a in result.artifacts)


async def test_the_vintage_is_the_refresh_date_not_the_download_time(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded

    assert result.vintage == f"weekly/{FIXED_NOW.date().isoformat()}"


async def test_the_2025_withdrawals_are_declared_as_a_known_gap(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """Why the stale fallback matters for this source in particular."""
    result, _ = loaded
    withdrawal = [g for g in result.known_gaps if g.since == date(2025, 1, 1)]

    assert withdrawal, "the 2025 EPA dataset withdrawals must be declared"
    assert "withdrawn" in withdrawal[0].detail
    assert withdrawal[0].affects == ("F1", "F2", "F3", "F4")


def test_the_adapter_declares_a_rate_limit_and_nothing_else_about_failure() -> None:
    """Rate limits and transient failures are the interface's job."""
    policy = EpaEchoAdapter.policy

    assert policy.rate_limit.requests_per_second == 2.0
    assert policy.retry == SourcePolicy().retry
    assert policy.stale_fallback


def test_the_shipped_policy_stays_strict() -> None:
    """The tests relax partial-failure tolerance; production must not follow."""
    assert EpaEchoAdapter.policy.partial_failure == PartialFailurePolicy()


async def test_a_second_pull_updates_rather_than_duplicates(sink: InMemorySink) -> None:
    for _ in range(2):
        await run(sink)

    assert sink.count(Facility.table) == 11
    assert sink.count(ComplianceQuarter.table) == 11 * 12


async def test_pagination_stops_when_a_short_page_arrives(sink: InMemorySink) -> None:
    """One page here, but fetch must not keep asking, and must not loop forever."""
    async with echo_context(sink) as ctx:
        await run_adapter(EpaEchoAdapter(), ctx)
        pages = [u for u in ctx.http.urls if u == GET_QID]

    assert len(pages) == 1


# ---- failure modes -----------------------------------------------------


async def test_an_expired_query_id_fails_the_run_and_loads_nothing(
    sink: InMemorySink,
) -> None:
    """A qid that returns no rows is an expired query, not an empty state."""
    empty = json.dumps({"Results": {"Message": "Success", "Facilities": []}})
    result = await run(sink, transport=echo_transport(qid=empty))

    assert result.status == "failed"
    assert sink.tables == {}
    assert "returned no rows" in " ".join(result.notes)


async def test_an_upstream_error_message_fails_the_run(sink: InMemorySink) -> None:
    refused = json.dumps(
        {"Results": {"Error": {"ErrorMessage": "Queryset Limit would be exceeded"}}}
    )
    result = await run(sink, transport=echo_transport(facilities=refused))

    assert result.status == "failed"
    assert "Queryset Limit" in " ".join(result.notes)


async def test_an_unavailable_echo_falls_back_to_the_last_snapshot(
    sink: InMemorySink,
) -> None:
    store = InMemorySnapshotStore()
    first = await run(sink, snapshots=store)
    assert first.status == "partial"

    second_sink = InMemorySink()
    result = await run(
        second_sink,
        transport=echo_transport(fail={GET_FACILITIES, GET_QID, GAZETTEER_URL}),
        snapshots=store,
        clock=FakeClock(),
    )

    assert result.status == "stale"
    assert second_sink.count(Facility.table) == 11
    assert all(a.from_snapshot for a in result.artifacts)
    assert "last good snapshot" in " ".join(result.notes)


def test_every_normalized_record_declares_a_table_and_a_key() -> None:
    for model in (Facility, ComplianceQuarter, EnforcementAction):
        assert issubclass(model, NormalizedRecord)
        assert isinstance(model.table, str) and model.table
