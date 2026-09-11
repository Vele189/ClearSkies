"""EPA AirToxScreen: modeled cancer risk and respiratory hazard, by census tract.

Feeds E1 and E2 (methodology section 8.1), which carry the primary weight in the
Exposures group because this is the only pollution source that covers every part
of the state evenly. TRI and ECHO describe where facilities are; OpenAQ describes
where the two dozen monitors are. This describes everywhere.

Four things about the published data shaped this adapter, all established by
downloading the files rather than assumed:

**The newest release does not publish tract-level results.** The 2020 assessment
publishes state and county summaries plus a mapping tool, and no downloadable
tract file. 2019 is the most recent release that publishes both tract-level
cancer risk and tract-level respiratory hazard, so E1 and E2 are pinned to it.
That is a lag of one whole release on top of the emissions lag below, and both
are the recency term's problem, which is why `vintage` is the release year.

**The published total is rounded to one significant figure and is unusable as an
indicator.** `Total Cancer Risk (per million)` takes ten distinct values across
Louisiana's 1,128 tracts — 20, 30, ... 100, 200 — and the respiratory total takes
nine. Percentile-ranking that (section 9) would collapse the whole state into ten
ties. The per-pollutant columns beside it are full precision, and summing them
recovers 1,128 distinct values spanning 17.9 to 189.3 per million. So E1 and E2
are the sum of the pollutant columns. The published total is still read, because
the sum rounded to one significant figure equals it for all 73,449 tracts in the
national file, which makes the identity a free check on whether the file still
has the shape this adapter believes it has. See `_screen`.

**The sheet interleaves rollups with tracts.** One row for the entire US, 53 for
states and territories and 3,223 for counties, all carrying a `Tract` value
ending `000000`. Loading the US row as a census tract would be a spectacular
error, so they are filtered in `fetch` and counted. They are skipped rather than
rejected: they are a different grain, not bad records, and counting 3,277 of them
as losses would exhaust the partial-failure tolerance every night.

**The tracts are 2010 vintage.** All 1,128 Louisiana tracts in the file appear in
the 2010 tract set and 273 of them do not exist in the 2020 one, whose blocks
section 7 builds the crosswalk from. The join is therefore across census
vintages, and `Coverage.unmatched_sources` counts what fails to cross rather than
letting a quarter of the state vanish quietly. Reconciling the two needs a Census
tract relationship file and belongs with the geography loader, not here.
"""

import io
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import ClassVar
from xml.etree import ElementTree

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.interpolate import Coverage, Crosswalk, HexValue, population_weighted_mean
from pipeline.metadata import KnownGap, SourceSpec
from pipeline.policy import PartialFailurePolicy, RateLimit, SourcePolicy
from pipeline.records import Measurement, NormalizedRecord

# The release, and the emissions year it models. Both are 2019: AirToxScreen
# names itself after the National Emissions Inventory year it runs on, and this
# one was published in December 2022. Section 12 computes the recency term from
# this, not from when the file was downloaded.
RELEASE_YEAR = 2019

# The census vintage the file's tract identifiers are on. Not the release year,
# and not the crosswalk's. See the module docstring.
TRACT_VINTAGE = 2010

RESULTS_PAGE = "https://www.epa.gov/AirToxScreen/2019-airtoxscreen-assessment-results"
FILES = "https://www.epa.gov/system/files/documents/2022-12"
CANCER_URL = f"{FILES}/{RELEASE_YEAR}_National_CancerRisk_by_tract_poll.xlsx"
RESPIRATORY_URL = f"{FILES}/{RELEASE_YEAR}_National_RespHI_by_tract_poll.xlsx"

# The six identifying columns before the total and the per-pollutant columns.
# Checked by name: a file that has lost one of them has changed shape, and
# guessing which column moved where would be worse than failing.
KEY_COLUMNS: tuple[str, ...] = ("State", "EPA Region", "County", "FIPS", "Tract", "Population")

# Column seven, named differently in each file — 'Total Cancer Risk (per
# million)' and 'Total Respiratory (hazard quotient)' — so it is matched on the
# prefix and everything else is a pollutant.
TOTAL_PREFIX = "Total"

GEOID_LENGTH = 11

# A rollup row carries a tract code of six zeroes: 00000000000 for the country,
# SS000000000 for a state, SSCCC000000 for a county. No real tract is numbered
# 000000, so the suffix identifies them on its own.
ROLLUP_SUFFIX = "000000"

