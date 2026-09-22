from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

# Port 1 refuses immediately rather than hanging until db_connect_timeout.
UNREACHABLE = "postgresql://clearskies:clearskies@127.0.0.1:1/clearskies"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """The app with the lifespan run for real and no database behind it.

    The database is pointed somewhere that refuses rather than left to the
    settings. `Settings` reads `.env`, which this repository documents as where
    a developer puts their `DATABASE_URL` and which is symlinked into `api/`,
    so without this the "no database" tests ran against whatever database the
    machine happened to be configured for -- passing on CI, and on a developer
    machine quietly reading the Neon dev branch.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", UNREACHABLE)
        get_settings.cache_clear()
        with TestClient(app) as c:
            yield c
    get_settings.cache_clear()
