from typing import Annotated

from fastapi import APIRouter, Header

from app.api import schemas
from app.api.deps import ContainerDep, JobDep, UserDep, job_state
from app.api.jobflow import advance
from app.core.errors import AppError, Conflict, NotFound
from app.db.models_app import Job
from app.graph import prompts
from app.graph.context import JobContext
from app.graph.drafts import find_version
from app.graph.schemas import Social
from app.services.blobs import job_path
from app.services.idempotency import request_hash, run_idempotent

router = APIRouter(prefix="/jobs/{job_id}", tags=["review"])


def _outline(values: dict) -> list[schemas.OutlineSectionOut]:
    return [schemas.OutlineSectionOut(id=s["id"], heading=s["heading"], start=s["start"], end=s["end"],
                                      key_points=s.get("key_points", [])) for s in values.get("outline", [])]


def _pending_value(snap, kind: str) -> dict:
    for it in snap.interrupts:
        if isinstance(it.value, dict) and it.value.get("kind") == kind:
            return it.value
    raise Conflict("This job isn't waiting for that action.", code="not_pending")


# ---------------------------------------------------------------- drafts / quality
@router.get("/drafts", response_model=list[schemas.DraftVersionOut])
async def list_drafts(job: JobDep, c: ContainerDep) -> list[schemas.DraftVersionOut]:
    snap = await job_state(c, job.id)
    return [schemas.DraftVersionOut(rev=v["rev"], kind=v["kind"], sha256=v["ref"]["sha256"],
                                    created_at=v["created_at"], char_count=v["ref"]["size"], note=v.get("note"))
            for v in snap.values.get("draft_versions", [])]


@router.get("/drafts/{rev}", response_model=schemas.DraftContent)
async def get_draft(rev: int, job: JobDep, c: ContainerDep) -> schemas.DraftContent:
    snap = await job_state(c, job.id)
    ref = find_version(snap.values, rev)
    if ref is None:
        raise NotFound("Draft version not found.")
    kind = next(v["kind"] for v in snap.values["draft_versions"] if v["rev"] == rev)
    return schemas.DraftContent(rev=rev, kind=kind, markdown=await c.blobs.get_text(ref["uri"]))


@router.get("/outline", response_model=schemas.OutlineOut)
async def outline(job: JobDep, c: ContainerDep) -> schemas.OutlineOut:
    v = (await job_state(c, job.id)).values
    return schemas.OutlineOut(angle=v.get("angle"), target_reader=v.get("target_reader"), sections=_outline(v))


@router.get("/fact-check", response_model=schemas.FactCheckOut)
async def fact_check(job: JobDep, c: ContainerDep) -> schemas.FactCheckOut:
    v = (await job_state(c, job.id)).values
    return schemas.FactCheckOut(
        faithfulness_score=v.get("faithfulness_score"), min_faithfulness=v.get("min_faithfulness", 0.85),
        quality_scores=v.get("quality_scores") or {}, claims=[schemas.ClaimOut(**cl) for cl in v.get("claims", [])],
        revision_notes=v.get("revision_notes", []), revision_count=v.get("revision_count", 0),
    )


# ---------------------------------------------------------------- HITL #1: draft review
@router.get("/review", response_model=schemas.ReviewPayload)
async def get_review(job: JobDep, c: ContainerDep) -> schemas.ReviewPayload:
    snap = await job_state(c, job.id)
    p = _pending_value(snap, "draft_review")
    v = snap.values
    return schemas.ReviewPayload(
        draft_rev=p["draft_rev"], title=p["title"], title_options=p.get("title_options", []),
        description=p["description"], tags=p["tags"], faithfulness_score=p.get("faithfulness_score"),
        min_faithfulness=v.get("min_faithfulness", 0.85), quality_scores=p.get("quality_scores"),
        unsupported_claims=p.get("unsupported_claims", []), outline=_outline(v), angle=p.get("angle"),
        target_reader=p.get("target_reader"), revision_count=v.get("revision_count", 0),
        max_revisions=v.get("max_revisions", 2), checkpoint_id=job.checkpoint_id,
    )


