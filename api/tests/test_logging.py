"""The log line is an interface too.

Railway indexes these objects field by field, so a record that stops being
JSON, or loses its request id, silently costs the only observability this
service has.
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    RequestLogMiddleware,
    configure_logging,
    current_request_id,
)


def record(**kwargs: object) -> logging.LogRecord:
    r = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="pulled %d rows",
        args=(3,),
        exc_info=None,
    )
    for key, value in kwargs.items():
        setattr(r, key, value)
    return r


def test_formatter_emits_one_json_object_with_the_interpolated_message() -> None:
    payload = json.loads(JsonFormatter().format(record()))

    assert payload["message"] == "pulled 3 rows"
    assert payload["level"] == "info"
    assert payload["logger"] == "app.test"
    # Parseable as a timestamp with an offset, which is what a log search needs.
    assert payload["timestamp"].endswith("+00:00")


def test_formatter_publishes_extra_fields() -> None:
    payload = json.loads(JsonFormatter().format(record(source="tri", vintage="2024")))

    assert payload["source"] == "tri"
    assert payload["vintage"] == "2024"


def test_formatter_never_raises_on_an_unserializable_extra() -> None:
    payload = json.loads(JsonFormatter().format(record(conn=object())))

    assert "object object at" in payload["conn"]


def test_formatter_drops_uvicorns_ansi_escaped_duplicate() -> None:
    """uvicorn sends a coloured copy of its message. It is noise in a log store."""
    payload = json.loads(JsonFormatter().format(record(color_message="pulled \x1b[36m%d\x1b[0m")))

    assert "color_message" not in payload


def test_formatter_carries_the_traceback() -> None:
    try:
        raise ValueError("no such hex")
    except ValueError:
        r = record()
        import sys

        r.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(r))
    assert "ValueError: no such hex" in payload["exception"]


@pytest.fixture
def logged_app() -> FastAPI:
    """A minimal app wrapped in the real middleware."""
    app = FastAPI()

    @app.get("/seen")
    async def seen() -> dict[str, str | None]:
        logging.getLogger("app.test").info("inside the handler")
        return {"request_id": current_request_id()}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("query exploded")

    app.add_middleware(RequestLogMiddleware)
    return app


def test_a_generated_request_id_reaches_the_handler_and_the_response(
    logged_app: FastAPI,
) -> None:
    with TestClient(logged_app) as client:
        r = client.get("/seen")

    assert r.status_code == 200
    assert r.headers[REQUEST_ID_HEADER] == r.json()["request_id"]


def test_a_supplied_request_id_is_kept_so_one_trace_spans_the_hop(
    logged_app: FastAPI,
) -> None:
    with TestClient(logged_app) as client:
        r = client.get("/seen", headers={REQUEST_ID_HEADER: "frontend-abc"})

    assert r.headers[REQUEST_ID_HEADER] == "frontend-abc"
    assert r.json()["request_id"] == "frontend-abc"


def test_the_request_id_is_not_left_set_between_requests(logged_app: FastAPI) -> None:
    with TestClient(logged_app) as client:
        client.get("/seen")

    assert current_request_id() is None


def test_the_access_line_reports_method_path_status_and_duration(
    logged_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.logging_config"):
        with TestClient(logged_app) as client:
            client.get("/seen", params={"bbox": "1,2,3,4"})

    line = next(r for r in caplog.records if r.message == "request")
    payload = json.loads(JsonFormatter().format(line))
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/seen"
    assert payload["http_status"] == 200
    assert payload["http_query"] == "bbox=1%2C2%2C3%2C4"
    assert isinstance(payload["duration_ms"], float)
    assert payload["request_id"]


def test_a_handler_that_raises_is_logged_as_a_failure_with_its_traceback(
    logged_app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.logging_config"):
        with TestClient(logged_app, raise_server_exceptions=False) as client:
            r = client.get("/boom")

    assert r.status_code == 500
    line = next(r for r in caplog.records if r.message == "request failed")
    assert line.levelno == logging.ERROR
    payload = json.loads(JsonFormatter().format(line))
    assert payload["http_status"] == 500
    assert "RuntimeError: query exploded" in payload["exception"]


def test_the_healthcheck_does_not_fill_the_log_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Railway polls /health for the life of the deploy. See QUIET_PATHS."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(RequestLogMiddleware)

    with caplog.at_level(logging.INFO, logger="app.logging_config"):
        with TestClient(app) as client:
            client.get("/health")

    assert [r for r in caplog.records if r.message == "request"] == []


def test_configure_logging_silences_uvicorns_duplicate_access_log() -> None:
    try:
        configure_logging("info", "json")

        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

        access = logging.getLogger("uvicorn.access")
        assert access.handlers == []
        assert access.propagate is True
        # Its lines would be a second copy of ours, without the request id.
        assert access.level == logging.WARNING
    finally:
        # Other test modules share this process and its root logger.
        logging.getLogger().handlers = []


def test_text_format_stays_available_for_local_work() -> None:
    try:
        configure_logging("debug", "text")

        formatter = logging.getLogger().handlers[0].formatter
        assert formatter is not None
        assert not isinstance(formatter, JsonFormatter)
    finally:
        logging.getLogger().handlers = []
