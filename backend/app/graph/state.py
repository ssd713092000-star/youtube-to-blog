"""Graph state. Large text (transcripts, sections, drafts) lives in GCS; state only holds BlobRefs,
so every checkpoint stays a few KB no matter how long the video is."""

import operator
from typing import Annotated, Literal, TypedDict

from app.services.blobs import BlobRef


class ChapterSpan(TypedDict):
    title: str
    start: float
    end: float


class OutlineSection(TypedDict):
    id: str
    heading: str
    chapter_idxs: list[int]
    start: float
    end: float
    key_points: list[str]


class SectionDraft(TypedDict):
    section_id: str
    idx: int
    heading: str
    ref: BlobRef
    start: float
    timestamp_link: str


class Claim(TypedDict):
    text: str
    supported: bool
    evidence: str
    section: str
    timestamp_seconds: float | None


class DraftVersion(TypedDict):
    rev: int
    kind: Literal["auto", "revised", "human_edit", "final"]
    ref: BlobRef
    created_at: str
    note: str | None


class SectionTask(TypedDict):
    """Payload for each parallel write_section branch. Refs only, no transcript text."""

    idx: int
    section: OutlineSection
    cleaned_transcript_ref: BlobRef
    user_id: str
    job_id: str
    video_id: str
    angle: str
    target_reader: str
    glossary: list[str]
    style_profile_id: str | None


class BlogState(TypedDict, total=False):
    # input
    job_id: str
    user_id: str
    video_id: str
    video_url: str
    attribution_mode: Literal["own_video", "credited"]
    style_profile_id: str | None
    max_revisions: int
    min_faithfulness: float

    # ingest
    title: str
    description: str
    channel_name: str
    duration: int
    has_chapters: bool
    thumbnail_url: str
    transcript_language: str
    transcript_words: int
    chapter_index: list[ChapterSpan]
    transcript_ref: BlobRef
    rejection_reason: str | None
    rejection_code: str | None

    # cleaning / planning
    glossary: list[str]
    cleaned_transcript_ref: BlobRef
    angle: str
    target_reader: str
    outline: list[OutlineSection]
    tags: list[str]

    # writing
    section_drafts: Annotated[list[SectionDraft], operator.add]
    draft_parts_ref: BlobRef
    draft_ref: BlobRef
    draft_rev: int
    draft_versions: list[DraftVersion]

    # quality loop
    claims: list[Claim]
    faithfulness_score: float
    quality_scores: dict[str, float]
    revision_notes: list[str]
    revision_count: int

    # dev.to metadata
    title_options: list[str]
    final_title: str
    devto_description: str
    devto_tags: list[str]
    canonical_url: str | None
    final_ref: BlobRef
    title_locked: bool

    # human review
    review_status: Literal["pending", "approved", "edited", "revise", "rejected"]
    reviewer_feedback: str | None

    # publish
    devto_article_id: int | None
    devto_url: str | None
    publish_status: str | None
    social_snippets: dict[str, str]

    errors: Annotated[list[str], operator.add]
    status: str
