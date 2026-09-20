"""Census ACS adapter, against fixtures. Nothing here touches the network.

`tests/fixtures/census_acs/` holds three files. The two geometry fixtures were
recorded from TIGERweb on 2026-09-11, which needs no credential: the Louisiana
outline at `maxAllowableOffset=0.02` and six real tracts at 0.005, five single
polygons from East Baton Rouge and one genuine multipolygon from Plaquemines.
Production asks for full resolution; the fixtures are generalised so they can be
read in a review.

The ACS values could not be recorded, because every data query now requires a
key. That fixture carries the documented response shape and real variable ids
with synthetic numbers, and it says so in its own `_note`.
"""

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from pipeline.adapters.census_acs import (
    ACS_URL,
    ACS_WINDOW,
    CREDENTIAL,
    CV_THRESHOLD,
    INDICATORS,
    JAM_CEILING,
    PULLED,
    RACE,
    SCORED,
    STATE_FIPS,
    TIGER_YEAR,
    VARIABLES_PER_REQUEST,
    VINTAGE,
    AcsVariable,
    CensusAcsAdapter,
    CensusTract,
    StateBoundary,
    TractEstimate,
    TractRaceEthnicity,
    bounds,
    chunks,
    geometry_fault,
    read_estimate,
    read_margin,
    rings_of,
    to_wkt,
)
from pipeline.context import RunContext
from pipeline.errors import RecordRejected
from pipeline.http import build_client
from pipeline.metadata import PullMetadata
from pipeline.policy import PartialFailurePolicy, SourcePolicy
from pipeline.records import Measurement
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from pipeline.snapshots import InMemorySnapshotStore, SnapshotStore
from tests.conftest import FakeClock, make_context, make_fetcher

FIXTURES = Path(__file__).parent / "fixtures" / "census_acs"

KEY = "fixture-key-not-a-real-credential"
FIPS = STATE_FIPS["LA"]

# The fixture is seven tracts, two of them deliberately unusable: one with a
# polygon and no estimates, one with estimates and no polygon. That is a 28%
# rejection rate, which the shipped one-percent tolerance would rightly refuse
# to load. `test_the_shipped_policy_stays_strict` guards the real one.
TEST_POLICY = SourcePolicy(
    rate_limit=CensusAcsAdapter.policy.rate_limit,
    partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
)

GEOMETRY_ONLY = "22033000500"
ACS_ONLY = "22071000100"
LOADED = (
    "22033000100",
    "22033000200",
    "22033000300",
    "22033000400",
    "22075050100",
)


def _values() -> dict[str, dict[str, list[str]]]:
    document = json.loads((FIXTURES / "acs_values.json").read_text())
    fill = document["fill"]
    tracts: dict[str, dict[str, list[str]]] = {}
    for geoid, overrides in document["tracts"].items():
        cells = {v.code: list(fill) for v in PULLED}
        cells.update({k: v for k, v in overrides.items() if not k.startswith("_")})
        tracts[geoid] = cells
    return tracts


def _tract_features() -> list[dict[str, object]]:
    return list(json.loads((FIXTURES / "tracts_page1.json").read_text())["features"])


def census_transport(
    *,
    fail: Iterable[str] = (),
    tract_features: list[dict[str, object]] | None = None,
    acs_body: str | None = None,
) -> httpx.MockTransport:
    """Serves the two services, honouring the query the adapter actually sends."""
    down = set(fail)
    features = _tract_features() if tract_features is None else tract_features
    tracts = _values()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        base = url.split("?")[0]
        if any(marker in url for marker in down):
            return httpx.Response(503)

        if base == ACS_URL:
            if acs_body is not None:
                return httpx.Response(200, text=acs_body)
            if request.url.params.get("key") != KEY:
                # What the live API does: a 302 to an HTML page, followed.
                return httpx.Response(200, text="<html><title>Invalid Key</title></html>")
            fields = request.url.params.get("get", "").split(",")
            header = [*fields, "state", "county", "tract"]
            rows: list[list[str]] = []
            for geoid, cells in tracts.items():
                row: list[str] = []
                for field in fields:
                    code, suffix = field[:-1], field[-1]
                    estimate, margin = cells.get(code, ["", ""])
                    row.append(estimate if suffix == "E" else margin)
                rows.append([*row, geoid[:2], geoid[2:5], geoid[5:]])
            return httpx.Response(200, text=json.dumps([header, *rows]))

        if base.endswith("/80/query"):
            return httpx.Response(200, text=(FIXTURES / "state_boundary.json").read_text())

        if base.endswith("/8/query"):
            offset = int(request.url.params.get("resultOffset", "0"))
            count = int(request.url.params.get("resultRecordCount", "200"))
            page = features[offset : offset + count]
            return httpx.Response(
                200, text=json.dumps({"type": "FeatureCollection", "features": page})
            )

        return httpx.Response(404)

    return httpx.MockTransport(handler)


