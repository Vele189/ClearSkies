import pytest

from pipeline.adapters import FakeAirAdapter, get, names, specs
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.registry import register
from pipeline.metadata import SourceSpec


def test_the_reference_adapter_is_registered() -> None:
    assert "fake" in names()
    assert get("fake") is FakeAirAdapter


def test_an_unknown_source_names_the_ones_that_exist() -> None:
    with pytest.raises(KeyError, match="registered: "):
        get("epa_echo")


def test_every_registered_source_describes_itself() -> None:
    # The map's "why did this hex score that way" panel reads these fields, so a
    # source with a blank spec is a source a reader cannot check.
    for spec in specs():
        assert spec.name and spec.title and spec.homepage
        assert spec.cadence and spec.native_geography


def test_registration_requires_a_spec() -> None:
    class Anonymous(SourceAdapter[str]):
        pass

    with pytest.raises(TypeError, match="must declare a SourceSpec"):
        register(Anonymous)


def test_registration_rejects_a_shouty_name() -> None:
    class Shouty(SourceAdapter[str]):
        spec = SourceSpec(
            name="EPA-ECHO",
            title="x",
            homepage="https://x.invalid",
            cadence="daily",
            native_geography="point",
        )

    with pytest.raises(ValueError, match="lowercase"):
        register(Shouty)


def test_two_adapters_cannot_claim_one_name() -> None:
    class Impostor(SourceAdapter[str]):
        spec = FakeAirAdapter.spec

    with pytest.raises(ValueError, match="already registered"):
        register(Impostor)
