"""The checks no single adapter can make.

Each of these describes a failure that leaves every individual source looking
perfectly healthy: TRI loading cleanly against facility ids ECHO no longer uses,
tracts present in the list and absent from the values, two sources writing
different hex grids, a group of indicators that has quietly stopped being
computable across the state. The manifests are green in all four cases, which is
why they are checked here and not there.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import pytest

from pipeline.quality.cross import (
    GROUP_INDICATORS,
    GROUP_MINIMUM_PRESENT,
    HEX_INDICATORS,
    HexIndicator,
    check_group_minimums,
    check_hex_grid_agreement,
    check_scored_hexes_meet_minimums,
    check_tract_coverage,
    check_tri_matches_echo,
)
from pipeline.quality.dataset import DictDataset
from pipeline.records import Measurement, NormalizedRecord

CELLS = ["8844c0a339fffff", "8844c0a331fffff", "8844c0a333fffff", "8844c0a335fffff"]


class Facility(NormalizedRecord):
    table: ClassVar[str] = "facility"
    facility_id: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id,)


class TriRelease(NormalizedRecord):
    table: ClassVar[str] = "tri_release"
    facility_id: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.facility_id,)


class CensusTract(NormalizedRecord):
    table: ClassVar[str] = "census_tract"
    geoid: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.geoid,)


class TractExposure(NormalizedRecord):
    table: ClassVar[str] = "tract_exposure"
    tract_geoid: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.tract_geoid,)


class TractDemographics(NormalizedRecord):
    table: ClassVar[str] = "tract_demographics"
    tract_geoid: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.tract_geoid,)


class HexExposure(NormalizedRecord):
    table: ClassVar[str] = "hex_exposure"
    h3: str
    cancer_risk_per_million: Measurement = Measurement.absent()
    respiratory_hazard_index: Measurement = Measurement.absent()

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3,)


class HexAirQuality(NormalizedRecord):
    table: ClassVar[str] = "hex_air_quality"
    h3: str
    annual_mean: Measurement = Measurement.absent()

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3,)


class HexReleaseProximity(NormalizedRecord):
    """Stands in for the hex-level E3 table CS-107 and CS-202 will build."""

    table: ClassVar[str] = "hex_release_proximity"
    h3: str
    value: Measurement = Measurement.absent()

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3,)


class HexScore(NormalizedRecord):
    table: ClassVar[str] = "hex_score"
    h3: str

    def natural_key(self) -> tuple[str, ...]:
        return (self.h3,)


def dataset(**tables: Sequence[NormalizedRecord]) -> DictDataset:
    return DictDataset(tables)


# ---- TRI against ECHO --------------------------------------------------


def test_tri_match_passes_when_every_facility_is_known() -> None:
    data = dataset(
        facility=[Facility(facility_id=f"F{i}") for i in range(10)],
        tri_release=[TriRelease(facility_id=f"F{i}") for i in range(8)],
    )
    assert check_tri_matches_echo(data).status == "pass"


def test_tri_match_warns_when_a_few_facilities_have_drifted() -> None:
    """TRI is annual and ECHO refreshes weekly, so a small gap is real, not a bug."""
    data = dataset(
        facility=[Facility(facility_id=f"F{i}") for i in range(100)],
        tri_release=[TriRelease(facility_id=f"F{i}") for i in range(85)]
        + [TriRelease(facility_id=f"RETIRED{i}") for i in range(15)],
    )
    result = check_tri_matches_echo(data)
    assert result.status == "warn"
    assert result.observed == pytest.approx(0.85)


def test_tri_match_fails_when_the_join_key_has_changed_shape() -> None:
    data = dataset(
        facility=[Facility(facility_id=f"F{i}") for i in range(10)],
        tri_release=[TriRelease(facility_id=f"ID-{i}") for i in range(10)],
    )
    result = check_tri_matches_echo(data)
    assert result.status == "fail"
    assert result.observed == pytest.approx(0.0)
    assert "E3" in result.detail


def test_tri_match_skips_and_names_what_is_missing_rather_than_passing() -> None:
    """A green tick because one of the two sources never loaded is the failure mode."""
    result = check_tri_matches_echo(dataset(facility=[Facility(facility_id="F1")]))
    assert result.status == "skip"
    assert "tri_release" in result.detail


# ---- tract coverage ----------------------------------------------------


def _tracts(count: int) -> list[CensusTract]:
    return [CensusTract(geoid=f"220710{i:05d}") for i in range(count)]


def test_tract_coverage_passes_when_every_tract_has_values() -> None:
    tracts = _tracts(100)
    data = dataset(
        census_tract=tracts,
        tract_exposure=[TractExposure(tract_geoid=t.geoid) for t in tracts],
        tract_demographics=[TractDemographics(tract_geoid=t.geoid) for t in tracts],
    )
    assert [r.status for r in check_tract_coverage(data)] == ["pass", "pass"]


def test_tract_coverage_fails_when_a_source_covers_too_few_tracts() -> None:
    tracts = _tracts(100)
    data = dataset(
        census_tract=tracts,
        tract_exposure=[TractExposure(tract_geoid=t.geoid) for t in tracts[:80]],
        tract_demographics=[TractDemographics(tract_geoid=t.geoid) for t in tracts],
    )
    exposure, demographics = check_tract_coverage(data)
    assert exposure.status == "fail"
    assert "missing indicator" in exposure.detail
    assert demographics.status == "pass"


def test_tract_coverage_warns_on_a_value_for_a_tract_that_does_not_exist() -> None:
    """An orphan is a join that will silently drop, so it is reported either way."""
    tracts = _tracts(100)
    data = dataset(
        census_tract=tracts,
        tract_exposure=[TractExposure(tract_geoid=t.geoid) for t in tracts]
        + [TractExposure(tract_geoid="48201100000")],
        tract_demographics=[TractDemographics(tract_geoid=t.geoid) for t in tracts],
    )
    exposure = check_tract_coverage(data)[0]
    assert exposure.status == "warn"
    assert "48201100000" in exposure.detail


def test_tract_coverage_skips_without_the_tract_list() -> None:
    assert check_tract_coverage(dataset())[0].status == "skip"


# ---- the hex grid ------------------------------------------------------


def test_hex_grids_agree() -> None:
    data = dataset(
        hex_exposure=[HexExposure(h3=c) for c in CELLS],
        hex_air_quality=[HexAirQuality(h3=c) for c in CELLS],
    )
    assert check_hex_grid_agreement(data).status == "pass"


def test_a_source_short_of_cells_fails_and_names_it() -> None:
    """A missing row is a hex the score joins away; an absence belongs inside the row."""
    data = dataset(
        hex_exposure=[HexExposure(h3=c) for c in CELLS],
        hex_air_quality=[HexAirQuality(h3=c) for c in CELLS[:1]],
    )
    result = check_hex_grid_agreement(data)
    assert result.status == "fail"
    assert "hex_air_quality" in result.detail


def test_hex_grid_check_skips_before_interpolation_has_run() -> None:
    assert check_hex_grid_agreement(dataset()).status == "skip"


# ---- section 11 group minimums ----------------------------------------


def test_group_minimums_skip_and_name_the_indicators_with_no_table_yet() -> None:
    """Evaluating a group on the indicators that happen to exist invents failures.

    A cell holding E1 and E2 does not fail a minimum of 2 of 4; it fails only
    because E3 and E4 could not be looked for. CS-106, CS-107 and CS-202 build
    those tables, and until then the honest answer is that the check did not run.
    """
    data = dataset(
        hex_exposure=[
            HexExposure(h3=c, cancer_risk_per_million=Measurement.of(30.0)) for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c) for c in CELLS],
    )
    exposures = next(r for r in check_group_minimums(data) if r.check.endswith("exposures"))
    assert exposures.status == "skip"
    assert "E3" in exposures.detail


@pytest.fixture
def all_exposures_locatable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend E3 already has a hex-level table, so the arithmetic can be tested."""
    monkeypatch.setattr(
        "pipeline.quality.cross.HEX_INDICATORS",
        (*HEX_INDICATORS, HexIndicator("E3", "hex_release_proximity", "h3", "value")),
    )


