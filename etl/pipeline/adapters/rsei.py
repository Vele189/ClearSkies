"""EPA RSEI: the inhalation toxicity weight each TRI chemical is scaled by.

Feeds E3 (methodology section 8.1), which is the only indicator that multiplies
one source's numbers by another's:

    E3(h) = sum_f [ sum_c w_c * m_{f,c} ] / max(d_{h,f}, 250 m)^2

`pipeline.adapters.tri` loads `m_{f,c}`, the pounds released. This loads `w_c`.
Neither is an indicator on its own: TRI poundage without a weight treats a tonne
of ammonia as a tonne of chromium, and a weight without poundage describes
nothing that was emitted.

The two halves stay in two tables, which is migration 0005's decision and worth
restating because it is the reason this adapter is small. A new RSEI edition is
a data load rather than a schema change, and because every row carries the
`source_edition` it came from, the weight a facility's contribution was computed
with is recoverable after the fact rather than inferred from whatever edition is
current when somebody asks.

**The source is the published toxicity spreadsheet, not the model output.** EPA
distributes RSEI results three ways. The 447 MB Public Release Data archive and
the aggregated grid-cell files carry modeled results this project does not use;
downloading either nightly to read 461 numbers out of it would be absurd. The
toxicity data workbook behind the RSEI Toxicity Weights page is the same
underlying table at 134 KB, and it is the one file EPA publishes whose grain is
one row per TRI chemical.

**ITW is the column, and it is EPA's own final inhalation weight.** The workbook
carries three inhalation quantities. `RfCToxWeight` and `IURToxWeight` are the
non-cancer and cancer weights derived from the reference concentration and the
inhalation unit risk, either of which may be blank; `ITW` is the final weight
EPA selects between them. Choosing between the two here would be this project
inventing a toxicity methodology, which section 17 does not allow, so the final
column is read as published. Note what EPA's own field description says about
it: where a chemical has no inhalation toxicity data, `ITW` is adopted from the
oral pathway, and `ToxicityClassInhale` marks that with an asterisk. 238 of the
461 weights are adopted that way. They are loaded, because EPA publishes them as
the inhalation weight, and `known_gaps` records that a little over half of them
are not measured inhalation toxicity.

**CASNumber is the join key, not CASStandard.** The workbook publishes both: a
packed form, `7783064`, and a hyphenated one, `7783-06-4`, which is the form
`tri_release.cas_number` holds. Reading the hyphenated column directly would be
the obvious choice and it is wrong, because seven of its cells have been
destroyed by Excel before EPA ever published the file. `7783-06-4` parsed as a
date in the year 7783 and was stored as the serial number 2148878, and hydrogen
sulfide is the largest single release in Louisiana's 2024 extract that would
then carry no weight: 930,064 lb, about 1.7% of the state's reported air
poundage. The packed column is text and survives intact, so this adapter reads
it and reconstructs the hyphenated form from the CAS format itself, which is
n-nn-n. Two things check that reconstruction rather than trusting it: every
packed number is verified against its own CAS check digit, and where the
hyphenated cell did survive it must agree with what was reconstructed. Both held
for all 823 rows of v2312.

**A chemical with no weight is not a chemical with a weight of zero.** 362 of the
823 rows carry no `ITW` at all: 359 chemicals EPA holds no inhalation toxicity
data for, and three placeholders that are not chemicals. An absent weight says
EPA has never assessed the chemical, not that the chemical is harmless. None of
them is written: the schema's `CHECK (rsei_weight > 0)` would refuse a zero
anyway, and the E3 join excludes a chemical that has no weight row rather than
multiplying its poundage by nothing. That is the missing-data rule of section 11
applied to a weight instead of to a measurement, and the counts are published in
the manifest so the exclusion is a number a reader can see rather than a
silence.

Against Louisiana's loaded 2024 releases this leaves E3 with 191 of the 229
reported chemicals weighted, covering 99.81% of reported air poundage. The
per-facility shape of that coverage is what `facility_release_toxicity`
(migration 0022) reports, because the share that matters is per facility rather
than statewide: two of the 373 facilities have no weighted poundage at all and
would otherwise contribute a silent zero to E3.
"""

