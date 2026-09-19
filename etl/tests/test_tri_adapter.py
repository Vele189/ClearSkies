"""EPA TRI adapter, against recorded fixtures. Nothing here touches the network.

The fixture is `tests/fixtures/tri/`: thirteen filings recorded from the live
Louisiana 2024 extract on 2026-09-11, plus five synthetic ones covering edge
cases that extract does not contain. Synthetic rows say so in their facility
name.

The recorded rows are chosen for what they prove rather than for being typical.
Denka at Reserve files dioxin in grams and has no coordinate in `tri_facility`.
Westlake Petrochemicals splits one chemical across three partial-facility forms.
House of Raeford files Form A certifications that report no quantity. Koch
Methanol is published under two different FRS ids by the two Envirofacts tables.
International Paper's Mansfield Mill is the state's largest TRI emitter that
does not join ECHO.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from pipeline.adapters.echo import (
    GAZETTEER_URL,
    GET_FACILITIES,
    GET_QID,
    RCRA_GET_FACILITIES,
    RCRA_GET_QID,
    Facility,
)
from pipeline.adapters.tri import (
    BASIC_FILE,
    GRAMS_PER_POUND,
    TRI_FACILITY,
    EpaTriAdapter,
    TriRelease,
    to_pounds,
)
from pipeline.context import RunContext
from pipeline.errors import RecordRejected
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.policy import PartialFailurePolicy, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore
from tests.conftest import FIXED_NOW, FakeClock, make_context, make_fetcher

FIXTURES = Path(__file__).parent / "fixtures" / "tri"
ECHO_FIXTURES = Path(__file__).parent / "fixtures" / "echo"

# The reporting year the fixture describes. FIXED_NOW is September 2026, and TRI
# ran about eighteen months behind then, so the adapter has to walk back past
# 2026 and 2025 to find it.
FIXTURE_YEAR = 2024

# The registry ids ECHO's air feed holds in these tests. Koch Methanol is here
# under 110070051640, the id `tri_facility` publishes; the Basic Data File
# publishes 110070742113 for the same site and that one is deliberately absent.
ECHO_REGISTRY_IDS = (
    "110000448659",  # Valero Refining - New Orleans
    "110067396669",  # Denka Performance Elastomer
    "110043973509",  # Westlake Petrochemicals Ethylene
    "110070051640",  # Koch Methanol St. James
)

# What ECHO's hazardous-waste feed holds in these tests, as (registry id,
# RCRA_UNIVERSE). The ECHO adapter loads a facility row for a large-quantity
# generator or TSD site whether or not it holds an air permit (CS-116), so this
# adapter must not write a second row over one. Neither id files to TRI in the
# fixture, so the default leaves every other test's counts alone; the one test that
# needs an overlap passes its own.
RCRA_HANDLERS: tuple[tuple[str, str], ...] = (
    ("110099999999", "LQG"),
    ("110072089073", "VSQG"),
)

VALERO = "110000448659"
DENKA = "110067396669"
WESTLAKE = "110043973509"
KOCH = "110070051640"
KOCH_BASIC_FILE_ID = "110070742113"
INTERNATIONAL_PAPER = "110000450173"
HOUSE_OF_RAEFORD = "110070674130"
ARCLIN = "110000597596"

BENZENE = "71-43-2"
CHLOROPRENE = "126-99-8"
DIOXIN = "N150"
FORMALDEHYDE = "50-00-0"
LEAD_COMPOUNDS = "N420"
ZINC_COMPOUNDS = "N982"

# The fixture is 13 sites, two of them deliberately unusable. No real TRI pull
# has a 15% rejection rate, so the production tolerance would rightly refuse to
# load it. Tests relax it; `test_the_shipped_policy_stays_strict` guards the
# real one against being loosened to match.
TEST_POLICY = SourcePolicy(
    rate_limit=EpaTriAdapter.policy.rate_limit,
    partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
)


def tri_transport(
    *,
    releases: str | None = None,
    directory: str | None = None,
    registry_ids: tuple[str, ...] = ECHO_REGISTRY_IDS,
    rcra_handlers: tuple[tuple[str, str], ...] = RCRA_HANDLERS,
    years: tuple[int, ...] = (FIXTURE_YEAR,),
    fail: set[str] | None = None,
) -> httpx.MockTransport:
    down = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url in down:
            return httpx.Response(503)
        if url.startswith(BASIC_FILE) and url.endswith("/COUNT/JSON"):
            year = int(url.split("/year/")[1].split("/")[0])
            total = 18 if year in years else 0
            return httpx.Response(200, text=json.dumps([{"TOTALQUERYRESULTS": total}]))
        if url.startswith(BASIC_FILE):
            body = releases or (FIXTURES / "basic_2024.json").read_text()
            return httpx.Response(200, text=body, headers={"Content-Type": "application/json"})
        if url.startswith(TRI_FACILITY):
            body = directory or (FIXTURES / "tri_facility.json").read_text()
            return httpx.Response(200, text=body, headers={"Content-Type": "application/json"})
        if url == GET_FACILITIES:
            opened = {"Results": {"QueryID": "777", "QueryRows": len(registry_ids)}}
            return httpx.Response(200, text=json.dumps(opened))
        if url == GET_QID:
            page = request.url.params.get("pageno", "1")
            rows = [{"RegistryID": rid} for rid in registry_ids] if page == "1" else []
            return httpx.Response(200, text=json.dumps({"Results": {"Facilities": rows}}))
        if url == RCRA_GET_FACILITIES:
            opened = {"Results": {"QueryID": "778", "QueryRows": len(rcra_handlers)}}
            return httpx.Response(200, text=json.dumps(opened))
        if url == RCRA_GET_QID:
            page = request.url.params.get("pageno", "1")
            handlers = (
                [
                    {"RegistryID": rid, "RCRAUniverse": universe, "Tsdf": None}
                    for rid, universe in rcra_handlers
                ]
                if page == "1"
                else []
            )
            return httpx.Response(200, text=json.dumps({"Results": {"Facilities": handlers}}))
        if url == GAZETTEER_URL:
            return httpx.Response(
                200,
                content=(ECHO_FIXTURES / "gazetteer_zcta.zip").read_bytes(),
                headers={"Content-Type": "application/zip"},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@asynccontextmanager
async def tri_context(
    sink: InMemorySink,
    *,
    transport: httpx.MockTransport | None = None,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
) -> AsyncIterator[RunContext]:
    async with build_client(TEST_POLICY, transport=transport or tri_transport()) as client:
        yield make_context(
            http=make_fetcher(
                client, source="epa_tri", policy=TEST_POLICY, snapshots=snapshots, clock=clock
            ),
            sink=sink,
            policy=TEST_POLICY,
            source="epa_tri",
        )


async def run(sink: InMemorySink, **kwargs: object) -> PullMetadata:
    async with tri_context(sink, **kwargs) as ctx:  # type: ignore[arg-type]
        return await run_adapter(EpaTriAdapter(), ctx)


def releases(sink: InMemorySink) -> dict[tuple[str, str], TriRelease]:
    return {
        (r.facility_id, r.cas_number): r
        for r in sink.rows(TriRelease.table)
        if isinstance(r, TriRelease)
    }


def facilities(sink: InMemorySink) -> dict[str, Facility]:
    return {r.facility_id: r for r in sink.rows(Facility.table) if isinstance(r, Facility)}


def gaps_text(result: PullMetadata) -> str:
    return " ".join(gap.detail for gap in result.known_gaps)


async def normalized(sink: InMemorySink, **kwargs: object) -> list[NormalizedRecord]:
    """Every record `normalize` produced, including the ones `load` cannot store."""
    adapter = EpaTriAdapter()
    async with tri_context(sink, **kwargs) as ctx:  # type: ignore[arg-type]
        fetched = await adapter.fetch(ctx)
        produced: list[NormalizedRecord] = []
        for record in fetched.records:
            try:
                adapter.validate(record, ctx)
            except RecordRejected:
                continue
            produced.extend(adapter.normalize(record, ctx))
        return produced


# ---- registration and shape ------------------------------------------------


async def test_the_adapter_is_registered_and_lists_the_indicator_it_feeds() -> None:
    from pipeline.adapters import get, names

    assert "epa_tri" in names()
    assert get("epa_tri") is EpaTriAdapter
    assert EpaTriAdapter.spec.provides == ("E3",)


async def test_a_pull_loads_releases_per_facility_per_year_per_chemical(
    sink: InMemorySink,
) -> None:
    result = await run(sink)

    assert result.status == "partial"
    assert result.counts.loaded > 0
    loaded = releases(sink)
    assert (VALERO, BENZENE) in loaded
    assert (DENKA, CHLOROPRENE) in loaded

    valero = loaded[(VALERO, BENZENE)]
    assert valero.reporting_year == FIXTURE_YEAR
    assert valero.chemical_name == "Benzene"
    assert valero.fugitive_air == Measurement.of(1530.0)
    assert valero.stack_air == Measurement.of(7562.0)
    assert valero.air_lb == Measurement.of(9092.0)


async def test_every_normalized_record_declares_a_table_and_a_key(sink: InMemorySink) -> None:
    for record in await normalized(sink):
        assert type(record).table
        assert all(isinstance(part, str) for part in record.natural_key())


# ---- vintage ---------------------------------------------------------------


async def test_the_vintage_is_the_reporting_year_not_the_download_date(
    sink: InMemorySink,
) -> None:
    result = await run(sink)

    assert result.vintage == str(FIXTURE_YEAR)
    assert result.pulled_at == FIXED_NOW
    assert result.pulled_at.year != FIXTURE_YEAR


async def test_the_reporting_year_is_discovered_rather_than_pinned(sink: InMemorySink) -> None:
    """Upstream ran eighteen months behind, so 2026 and 2025 hold nothing."""
    result = await run(sink)

    probed = [a.url for a in result.artifacts if a.url.endswith("/COUNT/JSON")]
    assert [url.split("/year/")[1].split("/")[0] for url in probed] == ["2026", "2025", "2024"]
    assert result.vintage == "2024"


async def test_an_older_release_is_used_when_it_is_the_newest_upstream_has(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=tri_transport(years=(2023,)))

    assert result.vintage == "2023"
    assert all(r.reporting_year == 2023 for r in releases(sink).values())


async def test_no_reporting_year_at_all_fails_the_run_and_loads_nothing(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=tri_transport(years=()))

    assert result.status == "failed"
    assert result.counts.loaded == 0
    assert sink.count(TriRelease.table) == 0


async def test_one_pull_never_mixes_two_reporting_years(sink: InMemorySink) -> None:
    await run(sink)

    assert {r.reporting_year for r in releases(sink).values()} == {FIXTURE_YEAR}


# ---- units -----------------------------------------------------------------


def test_pounds_are_recognised_however_upstream_spells_them() -> None:
    assert to_pounds(5.0, "Pounds") == 5.0
    assert to_pounds(5.0, "POUNDS") == 5.0
    assert to_pounds(5.0, " pounds ") == 5.0


def test_grams_are_converted_and_an_unknown_unit_is_refused() -> None:
    assert to_pounds(GRAMS_PER_POUND, "Grams") == pytest.approx(1.0)
    with pytest.raises(RecordRejected, match="unrecognised unit"):
        to_pounds(1.0, "Kilograms")


async def test_dioxin_reported_in_grams_is_stored_in_pounds(sink: InMemorySink) -> None:
    """Denka reports 0.09771 g of dioxin to stack air. Read as pounds it is 453x too big."""
    await run(sink)

    dioxin = releases(sink)[(DENKA, DIOXIN)]
    assert dioxin.stack_air.value == pytest.approx(0.09771 / GRAMS_PER_POUND)
    assert dioxin.stack_air.value == pytest.approx(0.000215, abs=1e-6)
    assert dioxin.fugitive_air == Measurement.of(0.0)


async def test_a_range_reported_release_arrives_already_resolved_to_its_midpoint(
    sink: InMemorySink,
) -> None:
    """Arclin reported fugitive formaldehyde as a range; EPA resolves it to 750 lb.

    This is why the Basic Data File is the release source. The raw
    `tri_release_qty` table carries only the range code.
    """
    await run(sink)

    formaldehyde = releases(sink)[(ARCLIN, FORMALDEHYDE)]
    assert formaldehyde.fugitive_air == Measurement.of(750.0)
    assert formaldehyde.stack_air == Measurement.of(3144.0)


async def test_a_filing_in_an_unknown_unit_is_rejected_rather_than_assumed(
    sink: InMemorySink,
) -> None:
    result = await run(sink)

    assert any("unrecognised unit of measure" in reason for reason in result.rejection_reasons)
    assert not any(f == "110000000002" for f, _ in releases(sink))


# ---- zero versus absent ----------------------------------------------------


async def test_a_form_r_reporting_zero_is_an_observation(sink: InMemorySink) -> None:
    await run(sink)

    lead = releases(sink)[("110003267946", LEAD_COMPOUNDS)]
    assert lead.fugitive_air == Measurement.of(0.0)
    assert lead.stack_air == Measurement.of(0.0)
    assert lead.air_lb == Measurement.of(0.0)
    assert lead.reported


async def test_a_form_a_filing_is_absent_and_is_never_written_as_zero(
    sink: InMemorySink,
) -> None:
    """House of Raeford certified under the alternate threshold and reported no quantity."""
    produced = await normalized(sink)
    absent = [
        r for r in produced if isinstance(r, TriRelease) and r.facility_id == HOUSE_OF_RAEFORD
    ]

    assert {r.cas_number for r in absent} == {ZINC_COMPOUNDS, "N100"}
    for record in absent:
        assert record.fugitive_air == Measurement.absent()
        assert record.stack_air == Measurement.absent()
        assert record.air_lb == Measurement.absent()
        assert not record.reported

    sink_after = InMemorySink()
    await run(sink_after)
    assert (HOUSE_OF_RAEFORD, ZINC_COMPOUNDS) not in releases(sink_after)


async def test_the_unquantified_filings_are_counted_in_the_manifest(sink: InMemorySink) -> None:
    result = await run(sink)

    assert "Form A" in gaps_text(result)
    assert "2 facility-chemical filings" in gaps_text(result)
    assert "not written as zero" in gaps_text(result)


async def test_zero_and_absent_are_never_merged(sink: InMemorySink) -> None:
    """The two facilities differ only in which form they filed."""
    produced = [r for r in await normalized(sink) if isinstance(r, TriRelease)]
    by_key = {(r.facility_id, r.cas_number): r for r in produced}

    reported_zero = by_key[("110003267946", LEAD_COMPOUNDS)]
    never_reported = by_key[(HOUSE_OF_RAEFORD, ZINC_COMPOUNDS)]

    assert reported_zero.air_lb.observed
    assert reported_zero.air_lb.value == 0.0
    assert not never_reported.air_lb.observed
    assert never_reported.air_lb.value is None
    assert reported_zero.air_lb != never_reported.air_lb


# ---- aggregation -----------------------------------------------------------


async def test_partial_facility_forms_for_one_chemical_are_summed(sink: InMemorySink) -> None:
    """Westlake filed benzene on three forms, each covering part of the site."""
    await run(sink)

    benzene = releases(sink)[(WESTLAKE, BENZENE)]
    assert benzene.fugitive_air == Measurement.of(1058.32 + 10198.27 + 0)
    assert benzene.stack_air == Measurement.of(2566.67 + 57405.89 + 20.73)


async def test_a_second_pull_updates_rather_than_duplicates(sink: InMemorySink) -> None:
    first = await run(sink)
    after_first = sink.count(TriRelease.table)
    second = await run(sink)

    assert sink.count(TriRelease.table) == after_first
    assert second.counts.loaded == first.counts.loaded


# ---- the ECHO join ---------------------------------------------------------


async def test_the_frs_id_that_joins_echo_is_preferred_over_the_basic_file_one(
    sink: InMemorySink,
) -> None:
    """Koch Methanol is 110070051640 in tri_facility and 110070742113 in the Basic Data File."""
    await run(sink)

    assert (KOCH, ZINC_COMPOUNDS) in releases(sink)
    assert (KOCH_BASIC_FILE_ID, ZINC_COMPOUNDS) not in releases(sink)
    assert KOCH not in facilities(sink)


async def test_a_matched_site_leaves_its_facility_row_to_the_echo_adapter(
    sink: InMemorySink,
) -> None:
    await run(sink)

    assert (VALERO, BENZENE) in releases(sink)
    assert VALERO not in facilities(sink)
    assert DENKA not in facilities(sink)


async def test_an_unmatched_site_keeps_its_own_facility_row_and_its_releases(
    sink: InMemorySink,
) -> None:
    """Mansfield Mill is Louisiana's largest TRI emitter that ECHO does not hold."""
    await run(sink)

    mill = facilities(sink)[INTERNATIONAL_PAPER]
    assert mill.name.startswith("INTERNATIONAL PAPER")
    assert mill.registry_id == INTERNATIONAL_PAPER
    assert mill.tri_facility_id == "71052NTRNTHWY50"
    assert mill.h3
    assert mill.coordinate_status == "ok"
    assert releases(sink)[(INTERNATIONAL_PAPER, FORMALDEHYDE)].air_lb == Measurement.of(6.2 + 33289)


