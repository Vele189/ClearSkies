from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://clearskies:clearskies@localhost:5432/clearskies"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "info"

    # "json" for the deploy, where Railway indexes the fields; "text" for a
    # readable line locally. See app/logging_config.py.
    log_format: Literal["json", "text"] = "json"

    # Locked in Phase 0. See docs/methodology.md section 4.
    pilot_state: str = "LA"

    # Absent in Phase 0; the draft endpoint reports 503 rather than failing at import.
    openai_api_key: str = ""

    # Keep startup fast when the database is not running, so the API still
    # serves /health and reports the database as unavailable.
    db_connect_timeout: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
