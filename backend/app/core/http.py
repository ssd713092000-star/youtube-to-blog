"""Shared FastAPI wiring: error envelope + middleware."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import AccessLogMiddleware, request_id_var
from app.services.locks import JobBusy

log = logging.getLogger(__name__)


def _envelope(status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None):
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    h = {"X-Request-ID": request_id_var.get() or "", **(headers or {})}
    return JSONResponse(body, status_code=status, headers=h)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, e: AppError):
        headers = {}
        if e.status_code == 429 and (ra := e.details.get("retry_after")):
            headers["Retry-After"] = str(ra)
        if e.status_code >= 500:
            log.error("app error %s: %s", e.code, e.message)
        return _envelope(e.status_code, e.code, e.message, e.details, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]} for err in e.errors()]
        return _envelope(422, "validation_error", "Some fields are invalid.", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        return _envelope(e.status_code, {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error"),
                         str(e.detail))

    @app.exception_handler(JobBusy)
    async def busy(_: Request, e: JobBusy):
        return _envelope(503, "job_busy", "Job is being processed by another worker.", headers={"Retry-After": "30"})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, e: Exception):
        log.exception("unhandled error")
        return _envelope(500, "internal_error", "Something went wrong on our side.")


def install_middleware(app: FastAPI) -> None:
    app.add_middleware(AccessLogMiddleware)
