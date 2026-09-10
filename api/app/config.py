from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anything `logging.basicConfig` will accept. An unknown value is corrected
# rather than fatal; see the validator below.
LOG_LEVELS = frozenset({"critical", "error", "warning", "info", "debug"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://clearskies:clearskies@localhost:5432/clearskies"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "info"

    # Locked in Phase 0. See docs/methodology.md section 4.
    pilot_state: str = "LA"

    # Absent in Phase 0; the draft endpoint reports 503 rather than failing at import.
    anthropic_api_key: str = ""

    # Keep startup fast when the database is not running, so the API still
    # serves /health and reports the database as unavailable.
    db_connect_timeout: float = 5.0

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        """Fall back to info rather than refusing to start.

        `logging.basicConfig` raises on an unrecognised level, and it is called
        at import time in `app.main`. A typo in one deploy variable would
        otherwise take the whole API down at boot, which is a worse outcome
        than logging at the wrong verbosity.
        """
        normalized = value.strip().lower()
        return normalized if normalized in LOG_LEVELS else "info"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        """Whether the drafting assistant has a key to work with.

        The draft endpoint reads this and returns 503 when it is false. Asking
        at request time rather than at import time is the whole of the
        degradation contract: the key is optional, and scores, the map, and
        every other endpoint must keep working without it.
        """
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
