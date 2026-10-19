from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.graph import prompts
from app.graph.context import JobContext
from app.graph.drafts import save_draft
from app.graph.schemas import Metadata
from app.graph.state import BlogState, DraftVersion
from app.graph.util import clean_tags, now_iso


async def prepare_metadata(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    draft = await ctx.deps.reader.get_text(state["draft_ref"]["uri"])
    update: dict = {}
    if not state.get("title_locked"):  # keep a title/tags the reviewer already chose
        meta = await ctx.structured(Metadata).ainvoke(prompts.metadata(state["angle"], state.get("tags", []), draft))
        update = {
            "title_options": meta.title_options[:3],
            "final_title": (meta.title_options[0] if meta.title_options else state["title"])[:128],
            "devto_description": meta.description[:150],
            "devto_tags": clean_tags(meta.tags or state.get("tags", [])),
        }

    url = state["video_url"]
    if state.get("attribution_mode") == "own_video":
        credit = f"> This post is the written version of my video. [Watch it on YouTube]({url})."
    else:
        credit = (
            f"> This post is an AI-assisted written adaptation of a video by **{state.get('channel_name') or 'the creator'}**. "
            f"All ideas belong to the original creator. [Watch the original on YouTube]({url})."
        )
    final_md = "{% embed " + url + " %}\n\n" + credit + "\n\n" + draft
    saved = await save_draft(ctx.deps.blobs, state, None, final_md, "final")
    return {
        **update,
        **saved,
        "final_ref": saved["draft_versions"][-1]["ref"],
        "review_status": "pending",
        "status": "ready_for_review",
    }


async def human_review(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    """HITL #1. The interrupt payload carries refs only; the API serves the markdown.

    Resume value: {action: approve|edit|revise|abort, title?, tags?, description?, draft_ref?, feedback?}
    For `edit`, the API has already written the edited markdown to GCS and passes its BlobRef."""
    unsupported = [c["text"] for c in state.get("claims", []) if not c["supported"]]
    decision = interrupt({
        "kind": "draft_review",
        "draft_rev": state.get("draft_rev"),
        "title": state["final_title"],
        "title_options": state.get("title_options", []),
        "description": state["devto_description"],
        "tags": state["devto_tags"],
        "faithfulness_score": state.get("faithfulness_score"),
        "quality_scores": state.get("quality_scores"),
        "unsupported_claims": unsupported,
        "angle": state.get("angle"),
        "target_reader": state.get("target_reader"),
    })
    action = decision.get("action", "approve")

    overrides: dict = {}
    if decision.get("title"):
        overrides["final_title"] = str(decision["title"])[:128]
    if decision.get("tags"):
        overrides["devto_tags"] = clean_tags(decision["tags"])
    if decision.get("description"):
        overrides["devto_description"] = str(decision["description"])[:150]
    if overrides:
        overrides["title_locked"] = True

    if action == "approve":
        return {**overrides, "review_status": "approved"}
    if action == "edit":
        ref = decision["draft_ref"]
        versions = list(state.get("draft_versions", []))
        rev = len(versions) + 1
        versions.append(DraftVersion(rev=rev, kind="human_edit", ref=ref, created_at=now_iso(), note="Edited by reviewer"))
        return {**overrides, "review_status": "edited", "final_ref": ref, "draft_versions": versions, "draft_rev": rev}
    if action == "revise":
        feedback = (decision.get("feedback") or "").strip()
        if runtime.store is not None and feedback:
            await runtime.store.aput(
                ("users", state["user_id"], "feedback"), f"{state['job_id']}-{state.get('draft_rev', 0)}",
                {"feedback": feedback[:2000], "created_at": now_iso(), "job_id": state["job_id"]},
            )
        return {**overrides, "review_status": "revise", "reviewer_feedback": feedback}
    return {"review_status": "rejected", "status": "aborted_by_reviewer"}


def route_after_review(state: BlogState):
    return {"approved": "publish", "edited": "publish", "revise": "revise_draft"}.get(state["review_status"], END)
