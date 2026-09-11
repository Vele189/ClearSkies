"""Per-source expectations, declared as data, and the checks that apply them.

`pipeline.policy` decides whether a pull lost too many records. It cannot decide
whether the records it kept are plausible, because that needs domain knowledge:
how many air facilities Louisiana has, how high a modeled cancer risk can
credibly go, which fields are allowed to be null and how often. That knowledge
is per source, so it is declared per source, in `expectations.py`, in the same
shape for all five.

Declared rather than coded, for the same reason `SourcePolicy` is. A hand-rolled
check per source drifts: one adapter checks its coordinates and another forgets,
one treats a null as fatal and another shrugs. Here a source says what it expects
and this module decides what a violation means, identically every time.

**Nulls and absences are the same question asked twice.** A plain field is null
when it is `None`. A `Measurement` field is null when it is not `observed`, and
its value is `None` by construction (methodology section 11). Both are handled by
`values()` below, so a rule reads the same whichever kind of field it names, and
no rule can accidentally count an absent measurement as a reported zero.

**Fractions, not counts.** Every rule is a fraction of rows, because row counts
change with the state and the vintage and a count-based threshold silently stops
meaning anything the first time a source grows.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import h3

from pipeline.quality.results import CheckResult, Severity

# The same loose envelope methodology section 6 describes, with roughly a 10 km
# buffer. Deliberately independent of any adapter's copy: the gate has to be able
# to check an adapter's output without importing the adapter, and a gate that
# shares a constant with the thing it is checking cannot catch that constant
# being wrong.
PILOT_ENVELOPE: dict[str, tuple[float, float, float, float]] = {
    # south, north, west, east
    "LA": (28.83, 33.10, -94.14, -88.73),
}

PILOT_STATE_FIPS: dict[str, str] = {"LA": "22"}

# Methodology section 5. A cell at another resolution in a hex-keyed table is a
# join that will silently return nothing later.
HEX_RESOLUTION = 8

_GEOID = re.compile(r"^\d{11}$")

# A sentinel distinct from None, because a rule naming a field the record does
# not have is a broken rule and must not read as "every row is null".
_MISSING = object()


# ---- the rules ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RowCount:
    """How many rows this table should hold.

    `high` is as important as `low`. A table that triples overnight is usually a
    join that started fanning out, and it reaches the score as a plausible-looking
    number rather than as an error.
    """

    low: int
    high: int | None = None
    severity: Severity = "fail"
    note: str = ""

    def rendered(self) -> str:
        return f"{self.low} to {self.high}" if self.high is not None else f"at least {self.low}"


@dataclass(frozen=True, slots=True)
class NullRate:
    """How often a field is allowed to be null, or a measurement to be absent."""

    field: str
    max_fraction: float = 0.0
    severity: Severity = "fail"
    note: str = ""


@dataclass(frozen=True, slots=True)
class Bounds:
    """The range a numeric field's values can credibly fall in.

    `max_outside_fraction` defaults to zero: a value outside a bound that was set
    from the physics of the measurement is a defect, not a tail. Sources whose
    upstream genuinely publishes outliers say so by raising it, and say why in
    `note`.
    """

    field: str
    low: float | None = None
    high: float | None = None
    max_outside_fraction: float = 0.0
    severity: Severity = "fail"
    note: str = ""

    def rendered(self) -> str:
        if self.low is not None and self.high is not None:
            return f"{self.low:g} to {self.high:g}"
        if self.low is not None:
            return f"at least {self.low:g}"
        return f"at most {self.high:g}" if self.high is not None else "any"

    def outside(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return True
        return self.high is not None and value > self.high


GeometryKind = Literal["h3_cell", "tract_geoid", "latitude", "longitude", "wkt_polygon"]


@dataclass(frozen=True, slots=True)
class Geometry:
    """A field that has to be a well-formed piece of geography.

    Structural validity only: a cell that H3 recognises at the project's
    resolution, a GEOID with the right shape and state, a coordinate inside the
    pilot envelope, a polygon whose rings close. Whether a facility is really at
    that coordinate is methodology section 6 and belongs in the adapter's
    `validate`, where it is counted per record.
    """

    field: str
    kind: GeometryKind
    max_invalid_fraction: float = 0.0
    allow_null: bool = True
    severity: Severity = "fail"
    note: str = ""


@dataclass(frozen=True, slots=True)
class Categories:
    """The complete set of values a coded field may hold.

    Upstream adding a code is how an enum silently becomes a shrug: an unmapped
    status reads as "not in violation" to everything downstream that tested for
    the codes it knew about.
    """

    field: str
    allowed: frozenset[str]
    severity: Severity = "fail"
    note: str = ""


@dataclass(frozen=True, slots=True)
class TableExpectations:
    """Everything expected of one table after a load."""

    table: str
    rows: RowCount | None = None
    null_rates: tuple[NullRate, ...] = ()
    bounds: tuple[Bounds, ...] = ()
    geometry: tuple[Geometry, ...] = ()
    categories: tuple[Categories, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceExpectations:
    """One source's thresholds, tuned beyond the interface default.

    Attached to the adapter class as `expectations`, or looked up by registry
    name in `expectations.py` for sources whose adapter has not adopted it yet.
    """

    source: str
    tables: tuple[TableExpectations, ...] = ()
    # Sources that publish nothing for a table in some vintages set this, so an
    # empty table is reported rather than treated as an outage.
    optional_tables: frozenset[str] = frozenset()
    notes: tuple[str, ...] = ()

    def table_names(self) -> tuple[str, ...]:
        return tuple(t.table for t in self.tables)


# A source with no declaration is checked for nothing beyond what the interface
# already does. That is a gap, and `expectations.for_source` reports it as one
# rather than passing silently.
NO_EXPECTATIONS = SourceExpectations(source="")


# ---- reading fields off records ----------------------------------------


def values(records: Iterable[Any], name: str) -> tuple[list[Any], int]:
    """Every non-null value of `name`, and how many rows were null.

    A `Measurement` contributes its number when observed and counts as null when
    absent, which is what makes one null-rate rule work for both kinds of field
    without the caller knowing which it named.
    """
    present: list[Any] = []
    nulls = 0
    for record in records:
        raw: Any = getattr(record, name, _MISSING)
        if raw is _MISSING:
            raise KeyError(name)
        observed = getattr(raw, "observed", None)
        if observed is not None:
            if observed:
                present.append(raw.value)
            else:
                nulls += 1
            continue
        if raw is None:
            nulls += 1
        else:
            present.append(raw)
    return present, nulls


def numbers(records: Iterable[Any], name: str) -> tuple[list[float], int]:
    """`values`, restricted to what can be compared against a bound."""
    present, nulls = values(records, name)
    # bool is a subclass of int, and a flag compared against a numeric bound is
    # a rule pointed at the wrong field rather than a value to measure.
    numeric = [float(v) for v in present if isinstance(v, int | float) and not isinstance(v, bool)]
    return numeric, nulls


# ---- the checks --------------------------------------------------------


def _result(
    *,
    check: str,
    scope: str,
    table: str,
    rule_field: str | None,
    ok: bool,
    severity: Severity,
    detail: str,
    observed: float | None,
    expected: str | None,
    note: str = "",
) -> CheckResult:
    return CheckResult(
        check=check,
        scope=scope,
        table=table,
        field=rule_field,
        status="pass" if ok else severity,
        detail=detail if not note else f"{detail} {note}",
        observed=observed,
        expected=expected,
    )


def check_row_count(
    records: Sequence[Any], rule: RowCount, *, scope: str, table: str
) -> CheckResult:
    count = len(records)
    ok = count >= rule.low and (rule.high is None or count <= rule.high)
    if ok:
        detail = f"{count} rows, inside the expected {rule.rendered()}."
    elif count < rule.low:
        detail = f"{count} rows, below the expected {rule.rendered()}; the load lost coverage."
    else:
        detail = f"{count} rows, above the expected {rule.rendered()}; check for a fanned-out join."
    return _result(
        check="row_count",
        scope=scope,
        table=table,
        rule_field=None,
        ok=ok,
        severity=rule.severity,
        detail=detail,
        observed=float(count),
        expected=rule.rendered(),
        note=rule.note,
    )


def check_null_rate(
    records: Sequence[Any], rule: NullRate, *, scope: str, table: str
) -> CheckResult:
    if not records:
        return _skip("null_rate", scope, table, rule.field, "no rows to measure a null rate on")
    _, nulls = values(records, rule.field)
    rate = nulls / len(records)
    ok = rate <= rule.max_fraction
    kind = "absent" if _is_measurement(records[0], rule.field) else "null"
    detail = (
        f"{nulls} of {len(records)} rows have {rule.field} {kind} "
        f"({rate:.1%}); the limit is {rule.max_fraction:.1%}."
    )
    return _result(
        check=f"null_rate.{rule.field}",
        scope=scope,
        table=table,
        rule_field=rule.field,
        ok=ok,
        severity=rule.severity,
        detail=detail,
        observed=rate,
        expected=f"at most {rule.max_fraction:.1%} null",
        note=rule.note,
    )


def check_bounds(records: Sequence[Any], rule: Bounds, *, scope: str, table: str) -> CheckResult:
    present, _ = numbers(records, rule.field)
    if not present:
        return _skip("bounds", scope, table, rule.field, "no numeric values to bound")
    outside = [v for v in present if rule.outside(v)]
    rate = len(outside) / len(present)
    ok = rate <= rule.max_outside_fraction
    if ok:
        detail = f"{len(present)} values of {rule.field} within {rule.rendered()}."
    else:
        worst_value = (
            min(outside) if rule.low is not None and min(outside) < rule.low else max(outside)
        )
        detail = (
            f"{len(outside)} of {len(present)} values of {rule.field} fall outside "
            f"{rule.rendered()} ({rate:.2%}), the furthest at {worst_value:g}."
        )
    return _result(
        check=f"bounds.{rule.field}",
        scope=scope,
        table=table,
        rule_field=rule.field,
        ok=ok,
        severity=rule.severity,
        detail=detail,
        observed=rate,
        expected=rule.rendered(),
        note=rule.note,
    )


def check_geometry(
    records: Sequence[Any], rule: Geometry, *, scope: str, table: str, pilot_state: str = "LA"
) -> CheckResult:
    present, nulls = values(records, rule.field)
    if not rule.allow_null and nulls:
        return _result(
            check=f"geometry.{rule.field}",
            scope=scope,
            table=table,
            rule_field=rule.field,
            ok=False,
            severity=rule.severity,
            detail=f"{nulls} rows have no {rule.field}, which this table does not permit.",
            observed=float(nulls),
            expected="no nulls",
            note=rule.note,
        )
    if not present:
        return _skip("geometry", scope, table, rule.field, "no values to validate")

    invalid = [v for v in present if not _valid_geometry(v, rule.kind, pilot_state)]
    rate = len(invalid) / len(present)
    ok = rate <= rule.max_invalid_fraction
    detail = (
        f"{len(present)} values of {rule.field} are well-formed {rule.kind}."
        if ok
        else (
            f"{len(invalid)} of {len(present)} values of {rule.field} are not a valid "
            f"{rule.kind} ({rate:.2%}), first {invalid[0]!r}."
        )
    )
    return _result(
        check=f"geometry.{rule.field}",
        scope=scope,
        table=table,
        rule_field=rule.field,
        ok=ok,
        severity=rule.severity,
        detail=detail,
        observed=rate,
        expected=f"valid {rule.kind}",
        note=rule.note,
    )


def check_categories(
    records: Sequence[Any], rule: Categories, *, scope: str, table: str
) -> CheckResult:
    present, _ = values(records, rule.field)
    if not present:
        return _skip("categories", scope, table, rule.field, "no values to check")
    unexpected = sorted({str(v) for v in present} - rule.allowed)
    ok = not unexpected
    detail = (
        f"{rule.field} holds only known codes."
        if ok
        else (
            f"{rule.field} holds {len(unexpected)} code(s) this pipeline does not map: "
            f"{', '.join(unexpected[:5])}. Downstream logic will read them as absence."
        )
    )
    return _result(
        check=f"categories.{rule.field}",
        scope=scope,
        table=table,
        rule_field=rule.field,
        ok=ok,
        severity=rule.severity,
        detail=detail,
        observed=float(len(unexpected)),
        expected=f"one of {', '.join(sorted(rule.allowed))}",
        note=rule.note,
    )


def check_table(
    records: Sequence[Any],
    expectations: TableExpectations,
    *,
    scope: str,
    pilot_state: str = "LA",
) -> list[CheckResult]:
    """Every rule declared for one table, applied to what it actually holds.

    A rule naming a field the records do not carry raises rather than skipping.
    That is a broken declaration, and a broken declaration that reports "skipped"
    is a check nobody notices has stopped running.
    """
    results: list[CheckResult] = []
    if expectations.rows is not None:
        results.append(
            check_row_count(records, expectations.rows, scope=scope, table=expectations.table)
        )
    for null_rule in expectations.null_rates:
        results.append(check_null_rate(records, null_rule, scope=scope, table=expectations.table))
    for bound in expectations.bounds:
        results.append(check_bounds(records, bound, scope=scope, table=expectations.table))
    for geometry in expectations.geometry:
        results.append(
            check_geometry(
                records, geometry, scope=scope, table=expectations.table, pilot_state=pilot_state
            )
        )
    for category in expectations.categories:
        results.append(check_categories(records, category, scope=scope, table=expectations.table))
    return results


# ---- geometry validity -------------------------------------------------


def _valid_geometry(value: Any, kind: GeometryKind, pilot_state: str) -> bool:
    match kind:
        case "h3_cell":
            return _valid_cell(value)
        case "tract_geoid":
            return _valid_geoid(value, pilot_state)
        case "latitude" | "longitude":
            return _inside_envelope(value, kind, pilot_state)
        case "wkt_polygon":
            return _valid_polygon(value, pilot_state)


def _valid_cell(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return bool(h3.is_valid_cell(value)) and h3.get_resolution(value) == HEX_RESOLUTION
    except (ValueError, TypeError):
        return False


def _valid_geoid(value: Any, pilot_state: str) -> bool:
    """Eleven digits, and the state the pilot is actually running in.

    A GEOID from the wrong state is the failure that matters here: it joins to
    nothing, so the tract silently drops out of coverage rather than erroring.
    """
    if not isinstance(value, str) or not _GEOID.match(value):
        return False
    expected = PILOT_STATE_FIPS.get(pilot_state)
    return expected is None or value.startswith(expected)


def _inside_envelope(value: Any, kind: GeometryKind, pilot_state: str) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    envelope = PILOT_ENVELOPE.get(pilot_state)
    if envelope is None:
        return -90.0 <= value <= 90.0 if kind == "latitude" else -180.0 <= value <= 180.0
    south, north, west, east = envelope
    return south <= value <= north if kind == "latitude" else west <= value <= east


def _valid_polygon(value: Any, pilot_state: str) -> bool:
    """Structural WKT validity, without taking a geometry library as a dependency.

    Checks what actually goes wrong in practice and is cheap to check: the type
    tag, at least four vertices per ring, a ring that closes, and coordinates in
    the pilot envelope. Self-intersection is left to PostGIS, which refuses the
    insert anyway.
    """
    if not isinstance(value, str):
        return False
    text = value.strip().upper()
    if not text.startswith(("POLYGON", "MULTIPOLYGON")):
        return False
    rings = re.findall(r"\(([^()]*)\)", value)
    if not rings:
        return False
    envelope = PILOT_ENVELOPE.get(pilot_state)
    for ring in rings:
        points = [p.strip() for p in ring.split(",") if p.strip()]
        if len(points) < 4 or points[0] != points[-1]:
            return False
        for point in points:
            parts = point.split()
            if len(parts) < 2:
                return False
            try:
                lon, lat = float(parts[0]), float(parts[1])
            except ValueError:
                return False
            if envelope is not None:
                south, north, west, east = envelope
                if not (south <= lat <= north and west <= lon <= east):
                    return False
    return True


# ---- helpers -----------------------------------------------------------


def _is_measurement(record: Any, name: str) -> bool:
    return hasattr(getattr(record, name, None), "observed")


def _skip(check: str, scope: str, table: str, rule_field: str | None, why: str) -> CheckResult:
    return CheckResult(
        check=f"{check}.{rule_field}" if rule_field else check,
        scope=scope,
        table=table,
        field=rule_field,
        status="skip",
        detail=why,
    )


__all__ = [
    "HEX_RESOLUTION",
    "NO_EXPECTATIONS",
    "PILOT_ENVELOPE",
    "PILOT_STATE_FIPS",
    "Bounds",
    "Categories",
    "Geometry",
    "GeometryKind",
    "NullRate",
    "RowCount",
    "SourceExpectations",
    "TableExpectations",
    "check_bounds",
    "check_categories",
    "check_geometry",
    "check_null_rate",
    "check_row_count",
    "check_table",
    "numbers",
    "values",
]
