"""Request/response models. These define the OpenAPI spec the frontend's typed client is generated from."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "awaiting_review", "awaiting_publish", "publishing", "completed",
                    "rejected", "failed", "cancelled"]
PendingAction = Literal["draft_review", "publish_approval"]
StepState = Literal["pending", "running", "done", "failed", "skipped", "waiting"]
Attribution = Literal["own_video", "credited"]
IneligibleReason = Literal["no_transcript", "too_long_without_chapters", "already_published", "fetch_blocked",
                           "not_found", "age_restricted"]


class Accepted(BaseModel):
    job_id: str
    status: JobStatus


# ---- videos ----
class PreviewRequest(BaseModel):
    url: str = Field(min_length=5, max_length=500)


class ChapterOut(BaseModel):
    title: str
    start: float
    end: float


class CostRange(BaseModel):
    low: float
    high: float


class VideoPreview(BaseModel):
    video_id: str
    title: str
    channel_name: str
    thumbnail_url: str
    duration_seconds: int
    chapters: list[ChapterOut]
    transcript_available: bool
    transcript_language: str | None
    eligible: bool
    ineligible_reason: IneligibleReason | None
    ineligible_message: str | None = None
    existing_article_url: str | None
    estimated_cost_usd: CostRange | None
    estimate_model: str | None


# ---- jobs ----
class CreateJob(BaseModel):
    video_url: str = Field(min_length=5, max_length=500)
    attribution_mode: Attribution = "credited"
    style_profile_id: str | None = None
    model: str | None = None
    max_revisions: int = Field(2, ge=0, le=3)
    min_faithfulness: float = Field(0.85, ge=0.5, le=1.0)
    budget_usd: float | None = Field(None, gt=0)


class SubItem(BaseModel):
    id: str
    label: str
    state: StepState


class StepOut(BaseModel):
    step: str
    label: str
    state: StepState
    attempt: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    sub_items: list[SubItem] | None = None
    cost_usd: float | None = None


class JobError(BaseModel):
    step: str | None
    code: str
    message: str
    at: str
    retryable: bool
    details: dict | None = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    by_step: dict[str, float] = {}


class JobSummary(BaseModel):
    id: str
    short_id: str
    video_id: str
    video_title: str
    channel_name: str
    thumbnail_url: str
    status: JobStatus
    pending_action: PendingAction | None
    current_step: str | None
    progress_label: str | None
    faithfulness_score: float | None
    revision_count: int
    cost_usd: float
    model: str
    rejection_code: str | None
    created_at: datetime
    updated_at: datetime


class JobConfig(BaseModel):
    model: str
    attribution_mode: Attribution
    style_profile_id: str | None
    max_revisions: int
    min_faithfulness: float


class JobDetail(JobSummary):
    video_url: str
    duration_seconds: int
    has_chapters: bool
    config: JobConfig
    budget_usd: float
    steps: list[StepOut]
    rejection_reason: str | None
    errors: list[JobError]
    usage: Usage
    checkpoint_id: str | None
    current_draft_rev: int | None
    devto_url: str | None
    publish_status: str | None
    started_at: datetime | None
    finished_at: datetime | None


class JobCounts(BaseModel):
    all: int = 0
    in_progress: int = 0
    needs_you: int = 0
    completed: int = 0
    failed: int = 0


class JobList(BaseModel):
    items: list[JobSummary]
    next_cursor: str | None
    counts: JobCounts


class RetryRequest(BaseModel):
    budget_usd: float | None = Field(None, gt=0)


# ---- drafts / quality ----
class DraftVersionOut(BaseModel):
    rev: int
    kind: Literal["auto", "revised", "human_edit", "final"]
    sha256: str
    created_at: str
    char_count: int
    note: str | None = None


class DraftContent(BaseModel):
    rev: int
    kind: str
    markdown: str


class OutlineSectionOut(BaseModel):
    id: str
    heading: str
    start: float
    end: float
    key_points: list[str]


class OutlineOut(BaseModel):
    angle: str | None
    target_reader: str | None
    sections: list[OutlineSectionOut]


class ClaimOut(BaseModel):
    text: str
    supported: bool
    evidence: str
    section: str = ""
    timestamp_seconds: float | None = None


class FactCheckOut(BaseModel):
    faithfulness_score: float | None
    min_faithfulness: float
    quality_scores: dict[str, float]
    claims: list[ClaimOut]
    revision_notes: list[str]
    revision_count: int


# ---- review / publish ----
class ReviewPayload(BaseModel):
    draft_rev: int
    title: str
    title_options: list[str]
    description: str
    tags: list[str]
    faithfulness_score: float | None
    min_faithfulness: float
    quality_scores: dict[str, float] | None
    unsupported_claims: list[str]
    outline: list[OutlineSectionOut]
    angle: str | None
    target_reader: str | None
    revision_count: int
    max_revisions: int
    checkpoint_id: str | None


class ReviewDecision(BaseModel):
    action: Literal["approve", "edit", "revise", "abort"]
    title: str | None = Field(None, max_length=128)
    tags: list[str] | None = Field(None, max_length=4)
    description: str | None = Field(None, max_length=150)
    markdown: str | None = Field(None, max_length=400_000)
    feedback: str | None = Field(None, max_length=4000)
    expected_checkpoint_id: str


class PublishRequestOut(BaseModel):
    title: str
    tags: list[str]
    description: str
    body_char_count: int
    canonical_url: str | None
    proposed_published: bool
    final_rev: int | None
    devto_username: str | None
    attribution_mode: Attribution
    channel_name: str
    checkpoint_id: str | None


class PublishDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    published: bool = False
    message: str | None = Field(None, max_length=1000)
    expected_checkpoint_id: str


class SocialOut(BaseModel):
    linkedin: str = ""
    x: str = ""


class RunSummary(BaseModel):
    total_seconds: int | None
    cost_usd: float
    tokens: int
    revisions: int
    faithfulness_score: float | None


class JobResult(BaseModel):
    devto_url: str | None
    devto_article_id: int | None
    publish_status: str | None
    title: str
    social: SocialOut
    summary: RunSummary


# ---- articles ----
class ArticleOut(BaseModel):
    job_id: str | None
    video_id: str
    title: str
    devto_url: str
    thumbnail_url: str
    publish_status: str
    published_at: datetime


class ArticleList(BaseModel):
    items: list[ArticleOut]
    next_cursor: str | None


# ---- style profiles ----
class StyleProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    examples: list[str] = Field(min_length=1, max_length=3)
    is_default: bool = False


class StyleProfileOut(BaseModel):
    id: str
    name: str
    examples: list[str]
    is_default: bool
    updated_at: str


# ---- me ----
class UserSettings(BaseModel):
    default_model: str
    default_attribution: Attribution = "credited"
    default_max_revisions: int = Field(2, ge=0, le=3)
    default_min_faithfulness: float = Field(0.85, ge=0.5, le=1.0)
    default_budget_usd: float = Field(0.5, gt=0)
    monthly_budget_usd: float = Field(10.0, gt=0)
    default_style_profile_id: str | None = None


class Profile(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    photo_url: str | None
    settings: UserSettings


class IntegrationStatus(BaseModel):
    connected: bool
    last4: str | None
    verified_at: datetime | None
    status: Literal["ok", "invalid", "unknown"]
    username: str | None = None


class Integrations(BaseModel):
    openrouter: IntegrationStatus
    devto: IntegrationStatus


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=300)


class TestResult(BaseModel):
    status: Literal["ok", "invalid", "unknown"]


class DailyUsage(BaseModel):
    date: str
    cost_usd: float
    jobs: int


class ModelUsage(BaseModel):
    model: str
    jobs: int
    cost_usd: float
    tokens: int


class Quota(BaseModel):
    jobs_per_day: int
    used_today: int


class UsageOut(BaseModel):
    period: str
    jobs: int
    cost_usd: float
    tokens: int
    avg_cost_per_post: float | None
    daily: list[DailyUsage]
    by_model: list[ModelUsage]
    quota: Quota


class DashboardStats(BaseModel):
    posts_this_month: int
    avg_faithfulness: float | None
    spend_this_month: float
    monthly_budget_usd: float
    awaiting_you: int
    quota: Quota


class DeleteAccount(BaseModel):
    confirm_email: str


# ---- models ----
class ModelOut(BaseModel):
    id: str
    name: str
    provider: str
    context_length: int
    price_per_mtok_in: float
    price_per_mtok_out: float
    estimate_usd: CostRange | None = None
    over_budget: bool = False
    used_before: bool = False
    is_default: bool = False


class ModelList(BaseModel):
    items: list[ModelOut]
    basis_words: int
    basis: Literal["video", "your_average", "default"]
