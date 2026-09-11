from app.indicators import (
    COMPONENT_COLUMNS,
    COMPONENT_GROUPS,
    GROUP_MEAN_COLUMNS,
    GROUP_MINIMUM_PRESENT,
    GROUP_WEIGHTS,
    INDICATORS,
    SOURCE_NAMES,
    Component,
    Group,
    in_group,
)

# Locked to docs/methodology.md section 8. Changing the indicator set is a
# methodology revision (section 17), so this test is meant to fail loudly.
EXPECTED_PER_GROUP = {
    Group.EXPOSURES: 4,
    Group.ENVIRONMENTAL_EFFECTS: 4,
    Group.SENSITIVE_POPULATIONS: 2,
    Group.SOCIOECONOMIC_FACTORS: 5,
}


def test_indicator_set_matches_the_methodology() -> None:
    assert len(INDICATORS) == 15
    for group, expected in EXPECTED_PER_GROUP.items():
        assert len(in_group(group)) == expected, group


def test_indicator_ids_are_unique() -> None:
    ids = [i.id for i in INDICATORS]
    assert len(ids) == len(set(ids))


def test_environmental_effects_carry_half_weight() -> None:
    # Section 8.2: one step further from the harm, and partly a measure of
    # regulatory attention rather than pollution.
    assert GROUP_WEIGHTS[Group.ENVIRONMENTAL_EFFECTS] == 0.5
    assert GROUP_WEIGHTS[Group.EXPOSURES] == 1.0


def test_every_group_belongs_to_exactly_one_component() -> None:
    seen = [g for groups in COMPONENT_GROUPS.values() for g in groups]
    assert sorted(seen) == sorted(Group)
    assert len(seen) == len(set(seen))


def test_minimums_are_satisfiable() -> None:
    for group, minimum in GROUP_MINIMUM_PRESENT.items():
        assert 1 <= minimum <= len(in_group(group))


def test_every_indicator_source_can_be_given_a_vintage() -> None:
    """The hex detail payload keys its vintage map by these names.

    An indicator whose source is not in SOURCE_NAMES is one the panel displays
    and cannot cite, because the vintage arrives under the snapshot's short key
    and nothing looks it up under the registry's name.
    """
    named = set(SOURCE_NAMES.values())
    for indicator in INDICATORS:
        assert indicator.source in named, f"{indicator.id} cites an unmappable source"


def test_every_group_and_component_maps_to_a_stored_column() -> None:
    """A group with no column would silently report a null mean percentile."""
    assert set(GROUP_MEAN_COLUMNS) == set(Group)
    assert set(COMPONENT_COLUMNS) == set(Component)
    assert len(set(GROUP_MEAN_COLUMNS.values())) == len(Group)