# Census FIPS for the pilot state. One entry, because section 4 locks the pilot
# to Louisiana; adding a second state is a methodology decision, not a lookup.
STATE_FIPS: Mapping[str, str] = {"LA": "22"}


class TractExposure(NormalizedRecord):
    """One tract's modeled risks as published. The source of record for E1 and E2."""

    table: ClassVar[str] = "tract_exposure"

    tract_geoid: str
    vintage_year: int
    cancer_risk_per_million: Measurement
    respiratory_hazard_index: Measurement

    def natural_key(self) -> tuple[str, ...]:
        return (self.tract_geoid, str(self.vintage_year))


class HexExposure(NormalizedRecord):
    """One hex's E1 and E2, section 7 applied. Derived, and rebuildable.

    The tract table stays the source of record, so a hex value can be walked back
    to the tracts it came from and a change to the interpolation costs a
    recompute rather than a re-download.
    """

    table: ClassVar[str] = "hex_exposure"

    h3: str
    vintage_year: int
    cancer_risk_per_million: Measurement
    respiratory_hazard_index: Measurement
    cancer_risk_absence: str | None
    respiratory_hazard_absence: str | None
    tract_count: int
    population: float

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3, str(self.vintage_year))


@dataclass(frozen=True, slots=True)
class Reading:
    """One indicator for one tract: the pollutant sum, and what EPA printed."""

    total: float
    published: float | None


@dataclass(frozen=True, slots=True)
class TractRow:
    """One census tract, joined across the two files.

    `rejection` is settled in `fetch` rather than in `validate`, for the same
    reason ECHO settles its coordinate status there: the section 7 mapping has to
    know which tracts are usable before it runs, and the runner asks an adapter
    for its known gaps before the first record is normalized. `validate` raises
    what `fetch` decided, so the rule has one implementation and the losses are
    still counted one record at a time.
    """

    geoid: str
    county: str
    population: int | None
    cancer: Reading | None
    respiratory: Reading | None
    rejection: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True)
class HexCell:
    """One hexagon's mapped values, already computed by `pipeline.interpolate`."""

    h3: str
    cancer: HexValue
    respiratory: HexValue


AirToxRecord = TractRow | HexCell


@dataclass(frozen=True, slots=True)
class SheetReading:
    """What one file contributed for one tract."""

    county: str
    population: int | None
    reading: Reading


def one_significant_figure(value: float) -> float:
    """Round as EPA's total columns are rounded.

    Verified against the whole national cancer file: the sum of the per-pollutant
    columns, rounded this way, equals the printed total for all 73,449 tracts,
    and likewise for the respiratory file across Louisiana. Ties round to even,
    which is `Decimal.quantize`'s default and is what that check passed under.
    """
    if value == 0.0:
        return 0.0
    as_decimal = Decimal(repr(value))
    unit = Decimal(1).scaleb(as_decimal.adjusted())
    return float((as_decimal / unit).quantize(Decimal("1")) * unit)


def _column(reference: str) -> str:
    """'BC12' -> 'BC'. Cells are addressed rather than positional, and may be omitted."""
    return "".join(character for character in reference if character.isalpha())


def _column_index(letters: str) -> int:
    index = 0
    for character in letters:
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index


def _sheet_member(archive: zipfile.ZipFile, url: str) -> str:
    for name in archive.namelist():
        if name.startswith("xl/worksheets/") and name.endswith(".xml"):
            return name
    raise PermanentSourceError(f"{url}: the workbook holds no worksheet")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            if element.tag.endswith("}si"):
                strings.append(_text(element))
                element.clear()
    return strings


def _text(element: ElementTree.Element) -> str:
    return "".join(part.text or "" for part in element.iter() if part.tag.endswith("}t"))


def _cell_text(cell: ElementTree.Element, strings: Sequence[str]) -> str | None:
    kind = cell.get("t")
    if kind == "inlineStr":
        return _text(cell)
    value = next((child for child in cell if child.tag.endswith("}v")), None)
    if value is None or value.text is None:
        return None
    if kind == "s":
        try:
            return strings[int(value.text)]
        except (ValueError, IndexError):
            return None
    return value.text


def _cells(row: ElementTree.Element, strings: Sequence[str]) -> dict[str, str]:
    cells: dict[str, str] = {}
    for cell in row:
        if not cell.tag.endswith("}c"):
            continue
        reference = cell.get("r")
        if reference is None:
            continue
        text = _cell_text(cell, strings)
        if text is not None:
            cells[_column(reference)] = text
    return cells


