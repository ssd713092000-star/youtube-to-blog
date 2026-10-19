from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api import schemas
from app.api.deps import ContainerDep, UserDep
from app.api.settings_util import user_settings
from app.db.models_app import Job
from app.services.openrouter_models import estimate_cost, words_from_duration
from app.services.youtube import parse_video_id

router = APIRouter(prefix="/models", tags=["models"])
DEFAULT_VIDEO_MINUTES = 22


@router.get("", response_model=schemas.ModelList)
async def list_models(
    user: UserDep, c: ContainerDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    max_price_mtok: Annotated[float | None, Query(ge=0)] = None,
    min_context: Annotated[int | None, Query(ge=0)] = None,
    used_before: bool = False,
    sort: Literal["price", "context", "name"] = "price",
    video_id: Annotated[str | None, Query(description="Video id or URL for a per-video estimate")] = None,
    budget_usd: Annotated[float | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> schemas.ModelList:
    settings = user_settings(user, c.settings)
    models = await c.catalog.list()

    async with c.sessions() as s:
        used = set((await s.scalars(select(Job.config["model"].astext).where(Job.user_id == user.id).distinct())).all())
        avg_words = await s.scalar(select(func.avg(Job.transcript_words)).where(
            Job.user_id == user.id, Job.transcript_words > 0, Job.created_at >= datetime.now(UTC) - timedelta(days=30)))

    basis: Literal["video", "your_average", "default"] = "default"
    words = words_from_duration(DEFAULT_VIDEO_MINUTES * 60)
    if vid := (parse_video_id(video_id) if video_id else None):
        try:
            tr = await c.youtube.get_transcript(vid)
            words, basis = sum(len(x["text"].split()) for x in tr["snippets"]), "video"
        except Exception:
            try:
                words, basis = words_from_duration((await c.youtube.get_metadata(vid))["duration"]), "video"
            except Exception:
                pass
    elif avg_words:
        words, basis = int(avg_words), "your_average"

    mult = await c.catalog.multipliers(user.id)
    budget = budget_usd or settings.default_budget_usd
    out: list[schemas.ModelOut] = []
    for m in models:
        api = m.to_api()
        if q and q.lower() not in (m.id + " " + m.name).lower():
            continue
        if max_price_mtok is not None and api["price_per_mtok_in"] > max_price_mtok:
            continue
        if min_context and m.context_length < min_context:
            continue
        if used_before and m.id not in used:
            continue
        est = estimate_cost(m, words, mult)
        out.append(schemas.ModelOut(**api, estimate_usd=schemas.CostRange(**est), over_budget=est["high"] > budget,
                                    used_before=m.id in used, is_default=m.id == settings.default_model))

    key = {"price": lambda x: (x.price_per_mtok_in + x.price_per_mtok_out, x.id),
           "context": lambda x: (-x.context_length, x.id), "name": lambda x: x.name.lower()}[sort]
    out.sort(key=key)
    out.sort(key=lambda x: not x.is_default)  # current default first, like the picker mockup
    return schemas.ModelList(items=out[:limit], basis_words=words, basis=basis)
