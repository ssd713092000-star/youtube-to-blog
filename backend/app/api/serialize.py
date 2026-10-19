import base64
import json
from datetime import datetime

from app.api import schemas
from app.db.models_app import Job
from app.graph.runner import STEP_LABELS, initial_steps

STATUS_GROUPS = {
    "in_progress": ("queued", "running", "publishing"),
    "needs_you": ("awaiting_review", "awaiting_publish"),
    "completed": ("completed",),
    "failed": ("failed",),
    "rejected": ("rejected", "cancelled"),
}


def short_id(job: Job) -> str:
    return f"job_{job.id.hex[:6]}"


def progress_label(job: Job) -> str | None:
    """'Running · write 3/6', 'Failed · fact_check', 'Rejected · no transcript' (dashboard rows)."""
    if job.status in ("running", "publishing", "queued"):
        step = next((s for s in job.steps if s["step"] == job.current_step), None)
        if step and step.get("sub_items"):
            done = sum(1 for x in step["sub_items"] if x["state"] == "done")
            return f"write {done}/{len(step['sub_items'])}"
        return STEP_LABELS.get(job.current_step or "", None) if job.current_step else None
    if job.status == "failed":
        return (job.errors[-1].get("step") if job.errors else None) or job.current_step
    if job.status == "rejected":
        return (job.rejection_code or "").replace("_", " ") or None
    if job.status == "completed":
        return {"published": "public", "saved_as_draft": "draft"}.get(job.publish_status or "", None)
    return None


def job_summary(job: Job) -> schemas.JobSummary:
    return schemas.JobSummary(
        id=str(job.id), short_id=short_id(job), video_id=job.video_id, video_title=job.video_title,
        channel_name=job.channel_name, thumbnail_url=job.thumbnail_url, status=job.status,
        pending_action=job.pending_action, current_step=job.current_step, progress_label=progress_label(job),
        faithfulness_score=job.faithfulness_score, revision_count=job.revision_count, cost_usd=round(job.cost_usd, 4),
        model=job.config.get("model", ""), rejection_code=job.rejection_code,
        created_at=job.created_at, updated_at=job.updated_at,
    )


def job_detail(job: Job, by_step: dict[str, float]) -> schemas.JobDetail:
    steps = job.steps or initial_steps()
    return schemas.JobDetail(
        **job_summary(job).model_dump(),
        video_url=job.video_url, duration_seconds=job.duration_seconds, has_chapters=job.has_chapters,
        config=schemas.JobConfig(
            model=job.config.get("model", ""), attribution_mode=job.config.get("attribution_mode", "credited"),
            style_profile_id=job.config.get("style_profile_id"), max_revisions=job.config.get("max_revisions", 2),
            min_faithfulness=job.config.get("min_faithfulness", 0.85),
        ),
        budget_usd=job.budget_usd,
        steps=[schemas.StepOut(**s, cost_usd=round(by_step.get(s["step"], 0.0), 5) or None) for s in steps],
        rejection_reason=job.rejection_reason,
        errors=[schemas.JobError(**e) for e in job.errors],
        usage=schemas.Usage(prompt_tokens=job.prompt_tokens, completion_tokens=job.completion_tokens,
                            cost_usd=round(job.cost_usd, 5), by_step={k: round(v, 5) for k, v in by_step.items()}),
        checkpoint_id=job.checkpoint_id, current_draft_rev=job.current_draft_rev, devto_url=job.devto_url,
        publish_status=job.publish_status, started_at=job.started_at, finished_at=job.finished_at,
    )


def encode_cursor(ts: datetime, id_: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([ts.isoformat(), id_]).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    ts, id_ = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return datetime.fromisoformat(ts), id_
