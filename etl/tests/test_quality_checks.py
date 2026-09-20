"""The per-source check primitives, and the guards on the declarations.

Two kinds of test here. Most assert that a rule fires on bad data and stays quiet
on good data, which is the only way to know a threshold is doing anything at all.

The last two are drift guards, and they matter more than they look. A quality
check pointed at a field that has been renamed does not fail; it raises once, or
worse, reports "skipped" every night while everyone reads the green tick. So the
expectations are checked against the record classes they describe, for every
adapter that is actually importable. Four of the five are on unmerged branches
today, so those guards cover ECHO now and cover each of the others on the day its
branch lands, without anyone remembering to come back.
"""

from typing import Any

import pytest

from pipeline.adapters import REGISTRY
from pipeline.quality.checks import (
    Bounds,
    Categories,
    Geometry,
    NullRate,
    RowCount,
    SourceExpectations,
    TableExpectations,
    check_bounds,
    check_categories,
    check_geometry,
    check_null_rate,
    check_row_count,
    check_table,
    values,
)
from pipeline.quality.expectations import TUNED, for_source
from pipeline.records import Measurement, NormalizedRecord

# A cell that H3 accepts at resolution 8, and one at resolution 7. Both are real
# cells; the point of the test is that only one of them belongs in a hex table.
CELL_RES8 = "8844c0a339fffff"
CELL_RES7 = "8744c0a33ffffff"


class Row(NormalizedRecord):
    """A stand-in with one of each kind of field the rules can name."""

    table = "row"

    key: str
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    h3: str | None = None
    geoid: str | None = None
    geom_wkt: str | None = None
    status: str | None = None
    amount: float | None = None
    reading: Measurement = Measurement.absent()

    def natural_key(self) -> tuple[str, ...]:
        return (self.key,)


def rows(count: int, **fields: object) -> list[Row]:
    return [Row(key=str(i), **fields) for i in range(count)]  # type: ignore[arg-type]


# ---- reading fields ----------------------------------------------------


def test_an_absent_measurement_reads_as_null_and_an_observed_zero_does_not() -> None:
    """Section 11's whole distinction, at the point a check could destroy it.

    Counting `Measurement.of(0.0)` as null would let a source that reported zero
    releases look like a source that reported nothing, which is the confusion the
    record type exists to prevent.
    """
    present, nulls = values(
        [
            Row(key="a", reading=Measurement.of(0.0)),
            Row(key="b", reading=Measurement.absent()),
            Row(key="c", reading=Measurement.of(4.5)),
        ],
        "reading",
    )
    assert present == [0.0, 4.5]
    assert nulls == 1


def test_naming_a_field_the_record_does_not_have_raises() -> None:
    """A broken declaration must not read as "every row is null"."""
    with pytest.raises(KeyError):
        values(rows(3), "no_such_field")


# ---- row counts --------------------------------------------------------


def test_row_count_passes_inside_the_range() -> None:
    assert check_row_count(rows(50), RowCount(10, 100), scope="s", table="row").status == "pass"


def test_row_count_fails_below_the_floor_and_says_coverage_was_lost() -> None:
    result = check_row_count(rows(3), RowCount(10, 100), scope="s", table="row")
    assert result.status == "fail"
    assert result.observed == 3
    assert "lost coverage" in result.detail


def test_row_count_fails_above_the_ceiling() -> None:
    """A ceiling is not decoration: a fanned-out join reaches the score as a number."""
    result = check_row_count(rows(500), RowCount(10, 100), scope="s", table="row")
    assert result.status == "fail"
    assert "fanned-out join" in result.detail


def test_row_count_severity_is_declared_not_decided() -> None:
    result = check_row_count(rows(0), RowCount(10, severity="warn"), scope="s", table="row")
    assert result.status == "warn"


# ---- null rates --------------------------------------------------------


def test_null_rate_passes_when_under_the_limit() -> None:
    records = rows(9, name="x") + [Row(key="9")]
    assert check_null_rate(records, NullRate("name", 0.2), scope="s", table="row").status == "pass"


def test_null_rate_fails_when_over_the_limit() -> None:
    records = rows(5, name="x") + rows(5)
    result = check_null_rate(records, NullRate("name", 0.2), scope="s", table="row")
    assert result.status == "fail"
    assert result.observed == pytest.approx(0.5)


def test_null_rate_on_a_measurement_counts_absences() -> None:
    records = [
        Row(key="a", reading=Measurement.of(1.0)),
        Row(key="b", reading=Measurement.absent()),
    ]
    result = check_null_rate(records, NullRate("reading", 0.1), scope="s", table="row")
    assert result.status == "fail"
    assert "absent" in result.detail


def test_null_rate_skips_rather_than_dividing_by_zero() -> None:
    assert check_null_rate([], NullRate("name"), scope="s", table="row").status == "skip"