@asynccontextmanager
async def census_context(
    sink: InMemorySink,
    *,
    transport: httpx.MockTransport | None = None,
    snapshots: SnapshotStore | None = None,
    clock: FakeClock | None = None,
    credentials: dict[str, str] | None = None,
) -> AsyncIterator[RunContext]:
    async with build_client(TEST_POLICY, transport=transport or census_transport()) as client:
        base = make_context(
            http=make_fetcher(
                client, source="census_acs", policy=TEST_POLICY, snapshots=snapshots, clock=clock
            ),
            sink=sink,
            policy=TEST_POLICY,
            source="census_acs",
        )
        yield replace(
            base,
            credentials=credentials if credentials is not None else {CREDENTIAL: KEY},
        )


async def run(sink: InMemorySink, **kwargs: object) -> PullMetadata:
    async with census_context(sink, **kwargs) as ctx:  # type: ignore[arg-type]
        return await run_adapter(CensusAcsAdapter(), ctx)


def estimates(sink: InMemorySink) -> dict[tuple[str, str], TractEstimate]:
    return {
        (r.tract_geoid, r.variable): r
        for r in sink.rows(TractEstimate.table)
        if isinstance(r, TractEstimate)
    }


def race_rows(sink: InMemorySink) -> dict[tuple[str, str], TractRaceEthnicity]:
    return {
        (r.tract_geoid, r.variable): r
        for r in sink.rows(TractRaceEthnicity.table)
        if isinstance(r, TractRaceEthnicity)
    }


def tracts(sink: InMemorySink) -> dict[str, CensusTract]:
    return {r.geoid: r for r in sink.rows(CensusTract.table) if isinstance(r, CensusTract)}


def gaps_text(result: PullMetadata) -> str:
    return " ".join(gap.detail for gap in result.known_gaps)


# ---- the declared variable set -----------------------------------------


def test_every_indicator_recipe_uses_variables_the_adapter_pulls() -> None:
    # A recipe naming a variable nobody fetched is an indicator that silently
    # never computes, which is worse than one that fails.
    scored = {v.code for v in SCORED}
    for indicator in INDICATORS:
        for code in indicator.numerator + indicator.denominator:
            assert code in scored, f"{indicator.id} names {code}, which is not pulled"


def test_no_indicator_recipe_reaches_a_race_variable() -> None:
    # Methodology section 14. This is the assertion the whole table split exists
    # to make possible, so it is worth stating twice: once here on the recipes,
    # and once below on what actually lands in the database.
    race = {v.code for v in RACE}
    for indicator in INDICATORS:
        used = set(indicator.numerator + indicator.denominator)
        assert not used & race, f"{indicator.id} reaches {sorted(used & race)}"


def test_the_scored_and_race_variable_sets_are_disjoint() -> None:
    assert not {v.code for v in SCORED} & {v.code for v in RACE}


def test_no_variable_is_pulled_twice() -> None:
    codes = [v.code for v in PULLED]
    assert len(codes) == len(set(codes))


def test_the_seven_social_indicators_are_all_declared() -> None:
    assert [i.id for i in INDICATORS] == ["S1", "S2", "P1", "P2", "P3", "P4", "P5"]


