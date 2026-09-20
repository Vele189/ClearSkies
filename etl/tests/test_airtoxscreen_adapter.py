"""EPA AirToxScreen adapter, against workbooks built in the test. No network.

The real files are 62 MB and 43 MB, so the fixture is generated rather than
recorded: `workbook` writes a genuine .xlsx, shared strings and all, with the
column names and the row shapes the live files actually have. The numbers are
chosen so the identity this adapter checks — the pollutant columns sum to the
printed total, once that sum is rounded to one significant figure — holds for
every good row and is broken deliberately in exactly one.
"""

import io
import zipfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from xml.sax.saxutils import escape

import httpx
import pytest

from pipeline.adapters.airtoxscreen import (
    CANCER_URL,
    RELEASE_YEAR,
    RESPIRATORY_URL,
    AirToxScreenAdapter,
    HexExposure,
    TractExposure,
    one_significant_figure,
)
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError
from pipeline.http import build_client
from pipeline.interpolate import Crosswalk, Overlap, StaticCrosswalk
from pipeline.metadata import PullMetadata
from pipeline.policy import PartialFailurePolicy, SourcePolicy
from pipeline.records import Measurement
from pipeline.runner import run_adapter
from pipeline.sinks import InMemorySink
from tests.conftest import FIXED_NOW, make_context, make_fetcher

SOURCE = "airtoxscreen"

# The fixture carries three deliberately bad tracts out of nine, which the
# production tolerance would rightly refuse. Tests relax their own copy;
# `test_the_shipped_policy_stays_strict` guards the real one.
TEST_POLICY = SourcePolicy(
    rate_limit=AirToxScreenAdapter.policy.rate_limit,
    partial_failure=PartialFailurePolicy(max_reject_fraction=0.5, min_records=1),
)


# ---- a real .xlsx, built here ------------------------------------------

SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOC_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml"


def _letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def workbook(rows: Sequence[Sequence[object]]) -> bytes:
    """A single-sheet .xlsx with text in the shared string table, as EPA's are."""
    strings: list[str] = []
    seen: dict[str, int] = {}
    body: list[str] = []

    for row_number, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column, value in enumerate(row):
            if value is None:
                continue
            reference = f"{_letters(column)}{row_number}"
            if isinstance(value, str):
                if value not in seen:
                    seen[value] = len(strings)
                    strings.append(value)
                cells.append(f'<c r="{reference}" t="s"><v>{seen[value]}</v></c>')
            else:
                cells.append(f'<c r="{reference}"><v>{value!r}</v></c>')
        body.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared = "".join(f"<si><t>{escape(text)}</t></si>" for text in strings)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<?xml version="1.0"?><Types xmlns="{PACKAGE_NS}">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{DOC_TYPE}.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" '
            f'ContentType="{DOC_TYPE}.worksheet+xml"/>'
            f'<Override PartName="/xl/sharedStrings.xml" '
            f'ContentType="{DOC_TYPE}.sharedStrings+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{RELS_NS}/package">'
            f'<Relationship Id="rId1" Type="{RELS_NS}/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0"?><workbook xmlns="{SHEET_NS}" xmlns:r="{RELS_NS}">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{RELS_NS}/package">'
            f'<Relationship Id="rId1" Type="{RELS_NS}/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<?xml version="1.0"?><sst xmlns="{SHEET_NS}" count="{len(strings)}" '
            f'uniqueCount="{len(strings)}">{shared}</sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<?xml version="1.0"?><worksheet xmlns="{SHEET_NS}"><sheetData>'
            f"{''.join(body)}</sheetData></worksheet>",
        )
    return buffer.getvalue()


# ---- the fixture -------------------------------------------------------
#
# Column names are the live ones. Pollutant values are chosen so each good row's
# sum rounds to its printed total at one significant figure, which is the
# identity `_screen` checks.

CANCER_HEADER = [
    "State",
    "EPA Region",
    "County",
    "FIPS",
    "Tract",
    "Population",
    "Total Cancer Risk (per million)",
    "1,3-BUTADIENE",
    "BENZENE",
    "FORMALDEHYDE",
]

RESPIRATORY_HEADER = [
    "State",
    "EPA Region",
    "County",
    "FIPS",
    "Tract",
    "Population",
    "Total Respiratory (hazard quotient)",
    "ACROLEIN",
    "FORMALDEHYDE",
]

