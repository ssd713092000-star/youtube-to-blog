import asyncio

from langchain.agents import create_agent
from langgraph.runtime import Runtime

from app.graph import prompts
from app.graph.context import JobContext
from app.graph.drafts import DraftParts, compose, save_draft, section_is_valid
from app.graph.schemas import FactCheck, RevisionPlan
from app.graph.state import BlogState, Claim
from app.graph.tools import make_search_transcript_tool
from app.graph.util import last_ai_text, norm, parse_time, text_of


async def fact_check(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    chapters = await ctx.deps.reader.get_json(state["cleaned_transcript_ref"]["uri"])
    draft = await ctx.deps.reader.get_text(state["draft_ref"]["uri"])

    checker = create_agent(
        model=ctx.llm(0.0), tools=[make_search_transcript_tool(chapters)], system_prompt=prompts.FACT_CHECKER,
        name="fact_checker", checkpointer=False,
    )
    result = await checker.ainvoke({"messages": [{"role": "user", "content": f"<draft>\n{draft}\n</draft>"}]})
    verdict = await ctx.structured(FactCheck, 0.0).ainvoke(prompts.fact_check_structure(last_ai_text(result)))

    claims: list[Claim] = [
        Claim(text=c.text, supported=c.supported, evidence=c.evidence, section=c.section,
              timestamp_seconds=parse_time(c.timestamp))
        for c in verdict.claims
    ]
    score = (sum(c["supported"] for c in claims) / len(claims)) if claims else 1.0  # computed, not self-reported
    notes = list(verdict.revision_notes)
    return {
        "claims": claims,
        "faithfulness_score": round(score, 2),
        "quality_scores": {"readability": verdict.readability, "structure": verdict.structure},
        "revision_notes": notes,
        "status": "fact_checked",
    }


def route_after_fact_check(state: BlogState):
    ok = state["faithfulness_score"] >= state.get("min_faithfulness", 0.85)
    if ok or state.get("revision_count", 0) >= state.get("max_revisions", 2):
        return "prepare_metadata"  # good enough, or out of automatic retries -> let the human decide
    return "revise_draft"


def _match_target(target: str, headings: dict[str, int]) -> str | int | None:
    t = norm(target)
    if t in ("intro", "introduction"):
        return "intro"
    if t in ("tldr", "tl dr", "summary"):
        return "tldr"
    if t in ("conclusion", "outro"):
        return "conclusion"
    if t in headings:
        return headings[t]
    for h, i in headings.items():  # tolerate small heading paraphrases
        if t and (t in h or h in t):
            return i
    return None


async def revise_draft(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    """Revise only the parts that need it (per section), instead of rewriting the whole post in one call
    and risking dropped sections or links on long videos."""
    ctx = runtime.context
    parts: DraftParts = await ctx.deps.reader.get_json(state["draft_parts_ref"]["uri"])
    chapters = await ctx.deps.reader.get_json(state["cleaned_transcript_ref"]["uri"])
    outline = {s["id"]: s for s in state.get("outline", [])}
    feedback = state.get("reviewer_feedback")
    unsupported = [c for c in state.get("claims", []) if not c["supported"]]

    headings = {norm(s["heading"]): i for i, s in enumerate(parts["sections"])}
    targets = [s["heading"] for s in parts["sections"]] + ["intro", "tldr", "conclusion"]
    plan = await ctx.structured(RevisionPlan, 0.0).ainvoke(prompts.revision_plan(
        targets, [f"[{c['section'] or '?'}] {c['text']}" for c in unsupported], state.get("revision_notes", []), feedback
    ))

    work: dict[str | int, list[str]] = {}
    for item in plan.items:
        if (key := _match_target(item.target, headings)) is not None:
            work.setdefault(key, []).append(item.instruction)
    for c in unsupported:  # never let an unsupported claim slip through an incomplete plan
        key = _match_target(c["section"], headings) if c["section"] else None
        if key is not None and not any(c["text"] in i for i in work.get(key, [])):
            work.setdefault(key, []).append(f"Remove or correct this unsupported claim: {c['text']}")

    notes: list[str] = []

    async def revise_one(key: str | int, instructions: list[str]) -> None:
        if isinstance(key, int):
            sec = parts["sections"][key]
            src = outline.get(sec["id"])
            excerpt = "\n\n".join(chapters[i]["text"] for i in src["chapter_idxs"]) if src else None
            out = text_of((await ctx.llm().ainvoke(prompts.revise_part("section", instructions, sec["markdown"], excerpt))).content).strip()
            if section_is_valid(sec["markdown"], out):
                sec["markdown"] = out
            else:
                notes.append(f"Revision of '{sec['heading']}' dropped its heading or code blocks and was discarded.")
        elif key == "tldr":
            current = "\n".join(f"- {b}" for b in parts["tldr"])
            out = text_of((await ctx.llm().ainvoke(prompts.revise_part("TL;DR bullet list", instructions, current, None))).content)
            bullets = [ln.lstrip("-*• ").strip() for ln in out.splitlines() if ln.strip()]
            if 2 <= len(bullets) <= 7:
                parts["tldr"] = bullets
        else:
            out = text_of((await ctx.llm().ainvoke(prompts.revise_part(key, instructions, parts[key], None))).content).strip()
            if out and not out.startswith("#"):
                parts[key] = out

    await asyncio.gather(*(revise_one(k, v) for k, v in work.items()))

    note = f"Revised {len(work)} part(s)" + (" from reviewer feedback" if feedback else "")
    update = await save_draft(ctx.deps.blobs, state, parts, compose(parts), "revised", note)
    return {
        **update,
        "revision_count": state.get("revision_count", 0) + 1,
        "reviewer_feedback": None,
        "review_status": "pending",
        "status": "revised",
        "errors": notes,
    }
