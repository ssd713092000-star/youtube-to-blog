import logging

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.graph import prompts
from app.graph.context import JobContext
from app.graph.schemas import Social
from app.graph.state import BlogState
from app.services.devto import DevtoRejected

log = logging.getLogger(__name__)


async def publish(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    """HITL #2, then an idempotent dev.to POST.

    The notebook used an LLM agent + HumanInTheLoopMiddleware just to call one tool. Here the human
    decision is a plain interrupt and the POST is deterministic code: cheaper, no model in the publish
    path (so transcript content can't steer it), and safe to retry through the publish_attempts ledger.

    Resume value: {type: approve|reject, published?: bool, message?: str}"""
    ctx = runtime.context
    decision = interrupt({
        "kind": "publish_approval",
        "title": state["final_title"],
        "tags": state["devto_tags"],
        "description": state["devto_description"],
        "body_char_count": state["final_ref"]["size"],
        "canonical_url": state.get("canonical_url"),
        "proposed_published": False,
        "final_rev": state.get("draft_rev"),
    })
    if decision.get("type") == "reject":
        return {"publish_status": "not_published", "status": "publish_rejected",
                "reviewer_feedback": decision.get("message")}

    published = bool(decision.get("published", False))
    job_id = state["job_id"]
    ledger = ctx.deps.publish_ledger
    attempt = await ledger.begin(job_id, published)

    if attempt.state == "succeeded" and attempt.devto_article_id and attempt.url:
        article_id, url, published = attempt.devto_article_id, attempt.url, attempt.published
    else:
        devto = ctx.deps.devto_factory(ctx.devto_key)
        existing = None
        if not attempt.is_new:
            # A previous attempt may have reached dev.to before the worker died. Look before posting again.
            existing = await devto.find_my_article(state["final_title"])
        if existing:
            article_id, url = existing["id"], existing.get("url") or existing.get("canonical_url")
            published = bool(existing.get("published", published))
        else:
            body = await ctx.deps.reader.get_text(state["final_ref"]["uri"])
            article = {
                "title": state["final_title"],
                "body_markdown": body,
                "published": published,
                "tags": state["devto_tags"],
                "description": state["devto_description"],
            }
            if state.get("canonical_url"):
                article["canonical_url"] = state["canonical_url"]
            try:
                data = await devto.create_article(article)
            except DevtoRejected as e:
                await ledger.fail(job_id, str(e))
                raise
            article_id, url, published = data["id"], data["url"], bool(data.get("published", published))
        await ledger.succeed(job_id, article_id, url, published)

    return {
        "devto_article_id": article_id,
        "devto_url": url,
        "publish_status": "published" if published else "saved_as_draft",
        "status": "published",
    }


def route_after_publish(state: BlogState):
    return "social_and_store" if state.get("devto_url") else END


async def social_and_store(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    await ctx.deps.articles.record(
        user_id=state["user_id"], job_id=state["job_id"], video_id=state["video_id"],
        devto_article_id=state["devto_article_id"], url=state["devto_url"], title=state["final_title"],
        thumbnail_url=state.get("thumbnail_url", ""), publish_status=state["publish_status"],
    )
    try:
        s = await ctx.structured(Social, 0.6).ainvoke(
            prompts.social(state["devto_url"], state["final_title"], state["devto_description"])
        )
        snippets = {"linkedin": s.linkedin, "x": s.x}
        errors: list[str] = []
    except Exception as e:  # the article is already live; social copy is a nice-to-have
        log.warning("social generation failed: %s", e)
        snippets, errors = {"linkedin": "", "x": ""}, [f"Social posts could not be generated: {type(e).__name__}"]
    return {"social_snippets": snippets, "status": "done", "errors": errors}
