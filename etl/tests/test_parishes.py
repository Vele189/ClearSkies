"""The parish table, and the one thing that can go wrong with a hand-written map.

A typo in a name is visible the moment somebody reads the panel. A typo in a
*code* is not: it silently leaves one parish unnamed and gives its name to
nothing. So the codes are checked against the set the loaded tract layer
actually uses, which is the same set the grid assigns from.
"""

import pathlib

from pipeline.parishes import BY_STATE, LOUISIANA_PARISHES, as_arrays, names_for

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The 64 county codes the pilot-state tract layer carries, read from the
#: loaded grid on 2026-09-23. Odd numbers 001 to 127, which is how Louisiana
#: numbers its parishes.
TRACT_LAYER_CODES = frozenset(f"{n:03d}" for n in range(1, 128, 2))


def test_the_codes_are_exactly_the_ones_the_tract_layer_uses() -> None:
    assert set(LOUISIANA_PARISHES) == TRACT_LAYER_CODES


def test_there_are_sixty_four_parishes() -> None:
    """Louisiana has had 64 since 1971. A 65th here is a duplicated key."""
    assert len(LOUISIANA_PARISHES) == 64


def test_no_two_parishes_share_a_name() -> None:
    """East and West Feliciana are different places, and so are the Carrolls."""
    names = list(LOUISIANA_PARISHES.values())
    assert len(set(names)) == len(names)


def test_a_name_never_carries_the_word_parish() -> None:
    """The panel adds it, and a draft may need the bare name.

    "St. James Parish Parish" is the failure this prevents.
    """
    assert not [name for name in LOUISIANA_PARISHES.values() if "parish" in name.lower()]


def test_the_arrays_stay_parallel() -> None:
    codes, names = as_arrays("22")

    assert len(codes) == len(names) == 64
    assert codes == sorted(codes), "unnest pairs by position, so order has to be stable"
    assert dict(zip(codes, names, strict=True)) == LOUISIANA_PARISHES


def test_a_state_with_no_table_yields_nothing_rather_than_raising() -> None:
    """The grid leaves `parish_name` null for it, which is the state it was in."""
    assert names_for("48") == {}
    assert as_arrays("48") == ([], [])


def test_the_pilot_state_is_the_one_tabulated() -> None:
    assert set(BY_STATE) == {"22"}


def test_the_validation_sites_parishes_are_all_in_the_table() -> None:
    """A cross-check against a file written long before this one.

    `sites.yml` names the parish of each pre-registered site, by hand, from
    public documentation, and §17.4 records that one of those labels was wrong
    and was corrected. Every parish it names should appear here; a disagreement
    means one of the two is wrong about Louisiana, and this table is the newer
    and less reviewed of the two.

    Read with a regex rather than a YAML parser because the ingestion package
    does not depend on one and this is not worth a dependency: the field is one
    line, the file's shape is guarded by `scripts/check_validation_set.py` in
    CI, and a parse that found nothing fails loudly below rather than passing
    vacuously.
    """
    import re

    sites = REPO_ROOT / "docs/validation/sites.yml"
    if not sites.exists():  # pragma: no cover - only in a partial checkout
        return

    named = {
        match.group(1).replace(" Parish", "").strip()
        for match in re.finditer(r'^\s*parish:\s*"([^"]+)"', sites.read_text(), re.MULTILINE)
    }

    assert named, "found no parish labels in sites.yml; the cross-check would pass vacuously"
    unknown = sorted(named - set(LOUISIANA_PARISHES.values()))
    assert not unknown, f"named in sites.yml but not in the parish table: {unknown}"
