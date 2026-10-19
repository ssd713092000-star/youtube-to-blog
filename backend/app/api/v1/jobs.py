import asyncio
import json
import uuid
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import and_, func, or_, select
from sse_starlette.sse import EventSourceResponse

from app.api import schemas
from app.api.deps import ContainerDep, JobDep, UserDep
from app.api.jobflow import advance
from app.api.serialize import STATUS_GROUPS, decode_cursor, encode_cursor, job_detail, job_summary
from app.api.settings_util import user_settings
from app.core.errors import AppError, Conflict, KeysMissing, QuotaExceeded
from app.db.models_app import Job, UsageLedger
from app.db.repos import PgArticleRegistry
from app.graph.runner import initial_steps
from app.services import events
from app.services.blobs import job_prefix
from app.services.idempotency import request_hash, run_idempotent
from app.services.tasks import new_payload
from app.services.youtube import parse_video_id

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def jobs_today(c, user_id: uuid.UUID) -> int:
    start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    async with c.sessions() as s:
        return await s.scalar(select(func.count(Job.id)).where(Job.user_id == user_id, Job.created_at >= start)) or 0


@router.post("", status_code=202, response_model=schemas.Accepted)
async def create_job(body: schemas.CreateJob, user: UserDep, c: ContainerDep) -> schemas.Accepted:
    if not await c.credentials.has_all(user.id):
        raise KeysMissing("Connect your OpenRouter and dev.to API keys first.")
    if await jobs_today(c, user.id) >= c.settings.daily_job_quota:
        raise QuotaExceeded(f"Daily limit of {c.settings.daily_job_quota} posts reached.",
                            details={"retry_after": 3600})
    vid = parse_video_id(body.video_url)
    if not vid:
        raise AppError("That doesn't look like a YouTube link.", code="invalid_url", status_code=422,
                       details={"field": "video_url"})
    if url := await PgArticleRegistry(c.sessions).existing_url(str(user.id), vid):
        raise Conflict("You already turned this video into a post.", code="already_published",
                       details={"existing_article_url": url})

    st = user_settings(user, c.settings)
    model = body.model or st.default_model
    try:
        if await c.catalog.get(model) is None:
            raise AppError(f"Unknown or non-tool-calling model: {model}", code="invalid_model", status_code=422,
                           details={"field": "model"})
    except AppError:
        raise
    except Exception:
        pass  # catalogue unavailable: let OpenRouter reject a bad model at run time
    budget = body.budget_usd or st.default_budget_usd
    if budget > c.settings.max_budget_usd:
        raise AppError(f"Budget can't exceed ${c.settings.max_budget_usd:.2f}.", code="budget_too_high",
                       status_code=422, details={"field": "budget_usd"})

    title = channel = ""
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    duration = 0
    try:  # usually served from the preview's cache
        meta = await c.youtube.get_metadata(vid)
        title, channel, thumb, duration = meta["title"], meta["channel"], meta["thumbnail_url"], meta["duration"]
    except Exception:
        pass

    job = Job(
        user_id=user.id, video_id=vid, video_url=f"https://www.youtube.com/watch?v={vid}", video_title=title,
        channel_name=channel, thumbnail_url=thumb, duration_seconds=duration, status="queued",
        steps=initial_steps(), budget_usd=budget,
        config={"model": model, "attribution_mode": body.attribution_mode,
                "style_profile_id": body.style_profile_id or st.default_style_profile_id,
                "max_revisions": body.max_revisions, "min_faithfulness": body.min_faithfulness},
    )
    async with c.sessions.begin() as s:
        s.add(job)
        await s.flush()
        job.pending_run = dict(new_payload(job.id, 0, "start"))
        await events.emit(s, job.id, "status_changed", {"status": "queued", "pending_action": None})
    try:
        await c.dispatcher.dispatch(new_payload(job.id, 0, "start"))
    except Exception as e:
        async with c.sessions.begin() as s:
            j = await s.get(Job, job.id)
            j.status = "failed"
            j.errors = [{"step": None, "code": "dispatch_failed", "message": "Couldn't queue the job.",
                         "at": datetime.now(UTC).isoformat(), "retryable": True}]
        raise AppError("Couldn't queue the job. Please retry.", code="dispatch_failed", status_code=503) from e
    return schemas.Accepted(job_id=str(job.id), status="queued")