def proximity(observed: bool = False) -> list[HexReleaseProximity]:
    value = Measurement.of(2.5) if observed else Measurement.absent()
    return [HexReleaseProximity(h3=c, value=value) for c in CELLS]


def test_group_minimum_passes_when_enough_indicators_are_observed(
    all_exposures_locatable: None,
) -> None:
    data = dataset(
        hex_exposure=[
            HexExposure(
                h3=c,
                cancer_risk_per_million=Measurement.of(30.0),
                respiratory_hazard_index=Measurement.of(0.4),
            )
            for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c, annual_mean=Measurement.of(9.0)) for c in CELLS],
        hex_release_proximity=proximity(),
    )
    exposures = next(r for r in check_group_minimums(data) if r.check.endswith("exposures"))
    assert exposures.status == "pass"
    assert exposures.observed == pytest.approx(1.0)


def test_group_minimum_fails_when_coverage_collapses_across_the_grid(
    all_exposures_locatable: None,
) -> None:
    """One indicator on most cells is how a region leaves the map without an error."""
    data = dataset(
        hex_exposure=[
            HexExposure(h3=c, cancer_risk_per_million=Measurement.of(30.0)) for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c) for c in CELLS],
        hex_release_proximity=proximity(),
    )
    exposures = next(r for r in check_group_minimums(data) if r.check.endswith("exposures"))
    assert exposures.status == "fail"
    assert "no_score" in exposures.detail