async def test_the_unmatched_count_reaches_the_manifest(sink: InMemorySink) -> None:
    result = await run(sink)

    detail = gaps_text(result)
    assert "did not join an ECHO facility" in detail
    assert "rather than dropped" in detail
    assert "Mansfield" in detail
    assert f"{len(ECHO_REGISTRY_IDS)} sites joined an ECHO facility" in " ".join(result.notes)


async def test_a_hazardous_waste_site_echo_loads_keeps_its_facility_row_there(
    sink: InMemorySink,
) -> None:
    """The join is against both ECHO feeds, not just the air one (CS-116).

    The ECHO adapter loads a facility row for a large-quantity generator or TSD
    site whether or not it holds an air permit. A second row from here would be
    upserted over it on the same natural key, and the two hazardous-waste flags F4
    reads would be replaced by this adapter's defaults.
    """
    result = await run(sink, transport=tri_transport(rcra_handlers=((INTERNATIONAL_PAPER, "LQG"),)))

    assert INTERNATIONAL_PAPER not in facilities(sink)
    # The releases are this adapter's either way; only the facility row moves.
    assert (INTERNATIONAL_PAPER, FORMALDEHYDE) in releases(sink)
    assert result.status != "failed"


async def test_a_small_generator_does_not_take_a_facility_row_away(
    sink: InMemorySink,
) -> None:
    """F4 counts large-quantity generators and TSD facilities, and so does the join.

    A site ECHO holds only as a very small quantity generator gets no facility row
    from the ECHO adapter, so this one still owns it.
    """
    await run(sink, transport=tri_transport(rcra_handlers=((INTERNATIONAL_PAPER, "VSQG"),)))

    assert INTERNATIONAL_PAPER in facilities(sink)


