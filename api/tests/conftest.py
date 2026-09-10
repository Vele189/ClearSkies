from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    # The lifespan runs for real. With no database reachable the pool stays None,
    # which is the degraded path these tests are meant to cover.
    with TestClient(app) as c:
        yield c