def test_every_pulled_variable_is_a_count() -> None:
    # The adapter deliberately pulls no rates or medians, which is what leaves
    # CS-106 able to obey section 7: interpolate numerator and denominator as
    # extensive quantities and derive the rate once at the end.
    assert all(variable.extensive for variable in PULLED)


def test_the_age_brackets_are_the_ones_that_were_verified() -> None:
    # These ranges were read off the live table on 2026-09-11 and are easy to
    # shift by one while editing. B01001_019 and _043 are the 62-to-64 brackets
    # and must stay out; _020 and _044 are the first 65-and-over brackets.
    codes = {v.code for v in PULLED}
    assert "B01001_020" in codes and "B01001_044" in codes
    assert "B01001_019" not in codes and "B01001_043" not in codes
    assert "B01001_025" in codes and "B01001_049" in codes
    assert "B01001_003" in codes and "B01001_027" in codes


def test_linguistic_isolation_takes_the_limited_household_not_its_complement() -> None:
    # C16002 lists the limited household first in each language block, so the
    # numerator is 004, 007, 010, 013. Reading the pattern off the table name
    # takes the complements and inverts the indicator.
    (p3,) = (i for i in INDICATORS if i.id == "P3")
    assert p3.numerator == ("C16002_004", "C16002_007", "C16002_010", "C16002_013")
    assert p3.denominator == ("C16002_001",)


def test_the_housing_burden_shortfall_is_declared_rather_than_hidden() -> None:
    # ACS publishes no low-income-by-over-50-percent cross tabulation at tract
    # level, so P5 cannot be what section 8.4 says it is. The deviation has to
    # be in the manifest, not only in a comment.
    (p5,) = (i for i in INDICATORS if i.id == "P5")
    assert "50" in p5.note
    static = " ".join(gap.detail for gap in CensusAcsAdapter().known_gaps(None))  # type: ignore[arg-type]
    assert "B25106" in static and "CHAS" in static


def test_the_variable_list_is_chunked_under_the_api_limit() -> None:
    batches = chunks(PULLED, VARIABLES_PER_REQUEST)
    assert sum(len(batch) for batch in batches) == len(PULLED)
    for batch in batches:
        # Each variable is requested as an estimate and a margin, and the API
        # caps `get=` at fifty.
        assert len(batch) * 2 <= 50


# ---- reading cells -----------------------------------------------------


def test_a_zero_estimate_is_an_observation() -> None:
    measurement = read_estimate("0")
    assert measurement.observed
    assert measurement.value == 0.0


def test_a_jam_value_is_an_absence_and_never_a_zero() -> None:
    for jam in ("-666666666", "-999999999", "-222222222", "-888888888", str(JAM_CEILING)):
        assert read_estimate(jam) == Measurement.absent()


def test_a_blank_cell_is_an_absence() -> None:
    assert read_estimate("") == Measurement.absent()
    assert read_margin("  ") == Measurement.absent()


def test_a_controlled_margin_is_zero_rather_than_unknown() -> None:
    # A controlled estimate was fixed to an independent population total, so it
    # has no sampling error. Storing that as unknown would make the most
    # certain input the pipeline has look like one of its least certain.
    margin = read_margin("-555555555")
    assert margin.observed
    assert margin.value == 0.0


def test_a_negative_margin_that_is_not_a_jam_value_is_rejected() -> None:
    assert read_margin("-4") == Measurement.absent()


def test_the_coefficient_of_variation_is_undefined_rather_than_infinite_at_zero() -> None:
    row = TractEstimate(
        tract_geoid="22033000100",
        acs_vintage=ACS_WINDOW,
        variable="C17002_002E",
        estimate=Measurement.of(0.0),
        margin_of_error=Measurement.of(13.0),
        is_extensive=True,
    )
    assert row.coefficient_of_variation is None


def test_the_coefficient_of_variation_divides_the_margin_by_the_confidence_factor() -> None:
    row = TractEstimate(
        tract_geoid="22033000100",
        acs_vintage=ACS_WINDOW,
        variable="C17002_002E",
        estimate=Measurement.of(40.0),
        margin_of_error=Measurement.of(90.0),
        is_extensive=True,
    )
    assert row.coefficient_of_variation == pytest.approx(90.0 / 1.645 / 40.0)
    assert row.coefficient_of_variation is not None
    assert row.coefficient_of_variation > CV_THRESHOLD


