"""Postgres implementations of the graph's ports (article registry, publish ledger, usage sink)."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models_app import Article, Job, PublishAttempt, UsageLedger
from app.graph.context import PublishAttemptRow
from app.services.usage import UsageRecord


class PgArticleRegistry:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._s = sessions

    async def existing_url(self, user_id: str, video_id: str) -> str | None:
        async with self._s() as s:
            return await s.scalar(
                select(Article.url).where(Article.user_id == uuid.UUID(user_id), Article.video_id == video_id)
            )

    async def record(self, *, user_id: str, job_id: str, video_id: str, devto_article_id: int, url: str,
                     title: str, thumbnail_url: str, publish_status: str) -> None:
        async with self._s.begin() as s:
            await s.execute(
                insert(Article)
                .values(user_id=uuid.UUID(user_id), job_id=uuid.UUID(job_id), video_id=video_id,
                        devto_article_id=devto_article_id, url=url, title=title, thumbnail_url=thumbnail_url,
                        publish_status=publish_status)
                .on_conflict_do_nothing(constraint="uq_articles_user_video")
            )


class PgPublishLedger:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._s = sessions

    async def begin(self, job_id: str, published: bool) -> PublishAttemptRow:
        jid = uuid.UUID(job_id)
        async with self._s.begin() as s:
            inserted = await s.scalar(
                insert(PublishAttempt).values(job_id=jid, state="in_flight", published=published)
                .on_conflict_do_nothing().returning(PublishAttempt.job_id)
            )
            if inserted:
                return PublishAttemptRow(state="in_flight", is_new=True, published=published)
            row = await s.get(PublishAttempt, jid, with_for_update=True)
            assert row is not None
            out = PublishAttemptRow(state=row.state, is_new=False, devto_article_id=row.devto_article_id,
                                    url=row.url, published=row.published)
            if row.state != "succeeded":
                row.state, row.published = "in_flight", published
            return out

    async def succeed(self, job_id: str, devto_article_id: int, url: str, published: bool) -> None:
        async with self._s.begin() as s:
            await s.execute(update(PublishAttempt).where(PublishAttempt.job_id == uuid.UUID(job_id)).values(
                state="succeeded", devto_article_id=devto_article_id, url=url, published=published, error=None))

    async def fail(self, job_id: str, error: str) -> None:
        async with self._s.begin() as s:
            await s.execute(update(PublishAttempt).where(PublishAttempt.job_id == uuid.UUID(job_id)).values(
                state="failed", error=error[:2000]))


class PgUsageSink:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], job_id: uuid.UUID, user_id: uuid.UUID):
        self._s = sessions
        self._job_id = job_id
        self._user_id = user_id

    async def record(self, rec: UsageRecord) -> float:
        async with self._s.begin() as s:
            s.add(UsageLedger(job_id=self._job_id, user_id=self._user_id, step=rec.step, model=rec.model,
                              prompt_tokens=rec.prompt_tokens, completion_tokens=rec.completion_tokens,
                              cost_usd=rec.cost_usd))
            total = await s.scalar(
                update(Job).where(Job.id == self._job_id).values(
                    cost_usd=Job.cost_usd + rec.cost_usd,
                    prompt_tokens=Job.prompt_tokens + rec.prompt_tokens,
                    completion_tokens=Job.completion_tokens + rec.completion_tokens,
                ).returning(Job.cost_usd)
            )
        return float(total or 0.0)