# ---- bounds ------------------------------------------------------------


def test_bounds_pass_inside_the_range() -> None:
    records = [Row(key=str(i), amount=float(i)) for i in range(10)]
    assert check_bounds(records, Bounds("amount", 0, 100), scope="s", table="row").status == "pass"


def test_bounds_fail_on_a_value_outside_and_name_the_furthest() -> None:
    records = [Row(key="a", amount=5.0), Row(key="b", amount=-3.0)]
    result = check_bounds(records, Bounds("amount", 0, 100), scope="s", table="row")
    assert result.status == "fail"
    assert "-3" in result.detail


def test_bounds_tolerate_outliers_only_when_the_rule_says_so() -> None:
    records = [Row(key=str(i), amount=1.0) for i in range(99)] + [Row(key="x", amount=9_999.0)]
    strict = check_bounds(records, Bounds("amount", 0, 100), scope="s", table="row")
    lenient = check_bounds(
        records, Bounds("amount", 0, 100, max_outside_fraction=0.02), scope="s", table="row"
    )
    assert strict.status == "fail"
    assert lenient.status == "pass"


def test_bounds_ignore_an_absent_measurement_rather_than_bounding_it_as_zero() -> None:
    """An absence has no value to compare, and treating it as 0.0 would invent one."""
    records = [
        Row(key="a", reading=Measurement.absent()),
        Row(key="b", reading=Measurement.of(5.0)),
    ]
    result = check_bounds(records, Bounds("reading", low=1.0), scope="s", table="row")
    assert result.status == "pass"


# ---- geometry ----------------------------------------------------------


def test_a_cell_at_the_wrong_resolution_is_invalid() -> None:
    """A resolution 7 cell joins to nothing at resolution 8 and errors nowhere."""
    good = check_geometry(
        [Row(key="a", h3=CELL_RES8)], Geometry("h3", "h3_cell"), scope="s", table="row"
    )
    bad = check_geometry(
        [Row(key="a", h3=CELL_RES7)], Geometry("h3", "h3_cell"), scope="s", table="row"
    )
    assert good.status == "pass"
    assert bad.status == "fail"


def test_a_cell_that_is_not_a_cell_is_invalid() -> None:
    result = check_geometry(
        [Row(key="a", h3="not-a-cell")], Geometry("h3", "h3_cell"), scope="s", table="row"
    )
    assert result.status == "fail"


def test_a_geoid_from_the_wrong_state_is_invalid() -> None:
    """The failure that matters: it joins to nothing, so the tract drops out silently."""
    louisiana = check_geometry(
        [Row(key="a", geoid="22071001100")],
        Geometry("geoid", "tract_geoid"),
        scope="s",
        table="row",
    )
    texas = check_geometry(
        [Row(key="a", geoid="48201100000")],
        Geometry("geoid", "tract_geoid"),
        scope="s",
        table="row",
    )
    assert louisiana.status == "pass"
    assert texas.status == "fail"


def test_a_coordinate_outside_the_pilot_envelope_is_invalid() -> None:
    inside = check_geometry(
        [Row(key="a", latitude=30.45)], Geometry("latitude", "latitude"), scope="s", table="row"
    )
    outside = check_geometry(
        [Row(key="a", latitude=41.88)], Geometry("latitude", "latitude"), scope="s", table="row"
    )
    assert inside.status == "pass"
    assert outside.status == "fail"


def test_geometry_may_permit_nulls_or_refuse_them() -> None:
    permitted = check_geometry(
        [Row(key="a")], Geometry("h3", "h3_cell", allow_null=True), scope="s", table="row"
    )
    refused = check_geometry(
        [Row(key="a")], Geometry("h3", "h3_cell", allow_null=False), scope="s", table="row"
    )
    assert permitted.status == "skip"
    assert refused.status == "fail"


@pytest.mark.parametrize(
    ("wkt", "valid"),
    [
        ("POLYGON((-91.1 30.4, -91.0 30.4, -91.0 30.5, -91.1 30.5, -91.1 30.4))", True),
        # Unclosed: the last vertex does not repeat the first.
        ("POLYGON((-91.1 30.4, -91.0 30.4, -91.0 30.5, -91.1 30.5))", False),
        # Three vertices cannot bound an area once the ring closes.
        ("POLYGON((-91.1 30.4, -91.0 30.4, -91.1 30.4))", False),
        # Well-formed, and in Illinois.
        ("POLYGON((-88.0 41.8, -87.9 41.8, -87.9 41.9, -88.0 41.9, -88.0 41.8))", False),
        ("LINESTRING(-91.1 30.4, -91.0 30.4)", False),
    ],
)
def test_polygon_validity(wkt: str, valid: bool) -> None:
    result = check_geometry(
        [Row(key="a", geom_wkt=wkt)],
        Geometry("geom_wkt", "wkt_polygon", allow_null=False),
        scope="s",
        table="row",
    )
    assert (result.status == "pass") is valid