async def test_a_site_with_no_frs_id_anywhere_is_keyed_on_its_tri_id(
    sink: InMemorySink,
) -> None:
    await run(sink)

    synthetic = facilities(sink)["tri:SYNTH0000000001"]
    assert synthetic.registry_id == ""
    assert synthetic.echo_url == ""
    assert ("tri:SYNTH0000000001", "108-88-3") in releases(sink)


async def test_an_expired_echo_query_fails_the_run_rather_than_reporting_no_matches(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=tri_transport(registry_ids=()))

    assert result.status == "failed"
    assert sink.count(TriRelease.table) == 0


# ---- positional accuracy ---------------------------------------------------


async def test_coordinates_are_judged_by_the_same_rule_the_echo_adapter_uses(
    sink: InMemorySink,
) -> None:
    await run(sink)
    loaded = facilities(sink)

    assert loaded["110000000003"].coordinate_status == "outside_state"
    assert loaded["110000000004"].coordinate_status == "zip_mismatch"
    assert loaded["tri:SYNTH0000000001"].coordinate_status == "ok"


async def test_a_flagged_facility_keeps_its_row_and_its_releases(sink: InMemorySink) -> None:
    await run(sink)

    texan = facilities(sink)["110000000003"]
    assert texan.latitude == pytest.approx(29.7604)
    assert texan.h3
    assert ("110000000003", "7664-41-7") in releases(sink)


