import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import ContainerDep
from app.core.errors import AppError

router = APIRouter(tags=["system"])
client_log = logging.getLogger("tube2dev.frontend")

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}
_SECRETISH = re.compile(r"(sk-or-[A-Za-z0-9-]{8,}|Bearer\s+[A-Za-z0-9._-]{20,}|eyJ[A-Za-z0-9._-]{30,})")


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True}


@router.get("/readyz", include_in_schema=False)
async def readyz(c: ContainerDep) -> dict:
    async with c.app_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    async with c.creds_engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"ok": True}


class ClientLogEntry(BaseModel):
    level: Literal["debug", "info", "warn", "error"]
    message: str = Field(max_length=2000)
    ts: str | None = Field(None, max_length=40)
    route: str | None = Field(None, max_length=300)
    session_id: str | None = Field(None, max_length=64)
    request_id: str | None = Field(None, max_length=64)
    context: dict[str, Any] | None = None
    stack: str | None = Field(None, max_length=8000)


class ClientLogBatch(BaseModel):
    entries: list[ClientLogEntry] = Field(max_length=50)
    release: str | None = Field(None, max_length=64)


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if isinstance(value, str):
        return _SECRETISH.sub("[redacted]", value[:1000])
    if isinstance(value, dict):
        return {str(k)[:64]: ("[redacted]" if "key" in str(k).lower() or "token" in str(k).lower() else
                              _scrub(v, depth + 1)) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_scrub(v, depth + 1) for v in value[:30]]
    return value


@router.post("/api/v1/client-logs", status_code=204, tags=["system"])
async def client_logs(batch: ClientLogBatch, request: Request,
                      user_agent: Annotated[str | None, Header()] = None) -> Response:
    """Browser log sink. Unauthenticated on purpose (errors on the login page matter too), so it is
    size-limited, rate-limited per client IP, scrubbed for secrets, and only ever written to logs."""
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
    try:
        request.app.state.client_log_limiter.check(ip)
    except AppError:
        return Response(status_code=204)  # drop silently; never make the client retry logs
    for e in batch.entries:
        client_log.log(_LEVELS[e.level], _scrub(e.message), extra={
            "source": "frontend", "release": batch.release, "route": e.route, "client_ts": e.ts,
            "session_id": e.session_id, "client_request_id": e.request_id, "context": _scrub(e.context or {}),
            "stack": _scrub(e.stack) if e.stack else None, "user_agent": (user_agent or "")[:200],
        })
    return Response(status_code=204)
