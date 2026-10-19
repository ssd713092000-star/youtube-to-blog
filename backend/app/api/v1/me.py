from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import Date, cast, delete, func, select

from app.api import schemas
from app.api.deps import ContainerDep, UserDep
from app.api.settings_util import user_settings
from app.core.errors import AppError
from app.db.models_app import Job, UsageLedger, User
from app.services.blobs import job_prefix
from app.services.credentials import Provider

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=schemas.Profile)
async def me(user: UserDep, c: ContainerDep) -> schemas.Profile:
    return schemas.Profile(id=str(user.id), email=user.email, display_name=user.display_name,
                           photo_url=user.photo_url, settings=user_settings(user, c.settings))


@router.get("/settings", response_model=schemas.UserSettings)
async def get_settings(user: UserDep, c: ContainerDep) -> schemas.UserSettings:
    return user_settings(user, c.settings)


@router.put("/settings", response_model=schemas.UserSettings)
async def put_settings(body: schemas.UserSettings, user: UserDep, c: ContainerDep) -> schemas.UserSettings:
    if body.default_budget_usd > c.settings.max_budget_usd:
        raise AppError(f"Budget can't exceed ${c.settings.max_budget_usd:.2f}.", code="budget_too_high",
                       status_code=422, details={"field": "default_budget_usd"})
    try:
        if await c.catalog.get(body.default_model) is None:
            raise AppError("Unknown or non-tool-calling model.", code="invalid_model", status_code=422,
                           details={"field": "default_model"})
    except AppError:
        raise
    except Exception:
        pass
    async with c.sessions.begin() as s:
        u = await s.get(User, user.id, with_for_update=True)
        u.settings = {**(u.settings or {}), **body.model_dump()}
    return body


# ---------------------------------------------------------------- integrations (keys)
async def _integrations(c, user) -> schemas.Integrations:
    st = await c.credentials.status(user.id)
    return schemas.Integrations(openrouter=schemas.IntegrationStatus(**st["openrouter"]),
                                devto=schemas.IntegrationStatus(**st["devto"]))


@router.get("/integrations", response_model=schemas.Integrations)
async def get_integrations(user: UserDep, c: ContainerDep) -> schemas.Integrations:
    return await _integrations(c, user)


@router.put("/integrations/{provider}", response_model=schemas.Integrations)
async def put_key(provider: Provider, body: schemas.ApiKeyIn, user: UserDep, c: ContainerDep) -> schemas.Integrations:
    """Verifies the key with the provider, then stores it KMS-encrypted. The key is never returned."""
    await c.credentials.put(user.id, provider, body.api_key)
    return await _integrations(c, user)


@router.post("/integrations/{provider}/test", response_model=schemas.TestResult)
async def test_key(provider: Provider, user: UserDep, c: ContainerDep) -> schemas.TestResult:
    return schemas.TestResult(status=await c.credentials.test(user.id, provider))


@router.delete("/integrations/{provider}", status_code=204)
async def delete_key(provider: Provider, user: UserDep, c: ContainerDep) -> Response:
    await c.credentials.delete(user.id, provider)
    return Response(status_code=204)


# ---------------------------------------------------------------- usage / dashboard
def _day_start() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


async def _quota(c, user) -> schemas.Quota:
    async with c.sessions() as s:
        used = await s.scalar(select(func.count(Job.id)).where(Job.user_id == user.id, Job.created_at >= _day_start()))
    return schemas.Quota(jobs_per_day=c.settings.daily_job_quota, used_today=used or 0)