import io
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from openpyxl import load_workbook

from pipeline.adapters.base import FetchResult, SourceAdapter
from pipeline.adapters.registry import register
from pipeline.context import RunContext
from pipeline.errors import PermanentSourceError, RecordRejected
from pipeline.metadata import KnownGap, SourceSpec
from pipeline.quality.checks import (
    Bounds,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
)
from pipeline.records import NormalizedRecord

# Pinned to an edition rather than discovered. EPA publishes each RSEI edition at
# its own URL under the month it was released, so there is no stable "current"
# address to follow and no pattern that yields the next one. The version is read
# back out of the workbook regardless of what this constant says, so a file EPA
# replaces in place is loaded under the edition it actually is; what this
# constant fixes is which edition the project asked for. Updating it, and
# re-running the pull, is the whole of adopting a new RSEI edition.
TOXICITY_URL = "https://www.epa.gov/system/files/other-files/2024-03/toxicity_data_rsei_v2312.xlsx"
PINNED_EDITION = "v2312"

DESCRIPTION_SHEET = "Description"
TOXICITY_SHEET = "Toxicity data"

COL_CAS = "CASNumber"
COL_CAS_STANDARD = "CASStandard"
COL_NAME = "Chemical"
COL_WEIGHT = "ITW"
COL_CLASS = "ToxicityClassInhale"

# Every column this adapter reads. Checked as a set after the header row is
# parsed so that a renamed column fails the pull with the name that went missing,
# rather than silently loading a table of empty weights.
REQUIRED_COLUMNS = (COL_CAS, COL_CAS_STANDARD, COL_NAME, COL_WEIGHT, COL_CLASS)

# A chemical category rather than a single substance: TRI reports "Arsenic
# compounds" under N020 and RSEI weights it under the same code. They join to
# `tri_release.cas_number` exactly as a CAS number does and are not reconstructed
# or check-digit tested, because they are not CAS numbers.
CATEGORY_PREFIX = "N"

# TRI's placeholders for a filing whose chemical identity is withheld or does not
# resolve. RSEI carries a row for each so its chemical table lines up with TRI's,
# with no toxicity data on any of them. They are not chemicals and cannot be
# weighted, so they are skipped and counted rather than rejected: there are
# exactly three, they are there every edition, and a rejection would mark every
# healthy pull `partial` for a condition nobody should ever go and look at. This
# is the same call the TRI adapter makes about Form A filings.
PLACEHOLDER_IDS = frozenset({"INVALID", "MIXTURE", "TRD SECRT"})

# EPA's own asterisk convention on ToxicityClassInhale: the inhalation weight was
# adopted from the oral pathway because no inhalation toxicity data exists.
ORAL_ADOPTED_MARK = "*"

# The published range of RSEI toxicity weights is 0.02 to 1.4 billion. These
# bracket it loosely: their job is to catch a column that moved or a unit that
# changed, not to re-derive EPA's arithmetic.
WEIGHT_FLOOR = 0.01
WEIGHT_CEILING = 2e9


class ChemicalToxicityWeight(NormalizedRecord):
    """One chemical's inhalation toxicity weight, `w_c` in the section 8.1 E3 formula.

    `source_edition` is on the row rather than only on the snapshot because the
    weight is a multiplier on somebody else's number. Reading a facility's E3
    contribution back a year later means knowing which RSEI edition scaled it,
    and an edition recorded only against the pull is an edition lost as soon as
    the next pull replaces the row.
    """

    table: ClassVar[str] = "chemical_toxicity_weight"

    cas_number: str
    chemical_name: str
    rsei_weight: float
    source_edition: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.cas_number,)


