"""Structured logging.

Railway's log view is the only place this service is observed from, and it
indexes JSON objects field by field. A formatted line there is a wall of text
you can grep and nothing more, so every record is emitted as one JSON object
on stdout instead.

Each request is given an id, echoed back in `X-Request-Id` and attached to
every record logged while it is being handled. That is what turns "the panel
was empty at 14:02" into the specific request that served it, which matters
here because a degraded answer is a normal answer for this API: a missing
score and a broken query look identical from the outside.

Set `LOG_FORMAT=text` for a readable line during local development.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

# Paths logged at DEBUG rather than INFO. Railway polls the healthcheck for the
# lifetime of the deploy, so at INFO these would be most of the log and the
# lines worth reading would scroll past.
QUIET_PATHS = frozenset({"/health"})

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """The id of the request being handled, or None outside one."""
    return _request_id.get()


# Attributes the logging module puts on every record. Anything else on a
# record arrived through `extra=` and is ours to publish.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        # uvicorn attaches an ANSI-escaped copy of its own message. Useful on a
        # terminal, noise in a log store.
        "color_message",
    }
)


_factory_installed = False


def _install_record_factory() -> None:
    """Stamp the current request id onto every record as it is created.

    Reading the context variable in the formatter instead would work only
    while formatting happens inline on the same task. Any handler that defers
    the work, a QueueHandler or pytest's capture among them, would format the
    record after the request has ended and quietly drop the id. Attaching it
    at creation makes it part of the record wherever that record travels.
    """
    global _factory_installed
    if _factory_installed:
        return

    base = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base(*args, **kwargs)
        record.request_id = _request_id.get()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


class JsonFormatter(logging.Formatter):
    """One JSON object per record, one record per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Stamped by the record factory; the context variable is the fallback
        # for a record made before configure_logging ran.
        request_id = getattr(record, "request_id", None) or _request_id.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key in _RESERVED or key == "request_id" or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # default=str so an unserializable extra degrades to its repr rather
        # than raising inside the handler and losing the line entirely.
        return json.dumps(payload, default=str)


def configure_logging(level: str = "info", fmt: str = "json") -> None:
    """Install the handler on the root logger and fold uvicorn's loggers into it.

    uvicorn configures its own colourised handlers before it imports the
    application. Left in place they print a second, unstructured copy of every
    line, so they are removed here and allowed to propagate to root instead.
    """
    _install_record_factory()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s  %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # This middleware emits its own access line with the request id on it, so
    # uvicorn's would only be a duplicate without one.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestLogMiddleware:
    """Assign a request id, then log one line per request when it finishes.

    Written against the ASGI interface rather than as a `BaseHTTPMiddleware`
    subclass: that base class moves the response through an anyio stream,
    which costs latency on every request and is the wrong price to pay for an
    access log.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # An id supplied by the caller is kept, so a trace started at the
        # frontend stays one trace across the hop.
        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = _request_id.set(request_id)

        started = time.perf_counter()
        # Stands unless the response actually starts. An exception below never
        # reaches http.response.start, and 500 is what the client will see.
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        error: BaseException | None = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            error = exc
            raise
        finally:
            path = scope.get("path", "")
            fields: dict[str, Any] = {
                "http_method": scope.get("method", ""),
                "http_path": path,
                "http_status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            query: bytes = scope.get("query_string", b"")
            if query:
                fields["http_query"] = query.decode("latin-1")

            if error is not None:
                log.error("request failed", exc_info=error, extra=fields)
            elif path in QUIET_PATHS:
                log.debug("request", extra=fields)
            else:
                log.info("request", extra=fields)

            _request_id.reset(token)
