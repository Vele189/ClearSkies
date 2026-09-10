"""The settings object, and the promises the rest of the service makes about it.

Two of these matter more than the others. An absent LLM key must leave every
other endpoint working, because the key is optional in Phase 0 and the drafting
assistant is the last thing to arrive. And an unusable log level must not stop
the API from booting, because `logging.basicConfig` is called at import time in
`app.main` and raises on a value it does not recognise.

The draft endpoint itself arrives in Phase 2. `llm_enabled` is the flag it reads
to decide between answering and returning 503, so its behaviour is pinned here
rather than waiting for the endpoint that consumes it.
"""

import logging
from typing import Any

import pytest

from app.config import LOG_LEVELS, Settings, get_settings


def make(**overrides: Any) -> Settings:
    """A Settings that ignores any .env a developer happens to have.

    Overrides are passed through rather than defaulted here, so a test that
    names nothing still lets the environment win, which is what the override
    test below is checking.
    """
    # `_env_file` is a BaseSettings constructor argument; the mypy plugin
    # generates __init__ from the declared fields alone and does not know it.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_constructs_with_nothing_configured() -> None:
    settings = make()
    assert settings.pilot_state == "LA"
    assert settings.log_level == "info"


@pytest.mark.parametrize("key", ["", "   ", "\n"])
def test_absent_key_disables_the_assistant(key: str) -> None:
    assert make(anthropic_api_key=key).llm_enabled is False


def test_present_key_enables_the_assistant() -> None:
    assert make(anthropic_api_key="sk-ant-not-a-real-key").llm_enabled is True


def test_absent_key_leaves_the_rest_of_the_settings_usable() -> None:
    """The degradation contract: no key is a disabled feature, not a broken app."""
    settings = make(anthropic_api_key="", cors_origins="https://clearskies.example")
    assert settings.llm_enabled is False
    assert settings.cors_origin_list == ["https://clearskies.example"]
    assert settings.database_url.startswith("postgresql://")


@pytest.mark.parametrize("level", sorted(LOG_LEVELS))
def test_every_accepted_level_is_usable_by_logging(level: str) -> None:
    """The validator's output has to satisfy the caller that crashes on bad input."""
    logging.getLogger("clearskies.test").setLevel(make(log_level=level).log_level.upper())


@pytest.mark.parametrize("level", ["INFO", " Debug ", "WARNING"])
def test_level_is_normalized_rather_than_rejected(level: str) -> None:
    assert make(log_level=level).log_level == level.strip().lower()


@pytest.mark.parametrize("level", ["verbose", "loud", "", "trace"])
def test_unknown_level_falls_back_instead_of_raising(level: str) -> None:
    assert make(log_level=level).log_level == "info"


def test_cors_origins_split_and_strip() -> None:
    settings = make(cors_origins="http://a.test, http://b.test ,, http://c.test")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test", "http://c.test"]


def test_cors_origins_empty_means_no_origins() -> None:
    assert make(cors_origins="  ").cors_origin_list == []


def test_environment_overrides_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PILOT_STATE", "TX")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    settings = make()
    assert settings.pilot_state == "TX"
    assert settings.llm_enabled is True


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_unknown_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Railway service carries variables meant for its neighbours."""
    monkeypatch.setenv("VITE_TILES_URL", "https://tiles.example.com/x.pmtiles")
    assert make().pilot_state == "LA"