# ---- geometry ----------------------------------------------------------


def test_a_single_part_tract_is_still_stored_as_a_multipolygon() -> None:
    # census_tract.geom is typed MultiPolygon, so the common single-part case
    # cannot be stored as a different type on most rows.
    polygons = rings_of({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
    assert to_wkt(polygons).startswith("MULTIPOLYGON(((")


def test_a_real_multipart_tract_survives_the_conversion() -> None:
    feature = next(
        f
        for f in _tract_features()
        if f["geometry"]["type"] == "MultiPolygon"  # type: ignore[index]
    )
    polygons = rings_of(feature["geometry"])  # type: ignore[arg-type]
    assert len(polygons) > 1
    assert geometry_fault(polygons) is None
    assert to_wkt(polygons).count(")), ((") == len(polygons) - 1


def test_an_unclosed_ring_is_a_fault_rather_than_something_quietly_closed() -> None:
    # PostGIS refuses it, and closing it here would hide an upstream change of
    # shape behind a polygon that happens to load.
    polygons = rings_of({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]})
    assert geometry_fault(polygons) == "unclosed ring"


def test_a_degenerate_ring_is_a_fault() -> None:
    polygons = rings_of({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]})
    assert geometry_fault(polygons) == "ring with fewer than four positions"


def test_an_impossible_coordinate_is_a_fault() -> None:
    polygons = rings_of(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 91], [0, 91], [0, 0]]]}
    )
    assert geometry_fault(polygons) == "coordinate outside the world"


def test_an_unknown_geometry_type_is_not_silently_accepted() -> None:
    assert rings_of({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}) == ()
    assert geometry_fault(()) == "no geometry"


def _boundary() -> StateBoundary:
    document = json.loads((FIXTURES / "state_boundary.json").read_text())
    return StateBoundary(rings_of(document["features"][0]["geometry"]))


def test_the_state_boundary_places_known_points_correctly() -> None:
    boundary = _boundary()
    assert boundary.contains(-91.187, 30.451)  # Baton Rouge
    assert boundary.contains(-90.071, 29.951)  # New Orleans
    assert not boundary.contains(-95.369, 29.760)  # Houston
    assert not boundary.contains(-90.000, 25.000)  # open Gulf
    assert not boundary.contains(-91.000, 34.000)  # Arkansas


def test_every_recorded_tract_internal_point_falls_inside_the_state() -> None:
    boundary = _boundary()
    for feature in _tract_features():
        properties = feature["properties"]
        assert isinstance(properties, dict)
        longitude = float(properties["INTPTLON"])
        latitude = float(properties["INTPTLAT"])
        assert boundary.contains(longitude, latitude), properties["GEOID"]


def test_the_banded_index_agrees_with_an_unindexed_ray_cast() -> None:
    """The band lookup is an optimisation, so it has to be invisible.

    Bucketing edges by latitude is the difference between two milliseconds and
    half a minute over a state, and an off-by-one in the band arithmetic would
    misplace only the tracts near a band edge, which no single spot check would
    catch.
    """
    document = json.loads((FIXTURES / "state_boundary.json").read_text())
    polygons = rings_of(document["features"][0]["geometry"])
    boundary = StateBoundary(polygons)
    edges = [
        (ring[i][0], ring[i][1], ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1])
        for polygon in polygons
        for ring in polygon
        for i in range(len(ring))
    ]

    def naive(longitude: float, latitude: float) -> bool:
        crossings = 0
        for x1, y1, x2, y2 in edges:
            if (y1 > latitude) != (y2 > latitude):
                if x1 + (latitude - y1) * (x2 - x1) / (y2 - y1) > longitude:
                    crossings += 1
        return crossings % 2 == 1

    west, south, east, north = bounds(polygons)
    steps = 40
    for row in range(steps + 1):
        for column in range(steps + 1):
            longitude = west + (east - west) * column / steps
            latitude = south + (north - south) * row / steps
            assert boundary.contains(longitude, latitude) == naive(longitude, latitude), (
                longitude,
                latitude,
            )


