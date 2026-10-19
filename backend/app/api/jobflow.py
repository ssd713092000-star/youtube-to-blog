"""Shared state-transition helpers for endpoints that (re)start a graph segment."""

import logging
import uuid
from typing import Any

from app.container import Container
from app.core.errors import AppError, Conflict
from app.db.models_app import Job
from app.services import events
from app.services.tasks import RunKind, new_payload

log = logging.getLogger(__name__)


async def advance(
    c: Container,
    job_id: uuid.UUID,
    *,
    kind: RunKind,
    new_status: str,
    resume: Any = None,
    expect_pending: str | None = None,
    expect_checkpoint: str | None = None,
    expect_status: tuple[str, ...] | None = None,
    updates: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Validate the job is in the expected state, bump its segment and enqueue the run. The row lock
    plus segment counter make concurrent or replayed requests safe: only one wins, the rest get 409."""
    async with c.sessions.begin() as s:
        job = await s.get(Job, job_id, with_for_update=True)
        if job is None:
            raise Conflict("Job disappeared.")
        if expect_pending is not None and job.pending_action != expect_pending:
            raise Conflict("This job isn't waiting for that action any more.", code="not_pending",
                           details={"pending_action": job.pending_action, "status": job.status})
        if expect_checkpoint is not None and job.checkpoint_id != expect_checkpoint:
            raise Conflict("This job changed since you loaded it.", code="stale_checkpoint",
                           details={"checkpoint_id": job.checkpoint_id})
        if expect_status is not None and job.status not in expect_status:
            raise Conflict(f"Job is {job.status}.", code="invalid_status", details={"status": job.status})
        prev = (job.status, job.pending_action, job.segment)
        job.segment += 1
        job.status = new_status
        job.pending_action = None
        job.cancel_requested = False
        for k, v in (updates or {}).items():
            setattr(job, k, v)
        segment = job.segment
        job.pending_run = dict(new_payload(job_id, segment, kind, resume))
        await events.emit(s, job_id, "status_changed", {"status": new_status, "pending_action": None})

    try:
        await c.dispatcher.dispatch(job.pending_run)  # type: ignore[arg-type]
    except Exception as e:
        log.exception("dispatch failed; restoring job state")
        async with c.sessions.begin() as s:
            job = await s.get(Job, job_id, with_for_update=True)
            if job and job.segment == segment:
                job.status, job.pending_action, job.segment = prev
                job.pending_run = None
                await events.emit(s, job_id, "status_changed", {"status": prev[0], "pending_action": prev[1]})
        raise AppError("Couldn't queue the job. Please try again.", code="dispatch_failed", status_code=503) from e
    return {"job_id": str(job_id), "status": new_status}