@dataclass(frozen=True, slots=True)
class RseiChemical:
    """One row of the toxicity workbook, as read.

    `weight` is None for a chemical RSEI holds no inhalation toxicity data for,
    which is 362 of the 823 rows and is not an error. `normalize` yields nothing
    for those; see the module docstring.
    """

    cas_number: str
    reported_cas_standard: str
    chemical_name: str
    weight: float | None
    toxicity_class: str

    @property
    def is_category(self) -> bool:
        return self.cas_number.startswith(CATEGORY_PREFIX)

    @property
    def is_placeholder(self) -> bool:
        """A TRI placeholder rather than a chemical. Never weighted."""
        return self.cas_number in PLACEHOLDER_IDS

    @property
    def weighted(self) -> bool:
        return self.weight is not None

    @property
    def oral_adopted(self) -> bool:
        """True when EPA took this inhalation weight from the oral pathway."""
        return ORAL_ADOPTED_MARK in self.toxicity_class


def check_digit_ok(packed: str) -> bool:
    """Verify a packed CAS number against its own final digit.

    A CAS number ends in a check digit equal to the sum of the preceding digits
    weighted by their position from the right, modulo ten. It costs nothing and
    it is the only independent evidence that the packed column was read as text
    and not mangled the way the hyphenated one was.
    """
    if len(packed) < 4 or not packed.isdigit():
        return False
    body, check = packed[:-1], int(packed[-1])
    total = sum(int(digit) * position for position, digit in enumerate(reversed(body), start=1))
    return total % 10 == check


def standard_cas(packed: str) -> str:
    """`7783064` -> `7783-06-4`, the form `tri_release.cas_number` holds.

    The CAS format fixes the split: a check digit, two digits before it, and
    everything else in front. Reconstructed rather than read because the column
    that publishes it is corrupt for seven chemicals (module docstring).
    """
    return f"{packed[:-3]}-{packed[-3:-1]}-{packed[-1]}"


def _text(value: Any) -> str:
    """A cell as text, without Excel's float rendering of an integer id."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def _weight(value: Any) -> float | None:
    """A toxicity weight, or None where EPA published none.

    Blank is the documented absence and is common. Anything present that is not
    a positive number is a defect in the cell rather than an absence, so it is
    returned as a sentinel the caller rejects on instead of being folded into
    None and loaded as "no weight".
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return number