# ---- a clean pull ------------------------------------------------------


async def test_a_clean_pull_loads_every_usable_tract(sink: InMemorySink) -> None:
    result = await run(sink)

    assert result.status == "partial"
    assert set(tracts(sink)) == set(LOADED)
    assert tracts(sink)["22033000100"].tiger_year == TIGER_YEAR


async def test_the_vintage_is_the_release_and_not_the_download_date(sink: InMemorySink) -> None:
    result = await run(sink)

    assert result.vintage == VINTAGE
    assert VINTAGE == "acs5_2020_2024"
    # The column that keys the rows follows the schema's own spelling.
    assert all(row.acs_vintage == ACS_WINDOW for row in estimates(sink).values())
    assert ACS_WINDOW == "2020-2024"


async def test_every_declared_variable_reaches_its_own_table(sink: InMemorySink) -> None:
    await run(sink)

    assert len(estimates(sink)) == len(SCORED) * len(LOADED)
    assert len(race_rows(sink)) == len(RACE) * len(LOADED)


async def test_a_variable_the_release_omitted_is_stored_absent_rather_than_skipped(
    sink: InMemorySink,
) -> None:
    # So a reader can tell "the survey had nothing to say about this tract" from
    # "nobody asked for it".
    await run(sink)

    row = estimates(sink)[("22075050100", "B23025_005E")]
    assert row.estimate == Measurement.absent()
    assert row.margin_of_error == Measurement.absent()


async def test_a_zero_count_is_loaded_as_an_observed_zero(sink: InMemorySink) -> None:
    await run(sink)

    row = estimates(sink)[("22033000200", "C16002_004E")]
    assert row.estimate.observed
    assert row.estimate.value == 0.0


async def test_a_jam_value_is_loaded_as_an_absence(sink: InMemorySink) -> None:
    await run(sink)

    row = estimates(sink)[("22033000300", "B15003_002E")]
    assert not row.estimate.observed
    assert row.estimate.value is None


async def test_a_controlled_estimate_keeps_a_zero_margin(sink: InMemorySink) -> None:
    await run(sink)

    row = estimates(sink)[("22033000100", "B01003_001E")]
    assert row.estimate.value == 1200.0
    assert row.margin_of_error.value == 0.0
    assert row.coefficient_of_variation == 0.0


async def test_every_loaded_row_is_marked_extensive(sink: InMemorySink) -> None:
    await run(sink)

    assert all(row.is_extensive for row in estimates(sink).values())
    assert all(row.is_extensive for row in race_rows(sink).values())


# ---- uncertainty -------------------------------------------------------


async def test_a_high_variation_estimate_is_loaded_and_not_dropped(sink: InMemorySink) -> None:
    """The acceptance criterion, and the reason for it.

    Dropping high-uncertainty estimates preferentially removes small and rural
    populations, which are the populations the project exists to see. The cost
    goes to c_spatial instead, where it is visible.
    """
    result = await run(sink)

    row = estimates(sink)[("22033000400", "C17002_002E")]
    assert row.estimate.value == 40.0
    assert row.coefficient_of_variation is not None
    assert row.coefficient_of_variation > CV_THRESHOLD
    assert "coefficient of variation above 0.30" in gaps_text(result)


async def test_the_margin_travels_with_every_estimate(sink: InMemorySink) -> None:
    await run(sink)

    rows = estimates(sink)
    assert rows[("22033000200", "C16002_004E")].margin_of_error.value == 13.0
    # Which is what makes the confidence term computable at all.
    assert all(hasattr(row, "coefficient_of_variation") for row in rows.values())


async def test_the_manifest_counts_the_high_variation_estimates(sink: InMemorySink) -> None:
    result = await run(sink)

    assert any("coefficient of variation" in gap.detail for gap in result.known_gaps)
    assert any("never as zero" in gap.detail for gap in result.known_gaps)


# ---- race and ethnicity, section 14 ------------------------------------