def test_an_absent_measurement_does_not_count_toward_a_minimum(
    all_exposures_locatable: None,
) -> None:
    """Section 11: absent is not zero, and a row that exists is not a value."""
    data = dataset(
        hex_exposure=[
            HexExposure(
                h3=c,
                cancer_risk_per_million=Measurement.absent(),
                respiratory_hazard_index=Measurement.absent(),
            )
            for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c, annual_mean=Measurement.of(9.0)) for c in CELLS],
        hex_release_proximity=proximity(),
    )
    exposures = next(r for r in check_group_minimums(data) if r.check.endswith("exposures"))
    assert exposures.status == "fail"


# ---- scored hexes ------------------------------------------------------


def test_scored_hex_check_skips_until_scoring_exists() -> None:
    result = check_scored_hexes_meet_minimums(dataset(hex_exposure=[HexExposure(h3=CELLS[0])]))
    assert result.status == "skip"
    assert "CS-204" in result.detail


def test_a_hex_scored_without_its_minimums_fails(all_exposures_locatable: None) -> None:
    """The most damaging defect available: it looks exactly like a hex that earned one."""
    data = dataset(
        hex_exposure=[
            HexExposure(h3=c, cancer_risk_per_million=Measurement.of(30.0)) for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c) for c in CELLS],
        hex_release_proximity=proximity(),
        hex_score=[HexScore(h3=c) for c in CELLS],
    )
    result = check_scored_hexes_meet_minimums(data)
    assert result.status == "fail"
    assert "score the data does not support" in result.detail


def test_scored_hexes_pass_when_they_meet_the_minimums(all_exposures_locatable: None) -> None:
    data = dataset(
        hex_exposure=[
            HexExposure(
                h3=c,
                cancer_risk_per_million=Measurement.of(30.0),
                respiratory_hazard_index=Measurement.of(0.4),
            )
            for c in CELLS
        ],
        hex_air_quality=[HexAirQuality(h3=c, annual_mean=Measurement.of(9.0)) for c in CELLS],
        hex_release_proximity=proximity(observed=True),
        hex_score=[HexScore(h3=c) for c in CELLS],
    )
    assert check_scored_hexes_meet_minimums(data).status == "pass"


# ---- the drift guard on section 11 ------------------------------------


def test_group_table_matches_the_api() -> None:
    """The ingestion package restates part of `api/app/indicators.py` and must not drift.

    `api` and `etl` are separate distributions with separate dependencies, which
    is what lets the API deploy without h3 and the pipeline run without asyncpg.
    The cost is that the group minimums exist in two places, so this loads the
    API's registry off disk and fails the moment the two disagree.
    """
    path = Path(__file__).resolve().parents[2] / "api" / "app" / "indicators.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("api/app/indicators.py is not in this tree")

    spec = importlib.util.spec_from_file_location("clearskies_indicators", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    api_groups = {
        group.value: tuple(i.id for i in module.in_group(group)) for group in module.Group
    }
    api_minimums = {group.value: n for group, n in module.GROUP_MINIMUM_PRESENT.items()}

    assert GROUP_INDICATORS == api_groups
    assert GROUP_MINIMUM_PRESENT == api_minimums
