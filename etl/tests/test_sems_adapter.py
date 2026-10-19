"""F5's source: Superfund sites with an NPL status, from EPA SEMS.

The fixture is Envirofacts' real response for Louisiana on 2026-10-19, cut to
one site per NPL status plus one site not on the NPL. What matters most here
is that every NPL status is stored, which status F5 counts being the scoring
query's decision, and that a site without coordinates is rejected rather than
placed at the origin.
"""

import json
from pathlib import Path

import h3
import httpx
import pytest

from pipeline.adapters.base import FetchResult
from pipeline.adapters.sems import (
    COUNTED_STATUSES,
    NPL_STATUSES,
    CleanupSite,
    EpaSemsAdapter,
    SemsSite,
    parse_sites,
)
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from tests.conftest import make_context, make_fetcher

FIXTURE = Path(__file__).parent / "fixtures" / "sems" / "la_sites.json"


def payload() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text())


async def fetch_from(body: bytes) -> FetchResult[SemsSite]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "fk_ref_state_code/equals/LA" in str(request.url)
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = make_fetcher(client, source="epa_sems")
        ctx = make_context(http=http, sink=None, source="epa_sems")  # type: ignore[arg-type]
        return await EpaSemsAdapter().fetch(ctx)


def site(**overrides: object) -> SemsSite:
    fields: dict[str, object] = {
        "site_id": "0600123",
        "epa_id": "LAD000000000",
        "name": "A SITE",
        "city": "BATON ROUGE",
        "county_fips": "22033",
        "state": "LA",
        "npl_status_code": "F",
        "npl_status_name": "Currently on the Final NPL",
        "federal_facility_ind": "N",
        "latitude": 30.45,
        "longitude": -91.18,
    }
    fields.update(overrides)
    return SemsSite(**fields)  # type: ignore[arg-type]


def test_every_npl_status_is_kept_and_not_on_the_npl_is_not() -> None:
    sites = parse_sites(payload(), "fixture")

    assert {s.npl_status_code for s in sites} == set(NPL_STATUSES)
    assert all(s.name != "BASS ENTERPRISES" for s in sites)


def test_f5_counts_final_and_proposed_only() -> None:
    """Section 8.2: established contamination, remedy not complete."""
    assert COUNTED_STATUSES == {"F", "P"}


def test_an_envirofacts_error_body_is_a_permanent_failure() -> None:
    """Envirofacts answers a bad query with 200 and `{"error": ...}`."""
    with pytest.raises(PermanentSourceError, match="expected a list"):
        parse_sites({"error": "column does not exist"}, "fixture")


async def test_fetch_dates_the_pull_and_says_what_f5_will_count() -> None:
    result = await fetch_from(FIXTURE.read_bytes())

    assert result.vintage.startswith("sems/")
    assert len(result.records) == 6
    assert "3 final or proposed" in result.notes[0]


def test_a_site_without_coordinates_is_rejected_not_placed_at_the_origin() -> None:
    ctx = make_context(http=None, sink=None, source="epa_sems")  # type: ignore[arg-type]
    with pytest.raises(RecordRejected, match="no coordinates"):
        EpaSemsAdapter().validate(site(latitude=None), ctx)


def test_a_coordinate_outside_the_state_is_rejected() -> None:
    """A dropped sign puts a Baton Rouge site in Kazakhstan."""
    ctx = make_context(http=None, sink=None, source="epa_sems")  # type: ignore[arg-type]
    with pytest.raises(RecordRejected, match="outside the pilot state"):
        EpaSemsAdapter().validate(site(longitude=91.18), ctx)


def test_a_site_in_another_state_is_rejected() -> None:
    ctx = make_context(http=None, sink=None, source="epa_sems")  # type: ignore[arg-type]
    with pytest.raises(RecordRejected, match="not the pilot state"):
        EpaSemsAdapter().validate(site(state="MS"), ctx)


def test_normalize_places_the_site_on_its_resolution_8_cell() -> None:
    (written,) = list(EpaSemsAdapter().normalize(site(federal_facility_ind="Y"), ctx=None))  # type: ignore[arg-type]

    assert isinstance(written, CleanupSite)
    assert written.h3 == h3.latlng_to_cell(30.45, -91.18, 8)
    assert h3.get_resolution(written.h3) == 8
    assert written.is_federal is True
    assert written.natural_key() == ("0600123",)


async def test_a_run_loads_every_npl_site_through_the_sink() -> None:
    sink = InMemorySink()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FIXTURE.read_bytes())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = make_fetcher(client, source="epa_sems")
        ctx = make_context(http=http, sink=sink, source="epa_sems")
        await run_adapter(EpaSemsAdapter(), ctx)

    assert sink.count(CleanupSite.table) == 6