async def test_race_variables_never_land_in_the_scored_table(sink: InMemorySink) -> None:
    """Section 14, enforced where it can actually be checked.

    The score's claim to evidence is that nothing in its construction reached
    for racial composition. A race variable in tract_demographics would put it
    one careless `WHERE variable LIKE` away from the arithmetic.
    """
    await run(sink)

    race_codes = {v.estimate_field for v in RACE}
    assert not {variable for _, variable in estimates(sink)} & race_codes


async def test_the_race_table_holds_what_the_scored_table_must_not(sink: InMemorySink) -> None:
    await run(sink)

    stored = {variable for _, variable in race_rows(sink)}
    assert "B03002_004E" in stored  # not Hispanic, Black alone
    assert "B03002_012E" in stored  # Hispanic or Latino
    assert "B02001_003E" in stored  # Black alone, any ethnicity
    assert stored == {v.estimate_field for v in RACE}


async def test_the_two_tables_are_written_separately(sink: InMemorySink) -> None:
    await run(sink)

    assert TractEstimate.table == "tract_demographics"
    assert TractRaceEthnicity.table == "tract_race_ethnicity"
    assert TractEstimate.table in sink.tables
    assert TractRaceEthnicity.table in sink.tables


def test_a_race_row_is_not_an_instance_of_a_scored_row() -> None:
    # They are siblings rather than one deriving from the other, so a future
    # `isinstance(row, TractEstimate)` filter cannot pick up a race row.
    row = TractRaceEthnicity(
        tract_geoid="22033000100",
        acs_vintage=ACS_WINDOW,
        variable="B03002_004E",
        estimate=Measurement.of(1.0),
        margin_of_error=Measurement.of(1.0),
        is_extensive=True,
    )
    assert not isinstance(row, TractEstimate)


async def test_the_race_separation_is_explained_in_the_manifest(sink: InMemorySink) -> None:
    result = await run(sink)

    assert "tract_race_ethnicity" in gaps_text(result)
    assert "section 13.6" in gaps_text(result).lower() or "13.6" in gaps_text(result)


# ---- rejections --------------------------------------------------------


async def test_a_tract_with_no_estimates_is_rejected_and_counted(sink: InMemorySink) -> None:
    result = await run(sink)

    assert GEOMETRY_ONLY not in tracts(sink)
    assert any(r.record_id == GEOMETRY_ONLY for r in result.rejections)
    assert f"no {ACS_WINDOW} estimates for the tract" in result.rejection_reasons


async def test_a_tract_with_no_geometry_is_rejected_and_counted(sink: InMemorySink) -> None:
    result = await run(sink)

    assert ACS_ONLY not in tracts(sink)
    assert any(r.record_id == ACS_ONLY for r in result.rejections)
    assert "no geometry" in result.rejection_reasons


async def test_both_kinds_of_mismatch_reach_the_manifest(sink: InMemorySink) -> None:
    result = await run(sink)

    assert result.counts.rejected == 2
    assert result.counts.fetched == 6 + 1
    assert "with no geometry" in gaps_text(result)


async def test_a_tract_outside_the_state_boundary_is_rejected(sink: InMemorySink) -> None:
    """The acceptance criterion is the boundary, not a bounding box.

    A tract placed in Houston is inside Louisiana's bounding box on the
    longitude axis and nowhere near the state, which is exactly the case a box
    check waves through.
    """
    features = _tract_features()
    # A tract that does have estimates, moved to Houston, so the boundary check
    # is what rejects it rather than an earlier check firing first.
    stray = json.loads(json.dumps(features))
    stray[0]["properties"]["INTPTLAT"] = "+29.7604000"
    stray[0]["properties"]["INTPTLON"] = "-095.3698000"
    moved = stray[0]["properties"]["GEOID"]

    adapter = CensusAcsAdapter()
    async with census_context(sink, transport=census_transport(tract_features=stray)) as ctx:
        fetched = await adapter.fetch(ctx)
    (profile,) = (p for p in fetched.records if p.geoid == moved)

    assert profile.has_acs
    assert not profile.inside_state
    with pytest.raises(RecordRejected, match="outside the state boundary"):
        adapter.validate(profile, ctx)


