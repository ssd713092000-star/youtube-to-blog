"""Tables in the `tube2dev_app` database. LangGraph's checkpoint and store tables live here too
(created by `AsyncPostgresSaver.setup()` / `AsyncPostgresStore.setup()`), but are not modelled."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AppBase(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(AppBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Job(AppBase):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_updated", "user_id", "updated_at"),
        Index("ix_jobs_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    video_id: Mapped[str] = mapped_column(String(16), nullable=False)
    video_url: Mapped[str] = mapped_column(Text, nullable=False)
    video_title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    channel_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    has_chapters: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    transcript_words: Mapped[int | None] = mapped_column(Integer)

    # queued | running | awaiting_review | awaiting_publish | publishing | completed | rejected | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued")
    pending_action: Mapped[str | None] = mapped_column(String(32))
    current_step: Mapped[str | None] = mapped_column(String(64))
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    faithfulness_score: Mapped[float | None] = mapped_column(Float)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_draft_rev: Mapped[int | None] = mapped_column(Integer)

    budget_usd: Mapped[float] = mapped_column(Float, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejection_code: Mapped[str | None] = mapped_column(String(64))
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")  # devto + social
    devto_url: Mapped[str | None] = mapped_column(Text)
    publish_status: Mapped[str | None] = mapped_column(String(32))

    checkpoint_id: Mapped[str | None] = mapped_column(String(64))
    segment: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The run payload of the segment in flight, kept until the runner finishes it, so a segment
    # interrupted by a process restart can be re-dispatched with the same resume decision.
    pending_run: Mapped[dict | None] = mapped_column(JSONB)
    purged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JobEvent(AppBase):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = _now()


class Article(AppBase):
    """Replaces the notebook's published_videos.json registry."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("user_id", "video_id", name="uq_articles_user_video"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    video_id: Mapped[str] = mapped_column(String(16), nullable=False)
    devto_article_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    publish_status: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = _now()


class PublishAttempt(AppBase):
    """One row per job. Makes the dev.to POST idempotent across worker crashes and retries."""

    __tablename__ = "publish_attempts"

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)  # in_flight | succeeded | failed
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    devto_article_id: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UsageLedger(AppBase):
    __tablename__ = "usage_ledger"
    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = _now()


class IdempotencyKey(AppBase):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class ModelCache(AppBase):
    __tablename__ = "model_cache"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[list] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = _now()
