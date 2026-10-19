from fastapi import APIRouter

from app.api import schemas
from app.api.deps import ContainerDep, UserDep
from app.api.settings_util import user_settings
from app.core.errors import AppError, TransientFetchError
from app.db.repos import PgArticleRegistry
from app.services.openrouter_models import estimate_cost, words_from_duration
from app.services.youtube import YouTubeError, parse_video_id

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("/preview", response_model=schemas.VideoPreview)
async def preview(body: schemas.PreviewRequest, user: UserDep, c: ContainerDep) -> schemas.VideoPreview:
    vid = parse_video_id(body.url)
    if not vid:
        raise AppError("That doesn't look like a YouTube link.", code="invalid_url", status_code=422,
                       details={"field": "url"})

    def blank(reason: str, message: str, **kw) -> schemas.VideoPreview:
        return schemas.VideoPreview(
            video_id=vid, title=kw.get("title", ""), channel_name=kw.get("channel", ""),
            thumbnail_url=kw.get("thumb", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
            duration_seconds=kw.get("duration", 0), chapters=kw.get("chapters", []), transcript_available=False,
            transcript_language=None, eligible=False, ineligible_reason=reason, ineligible_message=message,
            existing_article_url=kw.get("existing"), estimated_cost_usd=None, estimate_model=None,
        )

    try:
        meta = await c.youtube.get_metadata(vid)
    except TransientFetchError:
        return blank("fetch_blocked", "YouTube temporarily blocked the request. Try again in a minute.")
    except YouTubeError as e:
        return blank(e.code, str(e))

    info = {"title": meta["title"], "channel": meta["channel"], "thumb": meta["thumbnail_url"],
            "duration": meta["duration"], "chapters": [schemas.ChapterOut(**ch) for ch in meta["chapters"]]}

    if url := await PgArticleRegistry(c.sessions).existing_url(str(user.id), vid):
        return blank("already_published", "You already turned this video into a post.", existing=url, **info)
    limit = c.settings.max_no_chapter_duration
    if not meta["chapters"] and meta["duration"] > limit:
        return blank("too_long_without_chapters",
                     f"Videos longer than {limit // 60} minutes need YouTube chapters so they can be split into sections.",
                     **info)
    try:
        tr = await c.youtube.get_transcript(vid)
    except TransientFetchError:
        return blank("fetch_blocked", "YouTube temporarily blocked the request. Try again in a minute.", **info)
    except YouTubeError as e:
        return blank(e.code, str(e), **info)

    words = sum(len(s["text"].split()) for s in tr["snippets"]) or words_from_duration(meta["duration"])
    settings = user_settings(user, c.settings)
    estimate = None
    model_id = settings.default_model
    try:
        if model := await c.catalog.get(model_id):
            e = estimate_cost(model, words, await c.catalog.multipliers(user.id))
            estimate = schemas.CostRange(**e)
    except Exception:
        pass  # the estimate is optional; never block the preview on the model catalogue

    return schemas.VideoPreview(
        video_id=vid, title=meta["title"], channel_name=meta["channel"], thumbnail_url=meta["thumbnail_url"],
        duration_seconds=meta["duration"], chapters=info["chapters"], transcript_available=True,
        transcript_language=tr["language"], eligible=True, ineligible_reason=None, existing_article_url=None,
        estimated_cost_usd=estimate, estimate_model=model_id,
    )