async def test_an_unusable_geometry_is_rejected_with_its_reason(sink: InMemorySink) -> None:
    features = json.loads(json.dumps(_tract_features()))
    features[0]["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[-91.1, 30.5], [-91.0, 30.6]]],
    }
    broken = features[0]["properties"]["GEOID"]

    adapter = CensusAcsAdapter()
    async with census_context(sink, transport=census_transport(tract_features=features)) as ctx:
        fetched = await adapter.fetch(ctx)
    (profile,) = (p for p in fetched.records if p.geoid == broken)

    assert profile.has_acs
    with pytest.raises(RecordRejected, match="fewer than four positions"):
        adapter.validate(profile, ctx)


# ---- the credential ----------------------------------------------------


async def test_a_missing_key_fails_the_run_rather_than_going_stale(sink: InMemorySink) -> None:
    """A missing credential is a misconfiguration, not an unavailable upstream.

    Falling back to last night's snapshot would hide a broken deployment behind
    a `stale` run that looks survivable.
    """
    result = await run(sink, credentials={})

    assert result.status == "failed"
    assert result.counts.loaded == 0
    assert any(CREDENTIAL in note for note in result.notes)
    assert any("key_signup" in note for note in result.notes)


async def test_a_rejected_key_is_named_as_such(sink: InMemorySink) -> None:
    result = await run(sink, credentials={CREDENTIAL: "wrong"})

    assert result.status == "failed"
    assert any("rejected as invalid" in note for note in result.notes)


async def test_the_key_never_reaches_an_artifact_or_the_manifest(sink: InMemorySink) -> None:
    """`Artifact.url` is published verbatim in docs/provenance.md.

    The ACS API takes its key only as a query parameter, and it takes no header
    form, so keeping it out of the recorded URL is the whole of the defence.
    """
    result = await run(sink)

    assert result.artifacts
    assert not any(KEY in artifact.url for artifact in result.artifacts)
    assert KEY not in result.model_dump_json()
    assert any(artifact.url.startswith(ACS_URL) for artifact in result.artifacts)


async def test_the_recorded_url_still_identifies_what_was_asked_for(sink: InMemorySink) -> None:
    # Provenance a reader can act on: the URL is the real query, so adding your
    # own key to it reproduces the pull.
    result = await run(sink)

    acs = [a.url for a in result.artifacts if a.url.startswith(ACS_URL)]
    assert acs
    assert all("get=" in url and f"in=state:{FIPS}" in url for url in acs)


# ---- requests, paging and the stale fallback ---------------------------


async def test_each_variable_chunk_is_a_distinct_url(sink: InMemorySink) -> None:
    """Which is what makes the stale fallback correct.

    The snapshot store is keyed by request URL. Chunks that shared one would
    overwrite each other, and a later unavailable-upstream night would replay a
    single chunk's response for every chunk.
    """
    async with census_context(sink) as ctx:
        await CensusAcsAdapter().fetch(ctx)

    acs = [url for url in ctx.http.urls if url.startswith(ACS_URL)]
    assert len(acs) == len(chunks(PULLED, VARIABLES_PER_REQUEST))
    assert len(set(acs)) == len(acs)