# geoid -> (population, three pollutant values). Sums: 24.34, 44.68, 29.35.
GOOD_TRACTS = {
    "22001960100": (6213, (10.0, 8.0, 6.34)),
    "22071004401": (2400, (20.0, 15.0, 9.68)),
    "22055001300": (5988, (12.0, 10.0, 7.35)),
}
PRINTED_CANCER = {"22001960100": 20, "22071004401": 40, "22055001300": 30}


def cancer_rows() -> list[Sequence[object]]:
    rows: list[Sequence[object]] = [
        CANCER_HEADER,
        # The rollups the live file interleaves with real tracts. Loading the
        # first of these as a census tract would put the entire United States in
        # Louisiana.
        ["US", "Entire US", "Entire US", "00000", "00000000000", 312566557, 30, 1.0, 1.0, 1.0],
        ["LA", "EPA Region 6", "Entire State", "22000", "22000000000", 4533197, 30, 1.0, 1.0, 1.0],
        ["LA", "EPA Region 6", "Acadia", "22001", "22001000000", 61773, 20, 1.0, 1.0, 1.0],
        # A neighbouring state, which the pilot filter drops.
        ["TX", "EPA Region 6", "Harris", "48201", "48201100000", 3200, 50, 20.0, 20.0, 8.0],
    ]
    for geoid, (population, pollutants) in GOOD_TRACTS.items():
        rows.append(
            [
                "LA",
                "EPA Region 6",
                "Acadia",
                geoid[:5],
                geoid,
                population,
                PRINTED_CANCER[geoid],
                *pollutants,
            ]
        )
    # Three unusable rows, each broken in one way.
    rows.append(
        # Sum is 100.0, printed total says 20. Upstream has changed which columns
        # the total is made of, and summing them anyway would publish a number
        # nobody could reproduce from the file.
        ["LA", "EPA Region 6", "Acadia", "22001", "22001960200", 900, 20, 50.0, 30.0, 20.0]
    )
    rows.append(
        # A tract code that is not eleven digits.
        ["LA", "EPA Region 6", "Acadia", "22001", "2200196030", 900, 20, 10.0, 8.0, 6.34]
    )
    rows.append(
        # Says Louisiana, carries a Mississippi GEOID. The two disagree, so the
        # value is not attributed to a Louisiana hexagon on the strength of the
        # two-letter code.
        ["LA", "EPA Region 6", "Hancock", "28045", "28045030100", 900, 20, 10.0, 8.0, 6.34]
    )
    return rows


def respiratory_rows() -> list[Sequence[object]]:
    rows: list[Sequence[object]] = [
        RESPIRATORY_HEADER,
        ["US", "Entire US", "Entire US", "00000", "00000000000", 312566557, 0.3, 0.2, 0.1],
    ]
    # 22055001300 is deliberately absent from this file: a tract EPA modelled for
    # cancer risk and not for respiratory hazard is absent in E2, not zero in it.
    for geoid, printed, values in (
        ("22001960100", 0.3, (0.2, 0.08174)),
        ("22071004401", 0.5, (0.35, 0.150744)),
    ):
        population = GOOD_TRACTS[geoid][0]
        rows.append(
            ["LA", "EPA Region 6", "Acadia", geoid[:5], geoid, population, printed, *values]
        )
    return rows


def transport(
    *, cancer: bytes | None = None, respiratory: bytes | None = None, fail: set[str] | None = None
) -> httpx.MockTransport:
    down = fail or set()
    bodies = {
        CANCER_URL: cancer if cancer is not None else workbook(cancer_rows()),
        RESPIRATORY_URL: respiratory if respiratory is not None else workbook(respiratory_rows()),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url in down:
            return httpx.Response(503)
        body = bodies.get(url)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body, headers={"Content-Type": DOC_TYPE + ".sheet"})

    return httpx.MockTransport(handler)


@asynccontextmanager
async def context(
    sink: InMemorySink, mock: httpx.MockTransport | None = None
) -> AsyncIterator[RunContext]:
    async with build_client(TEST_POLICY, transport=mock or transport()) as client:
        yield make_context(
            http=make_fetcher(client, source=SOURCE, policy=TEST_POLICY),
            sink=sink,
            policy=TEST_POLICY,
            source=SOURCE,
        )


async def run(
    sink: InMemorySink,
    *,
    mock: httpx.MockTransport | None = None,
    crosswalk: Crosswalk | None = None,
) -> PullMetadata:
    async with context(sink, mock) as ctx:
        return await run_adapter(AirToxScreenAdapter(crosswalk), ctx)