async def test_the_exclusion_count_reaches_the_manifest(sink: InMemorySink) -> None:
    result = await run(sink)

    detail = gaps_text(result)
    assert "excluded from proximity indicators" in detail
    assert "outside_state 1" in detail
    assert "zip_mismatch 1" in detail
    assert "could not be ZIP-checked" in detail


async def test_the_zip_rule_is_published_as_a_threshold_problem_not_a_data_problem(
    sink: InMemorySink,
) -> None:
    """It excludes most Louisiana TRI sites, so E3's coverage loss has to be visible."""
    result = await run(sink)

    detail = gaps_text(result)
    assert "unverified location" in detail
    assert "not 'wrong location'" in detail
    assert "section 17" in detail


# ---- rejections ------------------------------------------------------------


async def test_a_facility_in_the_wrong_state_is_rejected_for_a_stated_reason(
    sink: InMemorySink,
) -> None:
    result = await run(sink)

    assert "reported state TX is not LA" in result.rejection_reasons
    assert "110000000005" not in facilities(sink)


# ---- provenance ------------------------------------------------------------


async def test_the_manifest_records_every_artifact_with_a_checksum(sink: InMemorySink) -> None:
    result = await run(sink)

    assert result.artifacts
    assert all(len(a.sha256) == 64 and a.size_bytes > 0 for a in result.artifacts)
    urls = " ".join(a.url for a in result.artifacts)
    assert BASIC_FILE in urls
    assert TRI_FACILITY in urls
    assert GET_QID in urls
    assert RCRA_GET_QID in urls
    assert GAZETTEER_URL in urls