@register
class EpaRseiAdapter(SourceAdapter[RseiChemical]):
    """RSEI inhalation toxicity weights, one row per TRI chemical."""

    spec = SourceSpec(
        name="epa_rsei",
        title="EPA Risk-Screening Environmental Indicators (RSEI) toxicity weights",
        homepage="https://www.epa.gov/rsei/rsei-toxicity-weights",
        cadence="annual, tied to an RSEI model version rather than a calendar year",
        native_geography="none; one row per chemical",
        provides=("E3",),
    )

    # The default policy stands. This is one 134 KB request to a static file on
    # www.epa.gov once a night, which is inside every default the interface sets:
    # nothing here justifies its own rate limit or timeout.

    expectations: ClassVar[SourceExpectations | None] = SourceExpectations(
        source="epa_rsei",
        tables=(
            TableExpectations(
                table="chemical_toxicity_weight",
                # Grounded, loosely. v2312 publishes 823 chemicals of which 461
                # carry an inhalation weight, and only the weighted ones are
                # written. The floor catches an edition that loaded almost
                # nothing; the ceiling catches unweighted rows being written as
                # zeros, which would roughly double the count and is the specific
                # regression worth a tripwire.
                rows=RowCount(
                    300,
                    1_200,
                    note="v2312 writes 461 of 823 chemicals. Only chemicals with an ITW.",
                ),
                null_rates=(
                    NullRate("cas_number", 0.0),
                    NullRate("chemical_name", 0.0),
                    # Every written row has a weight by construction. A null here
                    # means an absence was written rather than skipped.
                    NullRate("rsei_weight", 0.0),
                    NullRate("source_edition", 0.0),
                ),
                bounds=(
                    Bounds(
                        "rsei_weight",
                        low=WEIGHT_FLOOR,
                        high=WEIGHT_CEILING,
                        note="EPA publishes weights from 0.02 to 1.4e9. These are relative and "
                        "unitless; the bounds catch a moved column, not a surprising chemical.",
                    ),
                ),
            ),
        ),
        notes=(
            "Weights are relative to other TRI chemicals and span eleven orders of "
            "magnitude, so E3 is dominated by a few chemicals by design. Section 9 "
            "percentile-ranks it before it enters any average.",
        ),
    )

    def __init__(self) -> None:
        # Read off the workbook by `fetch` and reported by `normalize`. Not
        # per-record state: every record carries the same edition.
        self._edition = ""

    # ---- fetch ---------------------------------------------------------

    async def fetch(self, ctx: RunContext) -> FetchResult[RseiChemical]:
        download = await ctx.http.get(TOXICITY_URL)
        try:
            workbook = load_workbook(io.BytesIO(download.content), read_only=True, data_only=True)
        except Exception as exc:
            # openpyxl raises several unrelated types for a file that is not a
            # workbook, and all of them mean the same thing here: what EPA served
            # is not the spreadsheet this adapter reads.
            raise PermanentSourceError(f"{TOXICITY_URL}: not a readable workbook ({exc})") from None
        try:
            self._edition = self._edition_of(workbook)
            chemicals = self._chemicals(workbook)
        finally:
            workbook.close()

        duplicates = self._duplicate_cas(chemicals)
        if duplicates:
            # The table is keyed on the CAS number, so a repeat means one of the
            # two weights would be written and the other silently discarded. Which
            # one wins would depend on row order, and the difference multiplies
            # straight into E3.
            raise PermanentSourceError(
                f"{TOXICITY_URL}: {self._edition} repeats "
                f"{len(duplicates)} CAS numbers ({', '.join(duplicates[:5])}); "
                f"one weight per chemical is what makes the table keyable"
            )

        return FetchResult(
            records=chemicals,
            # Acceptance criterion one. The vintage is the RSEI model version, not
            # a year and not the night of the download: two editions can be
            # published in one calendar year and the same edition can stand for
            # several, so the version is the only identifier that says which
            # weights these are.
            vintage=self._edition,
            artifacts=[download.artifact],
            notes=self._pull_notes(chemicals),
        )

    def _edition_of(self, workbook: Any) -> str:
        """The RSEI version the workbook declares, as `v2312`.

        Read from the file rather than taken from `PINNED_EDITION` so that a file
        replaced in place is recorded as the edition it is. A workbook that no
        longer says is a workbook this adapter cannot label, and an unlabelled
        weight is worse than no weight: it cannot be told from the edition it
        replaced.
        """
        if DESCRIPTION_SHEET not in workbook.sheetnames:
            raise PermanentSourceError(
                f"{TOXICITY_URL}: no {DESCRIPTION_SHEET!r} sheet to read the RSEI version from"
            )
        for row in workbook[DESCRIPTION_SHEET].iter_rows(max_col=1, values_only=True):
            cell = _text(row[0] if row else None)
            if cell.lower().startswith("version"):
                # "Version 2.3.12" is how the workbook writes what EPA names
                # v2312 everywhere else, including in this file's own URL.
                digits = cell.split(None, 1)[1] if " " in cell else ""
                packed = digits.replace(".", "").strip()
                if packed:
                    return f"v{packed}"
        raise PermanentSourceError(
            f"{TOXICITY_URL}: the {DESCRIPTION_SHEET!r} sheet declares no RSEI version"
        )

    def _chemicals(self, workbook: Any) -> tuple[RseiChemical, ...]:
        """Every row of the toxicity sheet, read by column name."""
        if TOXICITY_SHEET not in workbook.sheetnames:
            raise PermanentSourceError(f"{TOXICITY_URL}: no {TOXICITY_SHEET!r} sheet")
        rows = workbook[TOXICITY_SHEET].iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration:
            raise PermanentSourceError(f"{TOXICITY_URL}: {TOXICITY_SHEET!r} is empty") from None

        index = {_text(name): position for position, name in enumerate(header) if _text(name)}
        missing = [name for name in REQUIRED_COLUMNS if name not in index]
        if missing:
            raise PermanentSourceError(
                f"{TOXICITY_URL}: {TOXICITY_SHEET!r} is missing {', '.join(missing)}"
            )

        def cell(row: Sequence[Any], name: str) -> Any:
            position = index[name]
            return row[position] if position < len(row) else None

        chemicals = []
        for row in rows:
            if row is None or not any(value is not None for value in row):
                continue
            chemicals.append(
                RseiChemical(
                    cas_number=_text(cell(row, COL_CAS)).upper(),
                    reported_cas_standard=_text(cell(row, COL_CAS_STANDARD)),
                    chemical_name=_text(cell(row, COL_NAME)),
                    weight=_weight(cell(row, COL_WEIGHT)),
                    toxicity_class=_text(cell(row, COL_CLASS)),
                )
            )
        if not chemicals:
            raise PermanentSourceError(f"{TOXICITY_URL}: {TOXICITY_SHEET!r} has no data rows")
        return tuple(chemicals)

    @staticmethod
    def _duplicate_cas(chemicals: Sequence[RseiChemical]) -> list[str]:
        seen: set[str] = set()
        repeated: list[str] = []
        for chemical in chemicals:
            if chemical.is_placeholder or not chemical.weighted:
                continue
            if chemical.cas_number in seen:
                repeated.append(chemical.cas_number)
            seen.add(chemical.cas_number)
        return repeated

    # ---- validate ------------------------------------------------------

    def validate(self, record: RseiChemical, ctx: RunContext) -> None:
        if not record.cas_number:
            raise RecordRejected("missing CAS number", field=COL_CAS)
        if record.is_placeholder:
            # Nothing else is true of these rows and nothing else needs to be.
            # `normalize` drops them and `_pull_notes` counts them.
            return
        if not record.chemical_name:
            raise RecordRejected(
                "missing chemical name", field=COL_NAME, record_id=record.cas_number
            )
        if not record.is_category and not check_digit_ok(record.cas_number):
            # Reads as a CAS number and fails its own check digit, which is the
            # signature of the cell having been converted on the way out of Excel.
            raise RecordRejected(
                f"CAS number {record.cas_number!r} fails its check digit",
                field=COL_CAS,
                record_id=record.cas_number,
            )
        if record.weight is not None and not record.weight > 0:
            # Catches both a non-numeric cell, which `_weight` returns as NaN, and
            # a zero or negative weight. None of the three can be stored, and a
            # zero in particular must not be: it would say "harmless" where the
            # table's convention is that an unweighted chemical has no row.
            raise RecordRejected(
                f"toxicity weight {record.weight!r} is not positive",
                field=COL_WEIGHT,
                record_id=record.cas_number,
            )
        if not record.is_category and "-" in record.reported_cas_standard:
            # The reconstruction is only trustworthy if it agrees with EPA
            # wherever EPA's own hyphenated cell survived. It did for all 780
            # intact rows of v2312; a disagreement means the CAS format assumed
            # here no longer holds.
            reconstructed = standard_cas(record.cas_number)
            if reconstructed != record.reported_cas_standard:
                raise RecordRejected(
                    f"reconstructed CAS {reconstructed} disagrees with the published "
                    f"{record.reported_cas_standard}",
                    field=COL_CAS_STANDARD,
                    record_id=record.cas_number,
                )

    # ---- normalize -----------------------------------------------------

    def normalize(self, record: RseiChemical, ctx: RunContext) -> Iterator[NormalizedRecord]:
        """One weight row, or none at all for a chemical RSEI cannot weight.

        Acceptance criterion two lives here. Yielding nothing is what keeps an
        unweighted chemical out of E3 without asserting anything about it: there
        is no row, so the join finds nothing to multiply by, rather than finding
        a zero that would claim the chemical is harmless. The count of what was
        skipped is published by `_pull_notes` and `_pull_gaps`.
        """
        if record.is_placeholder or not record.weighted:
            return
        assert record.weight is not None  # narrowed by `weighted`; validate proved it positive
        yield ChemicalToxicityWeight(
            cas_number=(
                record.cas_number if record.is_category else standard_cas(record.cas_number)
            ),
            chemical_name=record.chemical_name,
            rsei_weight=record.weight,
            source_edition=self._edition,
        )

    # ---- what the pull has to say about itself -------------------------

    def _pull_notes(self, chemicals: Sequence[RseiChemical]) -> tuple[str, ...]:
        weighted = [c for c in chemicals if c.weighted and not c.is_placeholder]
        categories = sum(1 for c in weighted if c.is_category)
        placeholders = sum(1 for c in chemicals if c.is_placeholder)
        notes = [
            f"{len(chemicals)} chemicals in RSEI {self._edition}, "
            f"{len(weighted)} with an inhalation toxicity weight",
            f"{categories} of the weighted rows are TRI chemical categories rather than "
            f"single substances",
            f"{placeholders} rows are TRI placeholders (withheld, mixture or unresolved "
            f"chemical identity) and carry no toxicity data",
        ]
        if self._edition != PINNED_EDITION:
            # Not a failure. The pull is still valid and still labelled correctly;
            # what has happened is that EPA replaced the file this project pinned,
            # and somebody should decide whether to follow it deliberately.
            notes.append(
                f"the workbook declares {self._edition} but this adapter pinned "
                f"{PINNED_EDITION}: EPA has replaced the file at the pinned URL"
            )
        return tuple(notes)

    def known_gaps(self, ctx: RunContext) -> tuple[KnownGap, ...]:
        return (
            KnownGap(
                scope="attribute",
                detail=(
                    "RSEI publishes an inhalation toxicity weight for 461 of the 823 TRI "
                    "chemicals and categories in v2312. The other 362 are 359 chemicals with "
                    "no inhalation toxicity data and three TRI placeholders; the chemicals "
                    "are still loaded as releases by the TRI adapter and still appear in the "
                    "drill-down, and E3 excludes them rather than scoring them as harmless. "
                    "Against Louisiana's 2024 releases "
                    "that leaves 191 of the 229 reported chemicals weighted, covering 99.81% "
                    "of reported air poundage; the two facilities whose reported poundage is "
                    "entirely unweighted are the reason the coverage share is reported per "
                    "facility and not only statewide."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "238 of the 461 inhalation weights are adopted from the oral pathway, "
                    "which is EPA's documented behaviour where a chemical has no inhalation "
                    "toxicity data and is marked with an asterisk on ToxicityClassInhale. "
                    "They are loaded as published, because selecting differently would be "
                    "this project revising a toxicity methodology under section 17, but a "
                    "little over half of E3's weights are therefore not measured inhalation "
                    "toxicity."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "RSEI toxicity weights are relative rather than absolute: they express "
                    "each chemical's toxicity against other TRI chemicals and span 0.02 to "
                    "1.4 billion. A toxicity-weighted poundage is an index, not a dose and "
                    "not a risk, which is why section 8.1 reads E3 as how much toxic material "
                    "is released nearby and percentile-ranks it before it enters any average."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="methodological",
                detail=(
                    "The weights describe chronic human health effects only. Short-term "
                    "exposure and ecological effects are outside RSEI entirely, so a chemical "
                    "dangerous mainly in an acute release is weighted here by its long-term "
                    "toxicity alone."
                ),
                affects=("E3",),
            ),
            KnownGap(
                scope="temporal",
                detail=(
                    f"The edition is pinned to {PINNED_EDITION}, published March 2024. EPA "
                    f"gives each RSEI edition its own URL, so a new edition is adopted by "
                    f"changing one constant and re-running this pull rather than by a schema "
                    f"change; until that happens the weights are the pinned edition's however "
                    f"recent the releases they scale are."
                ),
                affects=("E3",),
            ),
        )