def read_sheet(blob: bytes, url: str) -> tuple[tuple[str, ...], Iterator[dict[str, str]]]:
    """The header names, and a stream of rows keyed by them.

    Written against the stdlib rather than openpyxl because the sheet inside
    these files is 267 MB of XML, of which this adapter reads six named columns
    and a row sum; a whole-workbook object model would cost far more than the
    parsing it saves. Rows are yielded and released one at a time, so the sheet
    never exists in memory beside the bytes it was decompressed from.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise PermanentSourceError(f"{url}: not a readable .xlsx ({exc})") from None

    strings = _shared_strings(archive)
    stream = archive.open(_sheet_member(archive, url))
    events = ElementTree.iterparse(stream, events=("end",))

    header: dict[str, str] = {}
    for _, element in events:
        if element.tag.endswith("}row"):
            header = _cells(element, strings)
            element.clear()
            break
    if not header:
        stream.close()
        archive.close()
        raise PermanentSourceError(f"{url}: the worksheet has no header row")

    def rows() -> Iterator[dict[str, str]]:
        try:
            for _, element in events:
                if not element.tag.endswith("}row"):
                    continue
                cells = _cells(element, strings)
                element.clear()
                yield {name: cells[letter] for letter, name in header.items() if letter in cells}
        finally:
            stream.close()
            archive.close()

    names = tuple(header[letter] for letter in sorted(header, key=_column_index))
    return names, rows()


def _as_float(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(text: str | None) -> int | None:
    value = _as_float(text)
    return int(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class SheetSummary:
    """One parsed file: what was kept, and what was passed over."""

    readings: Mapping[str, SheetReading]
    rollups: int
    other_states: int


def parse_file(blob: bytes, url: str, state: str) -> SheetSummary:
    """One AirToxScreen tract file, filtered to the pilot state.

    The skipped counts travel with the readings because "1,128 rows kept out of
    76,726" is the difference between a filter that worked and a filter that
    quietly matched nothing.
    """
    header, rows = read_sheet(blob, url)

    missing = [name for name in KEY_COLUMNS if name not in header]
    if missing:
        raise PermanentSourceError(f"{url}: missing columns {missing}")

    total_column = next((name for name in header if name.startswith(TOTAL_PREFIX)), None)
    if total_column is None:
        raise PermanentSourceError(f"{url}: no column starting {TOTAL_PREFIX!r}")

    pollutants = [name for name in header if name not in KEY_COLUMNS and name != total_column]
    if not pollutants:
        # Without these the only number left is the rounded total, which section
        # 9 cannot rank. Continuing on it would silently replace the indicator
        # with a ten-valued version of itself.
        raise PermanentSourceError(f"{url}: no per-pollutant columns beside {total_column!r}")

    readings: dict[str, SheetReading] = {}
    rollups = 0
    other_states = 0
    for row in rows:
        geoid = (row.get("Tract") or "").strip()
        if geoid.endswith(ROLLUP_SUFFIX):
            rollups += 1
            continue
        if (row.get("State") or "").strip().upper() != state:
            other_states += 1
            continue
        readings[geoid] = SheetReading(
            county=(row.get("County") or "").strip(),
            population=_as_int(row.get("Population")),
            reading=Reading(
                total=sum(_as_float(row.get(name)) or 0.0 for name in pollutants),
                published=_as_float(row.get(total_column)),
            ),
        )

    if not readings:
        raise PermanentSourceError(f"{url}: no {state} tracts among {rollups} rollup rows")
    return SheetSummary(readings=readings, rollups=rollups, other_states=other_states)


@dataclass(frozen=True, slots=True)
class Mapped:
    """The result of running section 7 over the grid, ready for the manifest."""

    cells: tuple[HexCell, ...]
    gaps: tuple[KnownGap, ...]
    notes: tuple[str, ...]


@register
class AirToxScreenAdapter(SourceAdapter[AirToxRecord]):
    """Modeled air toxics cancer risk and respiratory hazard for the pilot state."""

    spec = SourceSpec(
        name="airtoxscreen",
        title="EPA AirToxScreen (Air Toxics Screening Assessment)",
        homepage=RESULTS_PAGE,
        cadence="every 1-2 years, ~3-year lag",
        native_geography=f"census tract ({TRACT_VINTAGE} vintage)",
        provides=("E1", "E2"),
    )

    policy: ClassVar[SourcePolicy] = SourcePolicy(
        # A static file host, and this adapter makes two requests a night. One a
        # second is politeness rather than a published limit.
        rate_limit=RateLimit(requests_per_second=1.0, burst=2),
        # The two files are 62 MB and 43 MB, by a wide margin the largest
        # downloads in the project. The 30-second default times out on any
        # ordinary connection and would turn a working source into a nightly
        # retry storm.
        request_timeout_s=300.0,
        # An absolute cap as well as the default fraction. The raw stream carries
        # one record per hexagon as well as one per tract, so on a full grid a
        # fractional rule computed over ~150,000 records would tolerate every one
        # of Louisiana's 1,128 tracts failing. Twelve is one percent of the tract
        # count, which is what the default fraction was trying to express.
        partial_failure=PartialFailurePolicy(max_reject_fraction=0.01, max_rejects=12),
    )

    def __init__(self, crosswalk: Crosswalk | None = None) -> None:
        # The tract-to-hex crosswalk of section 7, built by CS-007 from 2020
        # block populations. None until it exists, which loads E1 and E2 at tract
        # level and says so in the manifest rather than claiming a hex coverage
        # this pull does not have.
        self._crosswalk = crosswalk

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[AirToxRecord]:
        state = ctx.pilot_state
        if state not in STATE_FIPS:
            raise PermanentSourceError(
                f"no census FIPS known for pilot state {state!r}; AirToxScreen is keyed by "
                f"tract GEOID and cannot be filtered without one"
            )

        cancer_download = await ctx.http.get(CANCER_URL)
        cancer = parse_file(cancer_download.content, CANCER_URL, state)

        respiratory_download = await ctx.http.get(RESPIRATORY_URL)
        respiratory = parse_file(respiratory_download.content, RESPIRATORY_URL, state)

        tracts = tuple(
            self._tract_row(
                geoid,
                cancer.readings.get(geoid),
                respiratory.readings.get(geoid),
                STATE_FIPS[state],
            )
            for geoid in sorted(set(cancer.readings) | set(respiratory.readings))
        )

        notes = [
            f"{len(tracts)} {state} tracts on {TRACT_VINTAGE} census geography; "
            f"{cancer.rollups} rollup rows and {cancer.other_states} out-of-state tracts skipped",
            "E1 and E2 are the sum of the per-pollutant columns, not the published total, "
            "which is rounded to one significant figure",
        ]
        if len(cancer.readings) != len(respiratory.readings):
            notes.append(
                f"the two files disagree on coverage: {len(cancer.readings)} tracts carry a "
                f"cancer risk and {len(respiratory.readings)} a respiratory hazard; the "
                f"difference is stored as an absence, not a zero"
            )

        mapped = self._map_to_hexes([row for row in tracts if row.rejection is None])

        return FetchResult(
            records=tracts + mapped.cells,
            # The release, which is also the emissions inventory year. Section 12
            # ages the value from here, so a 2019 assessment downloaded tonight is
            # seven years old tonight.
            vintage=str(RELEASE_YEAR),
            artifacts=[cancer_download.artifact, respiratory_download.artifact],
            known_gaps=mapped.gaps,
            notes=notes + list(mapped.notes),
        )

    @staticmethod
    def _tract_row(
        geoid: str,
        cancer: SheetReading | None,
        respiratory: SheetReading | None,
        expected_fips: str,
    ) -> TractRow:
        present = cancer or respiratory
        row = TractRow(
            geoid=geoid,
            county=present.county if present is not None else "",
            population=present.population if present is not None else None,
            cancer=cancer.reading if cancer is not None else None,
            respiratory=respiratory.reading if respiratory is not None else None,
        )
        return replace(row, rejection=_screen(row, expected_fips))

    def _map_to_hexes(self, usable: Sequence[TractRow]) -> Mapped:
        """Section 7, over the hexes the crosswalk says are in the pilot state.

        Run here rather than in `normalize` because the coverage counts have to
        reach the manifest, and the runner asks for known gaps before the first
        record is normalized.
        """
        if self._crosswalk is None:
            return Mapped(
                cells=(),
                gaps=(
                    KnownGap(
                        scope="geographic",
                        detail=(
                            "No hex grid was supplied, so E1 and E2 were loaded at tract level "
                            "only and no hexagon received a value. The resolution 8 grid and "
                            "the tract-to-hex crosswalk are CS-007; the section 7 mapping this "
                            "adapter applies to them lives in pipeline.interpolate and runs as "
                            "soon as one is passed to the adapter."
                        ),
                        affects=("E1", "E2"),
                    ),
                ),
                notes=("no hex grid supplied; 0 hexagons received a value",),
            )

        cancer_values = {row.geoid: _measure(row.cancer) for row in usable if row.cancer}
        respiratory_values = {
            row.geoid: _measure(row.respiratory) for row in usable if row.respiratory
        }
        cancer_hexes, cancer_coverage = population_weighted_mean(cancer_values, self._crosswalk)
        resp_hexes, resp_coverage = population_weighted_mean(respiratory_values, self._crosswalk)

        cells = tuple(
            HexCell(h3=cancer_hex.h3, cancer=cancer_hex, respiratory=resp_hex)
            for cancer_hex, resp_hex in zip(cancer_hexes, resp_hexes, strict=True)
        )
        return Mapped(
            cells=cells,
            gaps=_mapping_gaps(cancer_coverage, resp_coverage),
            notes=(
                f"E1 mapping: {cancer_coverage.summary()}",
                f"E2 mapping: {resp_coverage.summary()}",
            ),
        )

    # ---- validate ------------------------------------------------------

    def validate(self, record: AirToxRecord, ctx: RunContext) -> None:
        if isinstance(record, HexCell):
            # A hexagon the mapping could not value is an absence, which is a
            # result to be stored and counted, not a record to be dropped.
            return
        if record.rejection is not None:
            reason, field = record.rejection
            raise RecordRejected(reason, field=field, record_id=record.geoid)

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: AirToxRecord, ctx: RunContext) -> Iterator[NormalizedRecord]:
        if isinstance(record, HexCell):
            yield HexExposure(
                h3=record.h3,
                vintage_year=RELEASE_YEAR,
                cancer_risk_per_million=record.cancer.value,
                respiratory_hazard_index=record.respiratory.value,
                cancer_risk_absence=record.cancer.absence,
                respiratory_hazard_absence=record.respiratory.absence,
                # The better-supported of the two, because a tract missing from
                # one file still populated the hexagon for the other. In practice
                # the two files cover the same tracts and these agree.
                tract_count=max(record.cancer.source_count, record.respiratory.source_count),
                population=max(record.cancer.population, record.respiratory.population),
            )
            return

        yield TractExposure(
            tract_geoid=record.geoid,
            vintage_year=RELEASE_YEAR,
            # A tract in one file and not the other is absent from the other, not
            # zero in it. Section 11 and the Measurement type both exist for
            # these two lines.
            cancer_risk_per_million=_measure(record.cancer),
            respiratory_hazard_index=_measure(record.respiratory),
        )

    # ---- gaps ----------------------------------------------------------

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="temporal",
                detail=(
                    f"AirToxScreen {RELEASE_YEAR} models the {RELEASE_YEAR} National Emissions "
                    f"Inventory and was published in December 2022. The emissions it describes "
                    f"are already several years old on the day it is downloaded, which is why "
                    f"the manifest's vintage is the release year rather than the retrieval "
                    f"date; the recency term in section 12 ages the value from there."
                ),
                affects=("E1", "E2"),
                since=date(RELEASE_YEAR, 12, 31),
            ),
            KnownGap(
                scope="temporal",
                detail=(
                    "The 2020 assessment is newer but publishes only state and county "
                    "summaries and a mapping tool, with no downloadable tract-level file for "
                    "either cancer risk or respiratory hazard. E1 and E2 are therefore one "
                    "release behind the newest assessment as well as behind their own "
                    "emissions year."
                ),
                affects=("E1", "E2"),
            ),
            KnownGap(
                scope="geographic",
                detail=(
                    f"Tract identifiers in this release are {TRACT_VINTAGE} census geography. "
                    f"All 1,128 Louisiana tracts in the file exist in the {TRACT_VINTAGE} tract "
                    f"set; 273 of them do not exist in the 2020 set, which is the geography the "
                    f"section 7 crosswalk is built on. Tracts that fail to cross are counted as "
                    f"unmatched rather than dropped, and reconciling the two vintages needs a "
                    f"Census tract relationship file that belongs with the geography loader."
                ),
                affects=("E1", "E2"),
            ),
            KnownGap(
                scope="geographic",
                detail=(
                    f"20 of the 1,148 Louisiana tracts in the {TRACT_VINTAGE} set are absent "
                    f"from the release: eleven water-only tracts numbered 99xxxx, eight "
                    f"special-use tracts numbered 98xxxx, and one ordinary land tract, "
                    f"22071004402 in Orleans Parish. A hexagon drawing only on those tracts "
                    f"receives an absence, never a zero."
                ),
                affects=("E1", "E2"),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "E1 and E2 are modeled, not measured. AirToxScreen disperses inventoried "
                    "emissions through a model and estimates exposure from the result, so it "
                    "inherits whatever the National Emissions Inventory missed, and EPA's own "
                    "guidance is that tract-level results are a screening estimate rather than "
                    "a measurement of any particular place. They carry the primary weight in "
                    "the Exposures group because they are the only pollution source with even "
                    "coverage, not because they are the most certain."
                ),
                affects=("E1", "E2"),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "EPA's printed total columns are rounded to one significant figure and take "
                    "ten distinct values across the pilot state, which section 9's percentile "
                    "ranking cannot use. E1 and E2 are the sum of the per-pollutant columns "
                    "instead. The printed total is retained as a check: the sum rounded to one "
                    "significant figure matches it for every tract in the national file, and a "
                    "tract where it stops matching is rejected as a changed upstream shape."
                ),
                affects=("E1", "E2"),
            ),
            KnownGap(
                scope="temporal",
                detail=(
                    "Several EPA environmental justice datasets were withdrawn from public "
                    "hosting during 2025. Upstream availability is treated as unreliable: both "
                    "files record their URL, retrieval date and checksum, and a night when EPA "
                    "is unreachable continues on the last good snapshot with the recency term "
                    "degraded rather than skipping."
                ),
                affects=("E1", "E2"),
                since=date(2025, 1, 1),
            ),
        )


def _measure(reading: Reading | None) -> Measurement:
    """The pollutant sum, or an absence. Never a zero standing in for silence."""
    return Measurement.of(reading.total) if reading is not None else Measurement.absent()


def _screen(row: TractRow, expected_fips: str) -> tuple[str, str] | None:
    """What makes a tract row unusable. Returns (reason, field), or None."""
    if len(row.geoid) != GEOID_LENGTH or not row.geoid.isdigit():
        return ("malformed tract geoid", "Tract")
    if row.geoid[:2] != expected_fips:
        # The state filter already ran, so this means the file's State column and
        # its GEOID disagree. Attributing the value to a Louisiana hexagon on the
        # strength of a two-letter code is exactly the mistake section 6 is about.
        return ("tract geoid outside the pilot state", "Tract")

    for reading, field in ((row.cancer, "cancer risk"), (row.respiratory, "respiratory hazard")):
        if reading is None:
            continue
        if reading.total < 0:
            return ("negative modeled risk", field)
        if (
            reading.published is not None
            and one_significant_figure(reading.total) != reading.published
        ):
            # The identity holds for every tract in the national file. Where it
            # stops holding, the columns being summed are no longer the columns
            # the total is made of, and loading the sum anyway would publish a
            # number nobody could reproduce from the file.
            return ("pollutant columns disagree with the published total", field)
    return None


def _mapping_gaps(cancer: Coverage, respiratory: Coverage) -> tuple[KnownGap, ...]:
    """What section 7's pass over the grid has to publish about itself."""
    gaps: list[KnownGap] = []
    for coverage, indicator in ((cancer, "E1"), (respiratory, "E2")):
        if coverage.absent:
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{indicator}: {coverage.summary()}. An absent hexagon carries the "
                        f"reason it is absent and no value; section 11 forbids imputing it to "
                        f"zero or to the median."
                    ),
                    affects=(indicator,),
                )
            )
        if coverage.unmatched_sources:
            sample = ", ".join(coverage.unmatched_sources[:5])
            gaps.append(
                KnownGap(
                    scope="geographic",
                    detail=(
                        f"{indicator}: {len(coverage.unmatched_sources)} tracts carry a value "
                        f"but appear nowhere in the tract-to-hex crosswalk, so they reach no "
                        f"hexagon. Expected where the release's {TRACT_VINTAGE} tracts and the "
                        f"crosswalk's 2020 tracts disagree. First few: {sample}."
                    ),
                    affects=(indicator,),
                )
            )
    return tuple(gaps)
