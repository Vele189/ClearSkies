"""The drift guard on the restated registry.

`api/app/indicators.py` is the single declaration of the fifteen indicators and
is locked to methodology section 8. This package restates the part of it the
components need, so the two can drift, so this test makes them fail loudly when
they do.
"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from burden.indicators import GROUP_INDICATORS, GROUP_MINIMUM_PRESENT, GROUP_WEIGHTS, group_spec


def api_registry() -> Any:
    path = Path(__file__).resolve().parents[2] / "api" / "app" / "indicators.py"
    if not path.exists():  # pragma: no cover - only in a partial checkout
        pytest.skip("api/app/indicators.py is not in this tree")

    spec = importlib.util.spec_from_file_location("clearskies_indicators", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_registry_matches_the_api() -> None:
    """Group membership, weights and minimums all come from the registry of record.

    `api` and `scoring` are separate distributions with separate dependency
    sets, which is what lets this package declare no dependencies at all. The
    cost is that three tables exist in two places, and this is what keeps the
    copy honest.
    """
    module = api_registry()

    assert GROUP_INDICATORS == {
        group.value: tuple(i.id for i in module.in_group(group)) for group in module.Group
    }
    assert GROUP_WEIGHTS == {group.value: w for group, w in module.GROUP_WEIGHTS.items()}
    assert GROUP_MINIMUM_PRESENT == {
        group.value: n for group, n in module.GROUP_MINIMUM_PRESENT.items()
    }


def test_the_components_group_the_way_the_api_does() -> None:
    module = api_registry()

    api_components = {
        component.value: tuple(group.value for group in groups)
        for component, groups in module.COMPONENT_GROUPS.items()
    }

    assert api_components["pollution_burden"] == ("exposures", "environmental_effects")
    assert api_components["population_characteristics"] == (
        "sensitive_populations",
        "socioeconomic_factors",
    )


def test_all_fifteen_indicators_are_accounted_for() -> None:
    # Fourteen would pass every other test in this file and quietly drop an
    # indicator from a component.
    assert sum(len(ids) for ids in GROUP_INDICATORS.values()) == 15


def test_a_group_spec_carries_its_weight_and_minimum() -> None:
    exposures = group_spec("exposures")

    assert exposures.indicators == ("E1", "E2", "E3", "E4")
    assert exposures.weight == 1.0
    assert exposures.minimum_present == 2