# ---- categories --------------------------------------------------------


def test_an_unmapped_code_fails_and_names_it() -> None:
    """Upstream adding a code is how an enum silently becomes a shrug."""
    records = [Row(key="a", status="ok"), Row(key="b", status="brand_new_code")]
    result = check_categories(
        records, Categories("status", frozenset({"ok"})), scope="s", table="row"
    )
    assert result.status == "fail"
    assert "brand_new_code" in result.detail
    assert "read them as absence" in result.detail


# ---- the whole table ---------------------------------------------------


def test_check_table_runs_every_declared_rule() -> None:
    expectations = TableExpectations(
        table="row",
        rows=RowCount(1, 10),
        null_rates=(NullRate("name", 0.0),),
        bounds=(Bounds("amount", 0, 10),),
        geometry=(Geometry("h3", "h3_cell"),),
        categories=(Categories("status", frozenset({"ok"})),),
    )
    records = [Row(key="a", name="x", amount=5.0, h3=CELL_RES8, status="ok")]
    results = check_table(records, expectations, scope="s")
    assert [r.status for r in results] == ["pass"] * 5
    assert {r.check for r in results} == {
        "row_count",
        "null_rate.name",
        "bounds.amount",
        "geometry.h3",
        "categories.status",
    }


# ---- guards on the declarations ---------------------------------------


def test_every_phase_one_source_declares_expectations() -> None:
    """The five sources CS-108 names all have thresholds, and they are non-empty."""
    assert set(TUNED) == {"epa_echo", "epa_tri", "airtoxscreen", "openaq", "census_acs"}
    for name, expectations in TUNED.items():
        assert expectations.source == name
        assert expectations.tables, f"{name} declares no tables"
        for table in expectations.tables:
            assert (
                table.rows or table.null_rates or table.bounds or table.geometry or table.categories
            ), f"{name}/{table.table} declares no rules"


def test_an_adapter_class_declaration_wins_over_the_bridging_table() -> None:
    """The intended home is the adapter. `TUNED` is the bridge while branches are open."""
    own = SourceExpectations(source="epa_echo", tables=(TableExpectations(table="facility"),))

    class Adapter:
        expectations = own

    assert for_source("epa_echo", Adapter) is own
    assert for_source("epa_echo", None) is TUNED["epa_echo"]


def test_a_source_with_no_declaration_returns_none_rather_than_an_empty_pass() -> None:
    assert for_source("fake", None) is None


def _record_classes() -> dict[str, type[NormalizedRecord]]:
    """Every record class any registered adapter can produce, keyed by table."""

    def walk(cls: Any) -> list[type[NormalizedRecord]]:
        found = []
        for sub in cls.__subclasses__():
            found += walk(sub)
            # Only real adapter records. Other test modules define stand-ins that
            # reuse these table names, and a stand-in shadowing the class this
            # guard exists to check would turn the guard into a coin toss.
            if getattr(sub, "table", None) and sub.__module__.startswith("pipeline."):
                found.append(sub)
        return found

    assert REGISTRY, "importing pipeline.adapters should register something"
    return {cls.table: cls for cls in walk(NormalizedRecord)}


def _all_declarations() -> list[SourceExpectations]:
    """Every expectation in the tree, however it was declared.

    Both homes are covered: the `expectations` class variable, which is where a
    declaration belongs, and the `TUNED` table, which holds the five Phase 1
    sources while their adapters are on unmerged branches.
    """
    declared = [cls.expectations for cls in REGISTRY.values() if cls.expectations is not None]
    return declared + list(TUNED.values())


def test_every_rule_names_a_field_its_record_class_actually_has() -> None:
    """The drift guard.

    A rule naming a renamed field does not fail loudly; it skips, or raises once
    in a place nobody reads. This checks each declaration against the record class
    that writes the table, for every adapter importable in this tree. The
    reference adapter and ECHO's three tables are covered today; TRI,
    AirToxScreen, OpenAQ and ACS come under it the day their branches merge, with
    no edit here.
    """
    classes = _record_classes()
    checked = 0
    for expectations in _all_declarations():
        for table in expectations.tables:
            record = classes.get(table.table)
            if record is None:
                continue  # that adapter is not in this tree yet
            fields = set(record.model_fields)
            named = (
                {r.field for r in table.null_rates}
                | {r.field for r in table.bounds}
                | {r.field for r in table.geometry}
                | {r.field for r in table.categories}
            )
            missing = sorted(named - fields)
            assert not missing, (
                f"{expectations.source}/{table.table} names absent field(s) {missing}"
            )
            checked += 1
    assert checked, "no adapter record classes were importable; the guard checked nothing"
