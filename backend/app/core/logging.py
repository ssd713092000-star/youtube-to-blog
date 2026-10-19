"""Structured JSON logging for Cloud Logging.

Every record carries `severity`, `service`, and the request/job/user ids from contextvars, plus the
`logging.googleapis.com/trace` field so Cloud Logging groups a request's logs under its trace. Use
`logging.getLogger(__name__)` everywhere; pass structured data with `extra={...}`."""

import contextvars
import logging
import sys
import time
import uuid
from typing import Any

from pythonjsonlogger.json import JsonFormatter
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace", default=None)
job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)

_GCP_PROJECT = ""
# Keys that must never reach the logs even if someone passes them in `extra`.
_REDACT = {"api_key", "openrouter_key", "devto_key", "authorization", "password", "token", "ciphertext"}


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.job_id = job_id_var.get()
        record.user_id = user_id_var.get()
        trace = trace_var.get()
        if trace and _GCP_PROJECT:
            setattr(record, "logging.googleapis.com/trace", f"projects/{_GCP_PROJECT}/traces/{trace}")
        for k in list(record.__dict__):
            if k.lower() in _REDACT:
                record.__dict__[k] = "[redacted]"
        return True


class _Formatter(JsonFormatter):
    def add_fields(self, log_record: dict[str, Any], record: logging.LogRecord, message_dict: dict[str, Any]) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["severity"] = record.levelname
        log_record["logger"] = record.name
        for k in ("request_id", "job_id", "user_id"):
            if log_record.get(k) is None:
                log_record.pop(k, None)


def setup_logging(level: str = "INFO", service: str = "tube2dev", gcp_project: str = "") -> None:
    global _GCP_PROJECT
    _GCP_PROJECT = gcp_project
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(_Formatter("%(message)s", static_fields={"service": service}, timestamp=True))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's own access log is replaced by AccessLogMiddleware (structured, with ids and latency).
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    for name in ("httpx", "httpcore", "google", "urllib3", "yt_dlp", "openai", "psycopg.pool"):
        logging.getLogger(name).setLevel(logging.WARNING)


class AccessLogMiddleware:
    """Pure ASGI (works with streaming/SSE). Sets request id + trace, logs one line per request."""

    def __init__(self, app: ASGIApp, skip_paths: tuple[str, ...] = ("/healthz",)):
        self.app = app
        self.skip = skip_paths
        self.log = logging.getLogger("tube2dev.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        rid = headers.get("x-request-id") or uuid.uuid4().hex
        request_id_var.set(rid)
        if tc := headers.get("x-cloud-trace-context"):
            trace_var.set(tc.split("/", 1)[0])
        user_id_var.set(None)
        job_id_var.set(None)
        start = time.perf_counter()
        status = 500

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            path = scope.get("path", "")
            if path not in self.skip:
                ms = round((time.perf_counter() - start) * 1000, 1)
                level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
                self.log.log(level, "%s %s %s %.0fms", scope.get("method"), path, status, ms, extra={
                    "httpRequest": {
                        "requestMethod": scope.get("method"), "requestUrl": path, "status": status,
                        "latency": f"{ms / 1000:.3f}s", "userAgent": headers.get("user-agent", "")[:200],
                    },
                })