@router.get("/usage", response_model=schemas.UsageOut)
async def usage(user: UserDep, c: ContainerDep,
                period: Annotated[Literal["7d", "30d", "90d"], Query()] = "30d") -> schemas.UsageOut:
    since = datetime.now(UTC) - timedelta(days=int(period[:-1]))
    async with c.sessions() as s:
        day = cast(UsageLedger.created_at, Date)
        daily_cost = dict((await s.execute(
            select(day, func.sum(UsageLedger.cost_usd)).where(UsageLedger.user_id == user.id,
                                                              UsageLedger.created_at >= since).group_by(day)
        )).all())
        jday = cast(Job.created_at, Date)
        daily_jobs = dict((await s.execute(
            select(jday, func.count(Job.id)).where(Job.user_id == user.id, Job.created_at >= since).group_by(jday)
        )).all())
        by_model = (await s.execute(
            select(UsageLedger.model, func.count(func.distinct(UsageLedger.job_id)), func.sum(UsageLedger.cost_usd),
                   func.sum(UsageLedger.prompt_tokens + UsageLedger.completion_tokens))
            .where(UsageLedger.user_id == user.id, UsageLedger.created_at >= since)
            .group_by(UsageLedger.model).order_by(func.sum(UsageLedger.cost_usd).desc())
        )).all()
        completed = await s.scalar(select(func.count(Job.id)).where(
            Job.user_id == user.id, Job.created_at >= since, Job.status == "completed"))

    days = [(since + timedelta(days=i + 1)).date() for i in range(int(period[:-1]))]
    daily = [schemas.DailyUsage(date=d.isoformat(), cost_usd=round(float(daily_cost.get(d, 0) or 0), 4),
                                jobs=int(daily_jobs.get(d, 0))) for d in days]
    cost = sum(x.cost_usd for x in daily)
    tokens = sum(int(t or 0) for *_, t in by_model)
    return schemas.UsageOut(
        period=period, jobs=sum(x.jobs for x in daily), cost_usd=round(cost, 4), tokens=tokens,
        avg_cost_per_post=round(cost / completed, 4) if completed else None, daily=daily,
        by_model=[schemas.ModelUsage(model=m, jobs=int(j), cost_usd=round(float(cst or 0), 4), tokens=int(t or 0))
                  for m, j, cst, t in by_model],
        quota=await _quota(c, user),
    )


@router.get("/dashboard", response_model=schemas.DashboardStats)
async def dashboard(user: UserDep, c: ContainerDep) -> schemas.DashboardStats:
    month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with c.sessions() as s:
        posts = await s.scalar(select(func.count(Job.id)).where(
            Job.user_id == user.id, Job.status == "completed", Job.created_at >= month))
        avg = await s.scalar(select(func.avg(Job.faithfulness_score)).where(
            Job.user_id == user.id, Job.created_at >= month, Job.faithfulness_score.is_not(None)))
        spend = await s.scalar(select(func.sum(UsageLedger.cost_usd)).where(
            UsageLedger.user_id == user.id, UsageLedger.created_at >= month))
        awaiting = await s.scalar(select(func.count(Job.id)).where(
            Job.user_id == user.id, Job.status.in_(("awaiting_review", "awaiting_publish"))))
    return schemas.DashboardStats(
        posts_this_month=posts or 0, avg_faithfulness=round(float(avg), 2) if avg is not None else None,
        spend_this_month=round(float(spend or 0), 4), monthly_budget_usd=user_settings(user, c.settings).monthly_budget_usd,
        awaiting_you=awaiting or 0, quota=await _quota(c, user),
    )


# ---------------------------------------------------------------- account deletion
@router.delete("", status_code=204)
async def delete_account(body: schemas.DeleteAccount, request: Request, user: UserDep, c: ContainerDep) -> Response:
    if not user.email or body.confirm_email.strip().lower() != user.email.lower():
        raise AppError("Type your email address to confirm.", code="confirmation_mismatch", status_code=422,
                       details={"field": "confirm_email"})
    async with c.sessions() as s:
        jobs = (await s.scalars(select(Job.id).where(Job.user_id == user.id))).all()
    for jid in jobs:
        await c.graph.checkpointer.adelete_thread(str(jid))
        await c.blobs.delete_prefix(job_prefix(str(user.id), str(jid)))
    for ns in (("users", str(user.id), "style_profiles"), ("users", str(user.id), "feedback")):
        for item in await c.store.asearch(ns, limit=1000):
            await c.store.adelete(ns, item.key)
    await c.credentials.delete(user.id)
    async with c.sessions.begin() as s:
        await s.execute(delete(User).where(User.id == user.id))  # cascades jobs, events, articles, usage
    await request.app.state.verifier.delete_user(user.firebase_uid)
    return Response(status_code=204)
