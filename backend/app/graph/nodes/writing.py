import json

from langchain.agents import create_agent
from langgraph.runtime import Runtime
from langgraph.types import Send

from app.graph import prompts
from app.graph.context import JobContext
from app.graph.drafts import DraftParts, SectionPart, compose, save_draft
from app.graph.schemas import Framing, Glossary, Outline, OutlineSectionModel
from app.graph.state import BlogState, OutlineSection, SectionTask
from app.graph.tools import validate_code_syntax
from app.graph.util import clean_tags, fmt_time, last_ai_text, split_words, text_of, yt_link
from app.services.blobs import job_path


async def clean_transcript(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    chapters = await ctx.deps.reader.get_json(state["transcript_ref"]["uri"])

    glossary = (await ctx.structured(Glossary).ainvoke(prompts.glossary(state["title"], state["description"]))).terms

    batch, owners = [], []
    for ci, ch in enumerate(chapters):
        for piece in split_words(ch["text"], 2500):  # keep each LLM call a manageable size
            batch.append(prompts.clean_chunk(glossary, piece))
            owners.append(ci)
    outputs = await ctx.llm().abatch(batch, config={"max_concurrency": 4})

    texts: list[list[str]] = [[] for _ in chapters]
    for ci, out in zip(owners, outputs, strict=True):
        texts[ci].append(text_of(out.content).strip())
    cleaned = [{**ch, "text": " ".join(texts[i])} for i, ch in enumerate(chapters)]

    body = json.dumps(cleaned, ensure_ascii=False)
    ref = await ctx.deps.blobs.put_text(
        job_path(state["user_id"], state["job_id"], "transcript", "cleaned", body, "json"), body, "application/json"
    )
    return {"glossary": glossary, "cleaned_transcript_ref": ref, "status": "cleaned"}


async def plan_outline(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    chapters = await ctx.deps.reader.get_json(state["cleaned_transcript_ref"]["uri"])
    overview = "\n".join(
        f"[{i}] {c['title']} ({fmt_time(c['start'])}-{fmt_time(c['end'])}): {' '.join(c['text'].split()[:60])}..."
        for i, c in enumerate(chapters)
    )
    plan = await ctx.structured(Outline).ainvoke(prompts.outline(state["title"], overview))

    valid = [s for s in plan.sections if s.chapter_idxs and all(0 <= i < len(chapters) for i in s.chapter_idxs)]
    if not valid:  # fallback: one section per chapter
        valid = [OutlineSectionModel(heading=c["title"], chapter_idxs=[i], key_points=[]) for i, c in enumerate(chapters)]

    outline: list[OutlineSection] = []
    for n, s in enumerate(valid):
        idxs = sorted(set(s.chapter_idxs))
        outline.append({
            "id": f"sec_{n:02d}",
            "heading": s.heading,
            "chapter_idxs": idxs,
            "start": chapters[idxs[0]]["start"],
            "end": chapters[idxs[-1]]["end"],
            "key_points": s.key_points,
        })
    return {
        "angle": plan.angle,
        "target_reader": plan.target_reader,
        "tags": clean_tags(plan.tags),
        "outline": outline,
        "status": "planned",
    }


def fan_out_sections(state: BlogState):
    """One small task per section so they are written in parallel. Only refs travel in the payload."""
    return [
        Send("write_section", SectionTask(
            idx=n,
            section=sec,
            cleaned_transcript_ref=state["cleaned_transcript_ref"],
            user_id=state["user_id"],
            job_id=state["job_id"],
            video_id=state["video_id"],
            angle=state["angle"],
            target_reader=state["target_reader"],
            glossary=state["glossary"],
            style_profile_id=state.get("style_profile_id"),
        ))
        for n, sec in enumerate(state["outline"])
    ]


async def _style_and_preferences(runtime: Runtime[JobContext], user_id: str, profile_id: str | None) -> tuple[str, str]:
    store = runtime.store
    style = prefs = ""
    if store is None:
        return style, prefs
    if profile_id:
        item = await store.aget(("users", user_id, "style_profiles"), profile_id)
        examples = (item.value.get("examples") if item else None) or []
        if examples:
            style = "\n\nMatch the voice of these example posts by the author:\n" + "\n---\n".join(e[:4000] for e in examples[:3])
    feedback = await store.asearch(("users", user_id, "feedback"), limit=5)
    if feedback:
        prefs = "\n\nThe author asked for these changes on past posts; follow them where relevant:\n" + "\n".join(
            f"- {f.value.get('feedback', '')[:300]}" for f in feedback
        )
    return style, prefs


async def write_section(task: SectionTask, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    sec = task["section"]
    chapters = await ctx.deps.reader.get_json(task["cleaned_transcript_ref"]["uri"])
    excerpt = "\n\n".join(chapters[i]["text"] for i in sec["chapter_idxs"])
    style, prefs = await _style_and_preferences(runtime, task["user_id"], task.get("style_profile_id"))

    # checkpointer=False: the agent's message history (full section text) is never checkpointed.
    writer = create_agent(
        model=ctx.llm(), tools=[validate_code_syntax], system_prompt=prompts.SECTION_WRITER,
        name="section_writer", checkpointer=False,
    )
    prompt = prompts.write_section(task["angle"], task["target_reader"], sec["heading"], sec["key_points"],
                                   task["glossary"], style, prefs, excerpt)
    result = await writer.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    markdown = last_ai_text(result)
    if not markdown.lstrip().startswith("## "):
        markdown = f"## {sec['heading']}\n\n{markdown}"
    ref = await ctx.deps.blobs.put_text(
        job_path(task["user_id"], task["job_id"], "sections", sec["id"], markdown), markdown
    )
    link = yt_link(task["video_id"], sec["start"])
    return {"section_drafts": [{
        "section_id": sec["id"], "idx": task["idx"], "heading": sec["heading"], "ref": ref,
        "start": sec["start"], "timestamp_link": link,
    }]}


async def assemble_post(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    """Sections are kept verbatim; the LLM only writes the intro, TL;DR and conclusion around them."""
    ctx = runtime.context
    drafts = sorted(state["section_drafts"], key=lambda d: d["idx"])
    sections: list[SectionPart] = []
    for d in drafts:
        md = await ctx.deps.reader.get_text(d["ref"]["uri"])
        sections.append(SectionPart(id=d["section_id"], heading=d["heading"], markdown=md,
                                    start=d["start"], link=d["timestamp_link"]))
    body = "\n\n".join(s["markdown"] for s in sections)
    fr = await ctx.structured(Framing).ainvoke(
        prompts.framing(state["title"], state["angle"], state["target_reader"], body)
    )
    parts = DraftParts(intro=fr.intro, tldr=list(fr.tldr), sections=sections, conclusion=fr.conclusion)
    update = await save_draft(ctx.deps.blobs, state, parts, compose(parts), "auto")
    return {**update, "status": "assembled"}