async def test_the_e3_toxicity_weights_are_declared_as_another_sources_job(
    sink: InMemorySink,
) -> None:
    """This adapter loads the poundage; `epa_rsei` loads what multiplies it.

    The split is the point, not an omission: keeping the weights in their own
    table and their own pull means adopting a new RSEI edition never re-reads a
    single release.
    """
    result = await run(sink)

    detail = gaps_text(result)
    assert "RSEI" in detail
    assert "chemical_toxicity_weight is filled" in detail
    assert "epa_rsei" in detail


async def test_the_reporting_threshold_gap_is_declared(sink: InMemorySink) -> None:
    result = await run(sink)

    assert "reporting threshold" in gaps_text(result)
    assert "not all" in gaps_text(result)


async def test_the_2025_withdrawals_are_declared_as_a_known_gap(sink: InMemorySink) -> None:
    result = await run(sink)

    withdrawal = [g.since for g in result.known_gaps if g.since is not None]
    assert withdrawal and withdrawal[0].year == 2025


# ---- policy ----------------------------------------------------------------


def test_the_adapter_tunes_only_the_rate_limit_and_the_timeout() -> None:
    """Both departures are about how Envirofacts serves, not about failure handling."""
    policy = EpaTriAdapter.policy

    assert policy.rate_limit.requests_per_second == 2.0
    # A Louisiana year of the Basic Data File took 126 seconds to serve.
    assert policy.request_timeout_s >= 126.0
    assert policy.retry == SourcePolicy().retry
    assert policy.partial_failure == SourcePolicy().partial_failure
    assert policy.stale_fallback is True


def test_the_shipped_policy_stays_strict() -> None:
    tolerance = EpaTriAdapter.policy.partial_failure

    assert tolerance.max_reject_fraction <= 0.01
    assert tolerance.min_records >= 1


# ---- unavailable upstream --------------------------------------------------


async def test_an_unavailable_envirofacts_falls_back_to_the_last_snapshot(
    sink: InMemorySink,
    snapshots: InMemorySnapshotStore,
) -> None:
    good = await run(sink, snapshots=snapshots)
    assert good.status == "partial"

    stale_sink = InMemorySink()
    result = await run(
        stale_sink,
        snapshots=snapshots,
        transport=tri_transport(fail={f"{BASIC_FILE}/st/LA/year/2026/COUNT/JSON"}),
    )

    assert result.status == "stale"
    assert result.vintage == str(FIXTURE_YEAR)
    assert all(a.from_snapshot for a in result.artifacts)
    assert stale_sink.count(TriRelease.table) == sink.count(TriRelease.table)