@router.get("", response_model=schemas.JobList)
async def list_jobs(
    user: UserDep, c: ContainerDep,
    status: Annotated[str | None, Query(description="all | in_progress | needs_you | completed | failed | rejected")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> schemas.JobList:
    base = [Job.user_id == user.id, Job.purged.is_(False)]
    if q:
        like = f"%{q}%"
        base.append(or_(Job.video_title.ilike(like), Job.channel_name.ilike(like)))
    filt = list(base)
    if status and status != "all":
        if status not in STATUS_GROUPS:
            raise AppError("Unknown status filter.", code="invalid_filter", status_code=422)
        filt.append(Job.status.in_(STATUS_GROUPS[status]))
    if cursor:
        ts, id_ = decode_cursor(cursor)
        filt.append(or_(Job.updated_at < ts, and_(Job.updated_at == ts, Job.id < uuid.UUID(id_))))

    async with c.sessions() as s:
        rows = (await s.scalars(
            select(Job).where(*filt).order_by(Job.updated_at.desc(), Job.id.desc()).limit(limit + 1)
        )).all()
        grouped = dict((await s.execute(
            select(Job.status, func.count(Job.id)).where(*base).group_by(Job.status)
        )).all())

    counts = schemas.JobCounts(all=sum(grouped.values()))
    for group in ("in_progress", "needs_you", "completed", "failed"):
        setattr(counts, group, sum(grouped.get(st, 0) for st in STATUS_GROUPS[group]))
    more = len(rows) > limit
    rows = rows[:limit]
    return schemas.JobList(
        items=[job_summary(j) for j in rows],
        next_cursor=encode_cursor(rows[-1].updated_at, str(rows[-1].id)) if more else None,
        counts=counts,
    )


@router.get("/{job_id}", response_model=schemas.JobDetail)
async def get_job(job: JobDep, c: ContainerDep) -> schemas.JobDetail:
    async with c.sessions() as s:
        by_step = dict((await s.execute(
            select(UsageLedger.step, func.sum(UsageLedger.cost_usd)).where(UsageLedger.job_id == job.id)
            .group_by(UsageLedger.step)
        )).all())
    return job_detail(job, {k: float(v or 0) for k, v in by_step.items()})


@router.get("/{job_id}/events", response_class=EventSourceResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
async def job_events(
    job: JobDep, c: ContainerDep, request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[int | None, Query(description="Replay events after this id (if no Last-Event-ID)")] = None,
):
    """Server-sent events: step_started, step_finished, step_failed, sub_item_update, interrupt, usage,
    status_changed, heartbeat. Reconnect with Last-Event-ID to resume without gaps."""
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else (after or 0)
    listener = c.listener

    async def gen():
        last = start
        assert listener is not None
        with listener.subscribe(job.id) as wake:
            while not await request.is_disconnected():
                wake.clear()  # clear before reading so a notify that races the query isn't lost
                evs = await events.events_after(c.sessions, job.id, last)
                for e in evs:
                    last = e.id
                    yield {"id": str(e.id), "event": e.type,
                           "data": json.dumps({**e.payload, "at": e.created_at.isoformat()})}
                if evs:
                    continue
                try:
                    await asyncio.wait_for(wake.wait(), timeout=15)
                except TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}

    return EventSourceResponse(gen(), ping=60, headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/{job_id}/cancel", status_code=202, response_model=schemas.Accepted)
async def cancel_job(job: JobDep, user: UserDep, c: ContainerDep,
                     idempotency_key: Annotated[str | None, Header()] = None) -> schemas.Accepted:
    async def do() -> dict:
        async with c.sessions.begin() as s:
            j = await s.get(Job, job.id, with_for_update=True)
            if j.status in ("completed", "rejected", "cancelled"):
                raise Conflict(f"Job is already {j.status}.", code="invalid_status")
            if j.status in ("queued", "running", "publishing"):
                j.cancel_requested = True  # the worker stops between steps
                return {"job_id": str(j.id), "status": j.status}
            j.status, j.pending_action, j.finished_at = "cancelled", None, datetime.now(UTC)
            j.segment += 1
            await events.emit(s, j.id, "status_changed", {"status": "cancelled", "pending_action": None})
            return {"job_id": str(j.id), "status": "cancelled"}

    _, resp = await run_idempotent(c.sessions, user.id, idempotency_key, request_hash(f"cancel/{job.id}", {}), do)
    return schemas.Accepted(**resp)


@router.post("/{job_id}/retry", status_code=202, response_model=schemas.Accepted)
async def retry_job(job: JobDep, user: UserDep, c: ContainerDep, body: schemas.RetryRequest | None = None,
                    idempotency_key: Annotated[str | None, Header()] = None) -> schemas.Accepted:
    """Resume a failed job from its last checkpoint: completed steps are not re-run or re-billed."""
    body = body or schemas.RetryRequest()

    async def do() -> dict:
        if job.errors and not job.errors[-1].get("retryable", True):
            raise Conflict("This failure can't be fixed by retrying.", code="not_retryable")
        updates = {}
        if body.budget_usd:
            if body.budget_usd > c.settings.max_budget_usd:
                raise AppError(f"Budget can't exceed ${c.settings.max_budget_usd:.2f}.", code="budget_too_high",
                               status_code=422)
            updates["budget_usd"] = body.budget_usd
        if not await c.credentials.has_all(user.id):
            raise KeysMissing("Connect your OpenRouter and dev.to API keys first.")
        return await advance(c, job.id, kind="retry", new_status="queued", expect_status=("failed",), updates=updates)

    _, resp = await run_idempotent(c.sessions, user.id, idempotency_key,
                                   request_hash(f"retry/{job.id}", body.model_dump()), do)
    return schemas.Accepted(**resp)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job: JobDep, user: UserDep, c: ContainerDep) -> Response:
    if job.status in ("queued", "running", "publishing"):
        raise Conflict("Cancel the job before deleting it.", code="job_running")
    await c.graph.checkpointer.adelete_thread(str(job.id))
    await c.blobs.delete_prefix(job_prefix(str(user.id), str(job.id)))
    async with c.sessions.begin() as s:
        j = await s.get(Job, job.id)
        if j:
            await s.delete(j)
    return Response(status_code=204)


@router.get("/{job_id}/history", include_in_schema=False)
async def history(job: JobDep, c: ContainerDep, limit: int = 20) -> list[dict]:
    """Checkpoint history (debugging / time travel)."""
    out = []
    async for snap in c.graph.aget_state_history({"configurable": {"thread_id": str(job.id)}}, limit=limit):
        out.append({"checkpoint_id": snap.config["configurable"]["checkpoint_id"], "next": list(snap.next),
                    "created_at": snap.created_at, "step": snap.metadata.get("step") if snap.metadata else None})
    return out