@router.post("/review", status_code=202, response_model=schemas.Accepted)
async def submit_review(body: schemas.ReviewDecision, job: JobDep, user: UserDep, c: ContainerDep,
                        idempotency_key: Annotated[str | None, Header()] = None) -> schemas.Accepted:
    async def do() -> dict:
        resume: dict = {"action": body.action}
        for k in ("title", "tags", "description", "feedback"):
            if (val := getattr(body, k)) is not None:
                resume[k] = val
        if body.action == "edit":
            if not body.markdown or not body.markdown.strip():
                raise AppError("Edited markdown is required.", code="markdown_required", status_code=422,
                               details={"field": "markdown"})
            ref = await c.blobs.put_text(
                job_path(str(user.id), str(job.id), "human_edit", "edit", body.markdown), body.markdown
            )
            resume["draft_ref"] = ref
        if body.action == "revise" and not (body.feedback or "").strip():
            raise AppError("Tell the writer what to change.", code="feedback_required", status_code=422,
                           details={"field": "feedback"})
        return await advance(c, job.id, kind="resume", new_status="running", resume=resume,
                             expect_pending="draft_review", expect_checkpoint=body.expected_checkpoint_id)

    _, resp = await run_idempotent(c.sessions, user.id, idempotency_key,
                                   request_hash(f"review/{job.id}", body.model_dump()), do)
    return schemas.Accepted(**resp)


# ---------------------------------------------------------------- HITL #2: publish approval
@router.get("/publish-request", response_model=schemas.PublishRequestOut)
async def publish_request(job: JobDep, user: UserDep, c: ContainerDep) -> schemas.PublishRequestOut:
    snap = await job_state(c, job.id)
    p = _pending_value(snap, "publish_approval")
    devto = (await c.credentials.status(user.id))["devto"]
    return schemas.PublishRequestOut(
        title=p["title"], tags=p["tags"], description=p["description"], body_char_count=p["body_char_count"],
        canonical_url=p.get("canonical_url"), proposed_published=p.get("proposed_published", False),
        final_rev=p.get("final_rev"), devto_username=devto.get("username"),
        attribution_mode=snap.values.get("attribution_mode", "credited"),
        channel_name=snap.values.get("channel_name", ""), checkpoint_id=job.checkpoint_id,
    )


@router.post("/publish", status_code=202, response_model=schemas.Accepted)
async def submit_publish(body: schemas.PublishDecision, job: JobDep, user: UserDep, c: ContainerDep,
                         idempotency_key: Annotated[str | None, Header()] = None) -> schemas.Accepted:
    async def do() -> dict:
        if body.decision == "reject":
            resume = {"type": "reject", "message": body.message}
            status = "running"
        else:  # "edit" kept for compatibility: the only editable arg is `published`
            resume = {"type": "approve", "published": body.published}
            status = "publishing"
        return await advance(c, job.id, kind="resume", new_status=status, resume=resume,
                             expect_pending="publish_approval", expect_checkpoint=body.expected_checkpoint_id)

    _, resp = await run_idempotent(c.sessions, user.id, idempotency_key,
                                   request_hash(f"publish/{job.id}", body.model_dump()), do)
    return schemas.Accepted(**resp)


# ---------------------------------------------------------------- result
def _result(job: Job, title: str) -> schemas.JobResult:
    r = job.result or {}
    total = int((job.finished_at - job.started_at).total_seconds()) if job.finished_at and job.started_at else None
    return schemas.JobResult(
        devto_url=r.get("devto_url"), devto_article_id=r.get("devto_article_id"),
        publish_status=r.get("publish_status"), title=title, social=schemas.SocialOut(**(r.get("social") or {})),
        summary=schemas.RunSummary(total_seconds=total, cost_usd=round(job.cost_usd, 4),
                                   tokens=job.prompt_tokens + job.completion_tokens, revisions=job.revision_count,
                                   faithfulness_score=job.faithfulness_score),
    )


@router.get("/result", response_model=schemas.JobResult)
async def result(job: JobDep, c: ContainerDep) -> schemas.JobResult:
    v = (await job_state(c, job.id)).values
    return _result(job, v.get("final_title") or job.video_title)


@router.post("/social/regenerate", response_model=schemas.SocialOut)
async def regenerate_social(job: JobDep, user: UserDep, c: ContainerDep) -> schemas.SocialOut:
    if not job.devto_url:
        raise Conflict("The post isn't published yet.", code="not_published")
    v = (await job_state(c, job.id)).values
    key = await c.credentials.get_plaintext(user.id, "openrouter")
    ctx = JobContext(job_id=str(job.id), user_id=str(user.id), model=job.config.get("model", ""),
                     deps=c.runner.deps, openrouter_key=key)
    s = await ctx.structured(Social, 0.8).ainvoke(
        prompts.social(job.devto_url, v.get("final_title", ""), v.get("devto_description", ""))
    )
    out = schemas.SocialOut(linkedin=s.linkedin, x=s.x)
    async with c.sessions.begin() as sess:
        j = await sess.get(Job, job.id)
        j.result = {**(j.result or {}), "social": out.model_dump()}
    return out