async def test_geometry_is_paged_and_stops_on_a_short_page(
    sink: InMemorySink, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pipeline.adapters.census_acs.GEOMETRY_PAGE_SIZE", 2)

    async with census_context(sink) as ctx:
        result = await CensusAcsAdapter().fetch(ctx)

    pages = [u for u in ctx.http.urls if "/8/query" in u]
    # Six features at two per page: three full pages, then a fourth that is empty.
    assert len(pages) == 4
    assert len(set(pages)) == 4
    assert len({p.geoid for p in result.records}) == 7


async def test_an_unavailable_upstream_serves_the_last_good_snapshot(
    sink: InMemorySink, snapshots: InMemorySnapshotStore, clock: FakeClock
) -> None:
    first = await run(sink, snapshots=snapshots, clock=clock)
    assert first.status == "partial"

    second = await run(
        sink,
        snapshots=snapshots,
        clock=clock,
        transport=census_transport(fail={"api.census.gov", "tigerweb.geo.census.gov"}),
    )

    assert second.status == "stale"
    assert all(artifact.from_snapshot for artifact in second.artifacts)
    # And the replay is per chunk, not one chunk repeated: every variable is
    # back, with the values the first run saw.
    assert set(tracts(sink)) == set(LOADED)


async def test_the_snapshot_replay_returns_every_chunk_and_not_just_the_last(
    sink: InMemorySink, snapshots: InMemorySnapshotStore, clock: FakeClock
) -> None:
    await run(sink, snapshots=snapshots, clock=clock)
    fresh = InMemorySink()

    stale = await run(
        fresh,
        snapshots=snapshots,
        clock=clock,
        transport=census_transport(fail={"api.census.gov", "tigerweb.geo.census.gov"}),
    )

    assert stale.status == "stale"
    assert len(estimates(fresh)) == len(SCORED) * len(LOADED)
    assert estimates(fresh)[("22033000100", "B01003_001E")].estimate.value == 1200.0


# ---- upstream shape changes --------------------------------------------


async def test_a_response_that_is_not_the_documented_shape_fails_permanently(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=census_transport(acs_body=json.dumps({"Results": []})))

    assert result.status == "failed"
    assert any("not a non-empty array" in note for note in result.notes)


async def test_a_row_narrower_than_the_header_is_not_read_by_position(
    sink: InMemorySink,
) -> None:
    # Silently zipping a short row against the header would attach one
    # variable's value to the next variable's id for the rest of the row.
    body = json.dumps([["B01003_001E", "B01003_001M", "state", "county", "tract"], ["1", "2"]])
    result = await run(sink, transport=census_transport(acs_body=body))

    assert result.status == "failed"
    assert any("does not match the header width" in note for note in result.notes)


async def test_a_row_naming_no_tract_is_counted_rather_than_dropped_quietly(
    sink: InMemorySink,
) -> None:
    # There is no record to reject, because the row names no tract, so the loss
    # would otherwise leave no trace at all. It is also counted once rather
    # than once per variable chunk.
    body = json.dumps(
        [
            ["B01003_001E", "B01003_001M", "state", "county", "tract"],
            ["1", "2", "22", "033", ""],
        ]
    )
    result = await run(sink, transport=census_transport(acs_body=body))

    assert any("no eleven-digit tract GEOID" in note for note in result.notes)
    assert any("1 ACS rows" in note for note in result.notes)


async def test_a_state_with_no_tracts_fails_rather_than_loading_nothing(
    sink: InMemorySink,
) -> None:
    result = await run(sink, transport=census_transport(tract_features=[]))

    assert result.status == "failed"
    assert any("returned no tracts" in note for note in result.notes)


# ---- the shipped configuration -----------------------------------------


def test_the_shipped_policy_stays_strict() -> None:
    # The fixture needs a loose tolerance; production must not inherit it.
    shipped = CensusAcsAdapter.policy
    assert shipped.partial_failure.max_reject_fraction == 0.01
    assert shipped.stale_fallback
    # Two requests a second: the API publishes no limit and TIGERweb sits behind
    # a firewall that has already refused one query.
    assert shipped.rate_limit.requests_per_second == 2.0
    # A geometry page is about five megabytes.
    assert shipped.request_timeout_s == 90.0


def test_the_adapter_describes_what_it_feeds() -> None:
    spec = CensusAcsAdapter.spec
    assert spec.name == "census_acs"
    assert spec.provides == ("S1", "S2", "P1", "P2", "P3", "P4", "P5")
    # Race and ethnicity are pulled and are deliberately not advertised as
    # feeding an indicator, because they feed none.
    assert "B03002" not in " ".join(spec.provides)
    assert spec.native_geography == "census tract"


def test_the_variable_declarations_carry_their_labels() -> None:
    # The drill-down panel and the provenance page both name variables to a
    # reader, so an unlabelled one is one nobody can check.
    assert all(isinstance(v, AcsVariable) and v.label for v in PULLED)
