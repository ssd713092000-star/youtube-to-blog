"""tube2dev-worker: private service that Cloud Tasks calls to run graph segments."""

import contextlib
import logging
from typing import Annotated

from fastapi import FastAPI, Header, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.auth.firebase import Unauthorized
from app.container import build_container
from app.core.config import get_settings
from app.core.http import install_error_handlers, install_middleware
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level, "tube2dev-worker", settings.gcp_project)
log = logging.getLogger(__name__)
_google_request = google_requests.Request()


class RunJob(BaseModel):
    job_id: str
    segment: int
    kind: str
    resume: dict | None = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with build_container(settings, listen_events=False) as container:
        app.state.container = container
        yield


app = FastAPI(title="Tube2Dev worker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
install_error_handlers(app)
install_middleware(app)


async def verify_tasks_oidc(authorization: str | None) -> None:
    """Only Cloud Tasks (signing as sa-tasks-invoker) may call the worker. Cloud Run IAM already
    requires run.invoker; this checks the token's audience and identity as defence in depth."""
    if settings.env == "local":
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing OIDC token.")
    token = authorization.split(" ", 1)[1]
    try:
        claims = await run_in_threadpool(id_token.verify_oauth2_token, token, _google_request,
                                         settings.worker_url.rstrip("/"))
    except Exception:
        raise Unauthorized("Invalid OIDC token.") from None
    if claims.get("email") != settings.tasks_invoker_sa or not claims.get("email_verified"):
        raise Unauthorized("Unexpected caller.")


@app.post("/internal/run-job")
async def run_job(body: RunJob, request: Request, authorization: Annotated[str | None, Header()] = None,
                  x_cloudtasks_taskretrycount: Annotated[str | None, Header()] = None) -> dict:
    await verify_tasks_oidc(authorization)
    log.info("running segment", extra={"job": body.job_id, "segment": body.segment, "kind": body.kind,
                                       "task_retry": x_cloudtasks_taskretrycount})
    # Graph failures are recorded on the job and return 200 (the user retries from the UI).
    # Infra failures raise -> 5xx -> Cloud Tasks retries; JobBusy -> 503 -> retried later.
    await request.app.state.container.runner.run_segment(body.model_dump())
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
