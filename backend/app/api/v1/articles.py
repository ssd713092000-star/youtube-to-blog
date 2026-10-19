import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from app.api import schemas
from app.api.deps import ContainerDep, UserDep
from app.api.serialize import decode_cursor, encode_cursor
from app.db.models_app import Article

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=schemas.ArticleList)
async def list_articles(user: UserDep, c: ContainerDep, q: Annotated[str | None, Query(max_length=200)] = None,
                        cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 25
                        ) -> schemas.ArticleList:
    filt = [Article.user_id == user.id]
    if q:
        filt.append(Article.title.ilike(f"%{q}%"))
    if cursor:
        ts, id_ = decode_cursor(cursor)
        filt.append(or_(Article.published_at < ts, and_(Article.published_at == ts, Article.id < uuid.UUID(id_))))
    async with c.sessions() as s:
        rows = (await s.scalars(select(Article).where(*filt)
                                .order_by(Article.published_at.desc(), Article.id.desc()).limit(limit + 1))).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return schemas.ArticleList(
        items=[schemas.ArticleOut(job_id=str(a.job_id) if a.job_id else None, video_id=a.video_id, title=a.title,
                                  devto_url=a.url, thumbnail_url=a.thumbnail_url, publish_status=a.publish_status,
                                  published_at=a.published_at) for a in rows],
        next_cursor=encode_cursor(rows[-1].published_at, str(rows[-1].id)) if more else None,
    )