def tracts(sink: InMemorySink) -> dict[str, TractExposure]:
    return {
        row.tract_geoid: row
        for row in sink.rows(TractExposure.table)
        if isinstance(row, TractExposure)
    }


def hexes(sink: InMemorySink) -> dict[str, HexExposure]:
    return {row.h3: row for row in sink.rows(HexExposure.table) if isinstance(row, HexExposure)}


def gaps_text(result: PullMetadata) -> str:
    return " ".join(gap.detail for gap in result.known_gaps)


@pytest.fixture
async def loaded(sink: InMemorySink) -> AsyncIterator[tuple[PullMetadata, InMemorySink]]:
    yield await run(sink), sink


# ---- the contract ------------------------------------------------------


async def test_the_adapter_is_registered_and_lists_the_indicators_it_feeds() -> None:
    from pipeline.adapters import get, names

    assert SOURCE in names()
    spec = get(SOURCE).spec
    assert spec.provides == ("E1", "E2")
    assert spec.native_geography.startswith("census tract")


async def test_a_pull_loads_one_row_per_pilot_state_tract(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert result.ok
    assert set(tracts(sink)) == set(GOOD_TRACTS)


async def test_the_natural_key_makes_a_second_pull_idempotent(sink: InMemorySink) -> None:
    await run(sink)
    await run(sink)

    assert sink.count(TractExposure.table) == len(GOOD_TRACTS)


# ---- the rounded total, which is the whole reason for the pollutant sum --


def test_one_significant_figure_matches_how_epa_prints_the_total() -> None:
    # The four cases the live file exercises, including a value that rounds down
    # from just under the midpoint and one that rounds up from just over.
    assert one_significant_figure(24.340040295728155) == 20
    assert one_significant_figure(29.347477197759204) == 30
    assert one_significant_figure(44.681120351339544) == 40
    assert one_significant_figure(189.304432923995) == 200
    assert one_significant_figure(0.28174202982274) == 0.3
    assert one_significant_figure(0.0) == 0.0


async def test_e1_is_the_pollutant_sum_and_not_the_printed_total(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """The finding that decides whether E1 carries any information at all.

    The printed total takes ten distinct values across the pilot state, so
    ranking it (section 9) would collapse Louisiana into ten ties. These three
    tracts print 20, 40 and 30 and differ in the third significant figure.
    """
    _, sink = loaded
    loaded_tracts = tracts(sink)

    assert loaded_tracts["22001960100"].cancer_risk_per_million == Measurement.of(24.34)
    assert loaded_tracts["22071004401"].cancer_risk_per_million == Measurement.of(44.68)
    assert loaded_tracts["22055001300"].cancer_risk_per_million == Measurement.of(29.35)

    values = {row.cancer_risk_per_million.value for row in loaded_tracts.values()}
    printed = set(PRINTED_CANCER.values())
    assert values.isdisjoint(printed)


async def test_a_tract_whose_columns_disagree_with_its_total_is_rejected(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert "22001960200" not in tracts(sink)
    assert "pollutant columns disagree with the published total" in result.rejection_reasons


# ---- grain, geography and shape ----------------------------------------


async def test_rollup_rows_are_skipped_rather_than_rejected(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """A US total is a different grain, not a bad record.

    Counting the live file's 3,277 rollups as losses would exhaust the
    partial-failure tolerance every night on a pull that is entirely healthy.
    """
    result, sink = loaded

    assert not any(geoid.endswith("000000") for geoid in tracts(sink))
    assert "rollup rows" in " ".join(result.notes)
    assert result.counts.rejected == 3


async def test_a_tract_in_another_state_never_reaches_the_sink(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    _, sink = loaded

    assert not any(geoid.startswith("48") for geoid in tracts(sink))


async def test_a_geoid_that_contradicts_its_state_column_is_rejected(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert "28045030100" not in tracts(sink)
    assert "tract geoid outside the pilot state" in result.rejection_reasons


async def test_a_malformed_geoid_is_rejected(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded

    assert "malformed tract geoid" in result.rejection_reasons


async def test_a_lost_column_fails_the_run_rather_than_loading_something_else(
    sink: InMemorySink,
) -> None:
    header = [name for name in CANCER_HEADER if name != "Tract"]
    rows: list[Sequence[object]] = [
        header,
        ["LA", "EPA Region 6", "Acadia", "22001", 6213, 20, 1.0],
    ]

    result = await run(sink, mock=transport(cancer=workbook(rows)))

    assert result.status == "failed"
    assert sink.count(TractExposure.table) == 0


async def test_a_file_with_only_the_rounded_total_is_refused(sink: InMemorySink) -> None:
    # Without per-pollutant columns the only number left is the ten-valued one,
    # and continuing on it would silently replace the indicator.
    header = CANCER_HEADER[:7]
    rows: list[Sequence[object]] = [
        header,
        ["LA", "EPA Region 6", "Acadia", "22001", "22001960100", 1, 20],
    ]

    result = await run(sink, mock=transport(cancer=workbook(rows)))

    assert result.status == "failed"


async def test_something_that_is_not_a_workbook_is_a_permanent_error(sink: InMemorySink) -> None:
    result = await run(sink, mock=transport(cancer=b"<html>404</html>"))

    assert result.status == "failed"


def test_the_reader_refuses_an_archive_with_no_worksheet() -> None:
    from pipeline.adapters.airtoxscreen import read_sheet

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")

    with pytest.raises(PermanentSourceError, match="no worksheet"):
        read_sheet(buffer.getvalue(), "test://book.xlsx")


# ---- missing is not zero -----------------------------------------------


async def test_a_tract_absent_from_one_file_is_absent_there_not_zero(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """22055001300 has a modeled cancer risk and no modeled respiratory hazard."""
    result, sink = loaded
    row = tracts(sink)["22055001300"]

    assert row.cancer_risk_per_million == Measurement.of(29.35)
    assert row.respiratory_hazard_index == Measurement.absent()
    assert row.respiratory_hazard_index.value is None
    assert "disagree on coverage" in " ".join(result.notes)


# ---- vintage ------------------------------------------------------------


async def test_the_vintage_is_the_model_release_not_the_download_date(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    """CS-103: the recency term has to see how old the emissions inventory is."""
    result, sink = loaded

    assert result.vintage == str(RELEASE_YEAR)
    assert str(FIXED_NOW.year) not in result.vintage
    assert {row.vintage_year for row in tracts(sink).values()} == {RELEASE_YEAR}


async def test_the_pull_says_the_emissions_inventory_is_older_than_the_release(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, _ = loaded
    text = gaps_text(result)

    assert "National Emissions Inventory" in text
    assert "no downloadable tract-level file" in text


async def test_the_census_vintage_mismatch_is_declared(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    assert "2010 census geography" in gaps_text(loaded[0])


# ---- the section 7 mapping ---------------------------------------------


def grid() -> StaticCrosswalk:
    """Two hexes over the fixture's tracts, one empty, one unpopulated.

    h1 draws on two tracts with very different populations, so a mean that
    ignored the weights would be visibly wrong. h2 draws on one. h3 overlaps
    nothing. h4 overlaps a tract with no population in it.
    """
    return StaticCrosswalk(
        cells=("h1", "h2", "h3", "h4"),
        rows=(
            Overlap("22001960100", "h1", population=6000.0, pop_weight=0.97),
            Overlap("22071004401", "h1", population=2000.0, pop_weight=0.83),
            Overlap("22055001300", "h2", population=5988.0, pop_weight=1.0),
            Overlap("22001960100", "h4", population=0.0, pop_weight=0.0),
        ),
    )


async def test_without_a_grid_no_hexagon_is_claimed_and_the_pull_says_so(
    loaded: tuple[PullMetadata, InMemorySink],
) -> None:
    result, sink = loaded

    assert sink.count(HexExposure.table) == 0
    assert "No hex grid was supplied" in gaps_text(result)
    assert "CS-007" in gaps_text(result)


async def test_every_hex_receives_a_value_or_a_counted_absence(sink: InMemorySink) -> None:
    """CS-103's third acceptance criterion, stated as an assertion."""
    result = await run(sink, crosswalk=grid())
    mapped = hexes(sink)

    assert set(mapped) == {"h1", "h2", "h3", "h4"}
    for row in mapped.values():
        cancer_known = row.cancer_risk_per_million.observed
        assert cancer_known != (row.cancer_risk_absence is not None)
    assert "E1 mapping: 2 of 4 hexes received a value" in " ".join(result.notes)


async def test_a_hex_value_is_the_population_weighted_mean_of_its_tracts(
    sink: InMemorySink,
) -> None:
    """(24.34 * 6000 + 44.68 * 2000) / 8000 = 29.425.

    The unweighted mean is 34.51 and an area-weighted one would be different
    again. Both are wrong in the direction section 7 opens by rejecting.
    """
    await run(sink, crosswalk=grid())

    h1 = hexes(sink)["h1"]

    assert h1.cancer_risk_per_million.value == pytest.approx(29.425)
    assert h1.tract_count == 2
    assert h1.population == 8000.0


async def test_a_hex_with_no_overlapping_tract_carries_the_reason(sink: InMemorySink) -> None:
    await run(sink, crosswalk=grid())

    h3 = hexes(sink)["h3"]

    assert h3.cancer_risk_per_million == Measurement.absent()
    assert h3.cancer_risk_absence == "no_overlapping_source"
    assert h3.respiratory_hazard_absence == "no_overlapping_source"


async def test_an_unpopulated_hex_is_absent_rather_than_area_averaged(
    sink: InMemorySink,
) -> None:
    await run(sink, crosswalk=grid())

    h4 = hexes(sink)["h4"]

    assert h4.cancer_risk_absence == "no_population"
    assert h4.cancer_risk_per_million.value is None


async def test_a_hex_whose_tracts_lack_the_indicator_is_absent_for_that_one(
    sink: InMemorySink,
) -> None:
    # h2 draws only on 22055001300, which the respiratory file does not carry.
    await run(sink, crosswalk=grid())

    h2 = hexes(sink)["h2"]

    assert h2.cancer_risk_per_million == Measurement.of(29.35)
    assert h2.respiratory_hazard_index == Measurement.absent()
    assert h2.respiratory_hazard_absence == "no_source_value"


async def test_a_tract_the_crosswalk_does_not_know_is_counted_not_dropped(
    sink: InMemorySink,
) -> None:
    """The 2010-against-2020 tract mismatch, which would otherwise be silent."""
    partial = StaticCrosswalk(
        cells=("h1",),
        rows=(Overlap("22001960100", "h1", population=6000.0, pop_weight=1.0),),
    )

    result = await run(sink, crosswalk=partial)

    assert "appear nowhere in the tract-to-hex crosswalk" in gaps_text(result)
    assert "22055001300" in gaps_text(result)


async def test_the_hex_rows_are_idempotent_too(sink: InMemorySink) -> None:
    await run(sink, crosswalk=grid())
    await run(sink, crosswalk=grid())

    assert sink.count(HexExposure.table) == 4


# ---- policy -------------------------------------------------------------


def test_the_shipped_policy_stays_strict() -> None:
    """The tests relax the tolerance; production must not have followed them."""
    shipped = AirToxScreenAdapter.policy.partial_failure

    assert shipped.max_reject_fraction == 0.01
    # An absolute cap as well, because the raw stream carries one record per
    # hexagon and a fraction over ~150,000 of them would tolerate every tract in
    # the state failing.
    assert shipped.max_rejects == 12


def test_the_timeout_allows_for_a_hundred_megabytes() -> None:
    assert AirToxScreenAdapter.policy.request_timeout_s >= 120.0


async def test_an_unreachable_epa_falls_back_rather_than_inventing_values(
    sink: InMemorySink,
) -> None:
    from pipeline.snapshots import InMemorySnapshotStore

    snapshots = InMemorySnapshotStore()
    async with build_client(TEST_POLICY, transport=transport()) as client:
        ctx = make_context(
            http=make_fetcher(client, source=SOURCE, policy=TEST_POLICY, snapshots=snapshots),
            sink=sink,
            policy=TEST_POLICY,
            source=SOURCE,
        )
        first = await run_adapter(AirToxScreenAdapter(), ctx)
    assert first.status == "partial"

    async with build_client(
        TEST_POLICY, transport=transport(fail={CANCER_URL, RESPIRATORY_URL})
    ) as client:
        ctx = make_context(
            http=make_fetcher(client, source=SOURCE, policy=TEST_POLICY, snapshots=snapshots),
            sink=sink,
            policy=TEST_POLICY,
            source=SOURCE,
        )
        second = await run_adapter(AirToxScreenAdapter(), ctx)

    assert second.status == "stale"
    assert second.vintage == str(RELEASE_YEAR)
    assert all(artifact.from_snapshot for artifact in second.artifacts)
