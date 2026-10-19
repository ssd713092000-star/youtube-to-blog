import json

from langgraph.graph import END
from langgraph.runtime import Runtime

from app.graph.context import JobContext
from app.graph.state import BlogState, ChapterSpan
from app.graph.util import fmt_time
from app.services.blobs import job_path
from app.services.youtube import YouTubeError


def _reject(base: dict, code: str, reason: str) -> dict:
    return {**base, "rejection_code": code, "rejection_reason": reason, "status": "rejected"}


async def ingest_video(state: BlogState, runtime: Runtime[JobContext]) -> dict:
    ctx = runtime.context
    deps = ctx.deps
    vid = state["video_id"]

    try:
        meta = await deps.youtube.get_metadata(vid)
    except YouTubeError as e:
        return _reject({}, e.code, str(e))
    # TransientFetchError propagates -> RetryPolicy retries the node.

    base = {
        "video_url": f"https://www.youtube.com/watch?v={vid}",
        "title": meta["title"],
        "description": meta["description"][:3000],
        "channel_name": meta["channel"],
        "duration": meta["duration"],
        "has_chapters": bool(meta["chapters"]),
        "thumbnail_url": meta["thumbnail_url"],
        "status": "ingested",
    }

    # Gate 1: no chapters and too long -> stop before downloading the transcript
    limit = deps.max_no_chapter_duration
    if not meta["chapters"] and meta["duration"] > limit:
        return _reject(base, "too_long_without_chapters", (
            f"Cannot be converted to blog: the video has no chapters and is "
            f"{fmt_time(meta['duration'])} long (limit {fmt_time(limit)})."
        ))

    # Gate 2: already converted by this user
    if url := await deps.articles.existing_url(state["user_id"], vid):
        return _reject(base, "already_published", f"Already converted and published: {url}")

    # Gate 3: transcript must exist
    try:
        tr = await deps.youtube.get_transcript(vid)
    except YouTubeError as e:
        return _reject(base, "no_transcript" if e.code == "no_transcript" else e.code, str(e))
    snippets = tr["snippets"]

    # Chapters: real ones, or fixed windows when the video has none
    if meta["chapters"]:
        spans = [(c["title"], c["start"], c["end"]) for c in meta["chapters"]]
    else:
        total = max(meta["duration"], int(snippets[-1]["start"]) + 1)
        w = deps.window_seconds
        spans = [
            (f"Part {i + 1} ({fmt_time(s)})", float(s), float(min(s + w, total)))
            for i, s in enumerate(range(0, total, w))
        ]
    spans[-1] = (spans[-1][0], spans[-1][1], max(spans[-1][2], snippets[-1]["start"] + 1))

    chapters = []
    for title, start, end in spans:
        lines = [s["text"].replace("\n", " ") for s in snippets if start <= s["start"] < end]
        chapters.append({"title": title, "start": start, "end": end, "text": " ".join(lines)})

    body = json.dumps(chapters, ensure_ascii=False)
    ref = await deps.blobs.put_text(
        job_path(state["user_id"], state["job_id"], "transcript", "chapters", body, "json"), body, "application/json"
    )
    index = [ChapterSpan(title=c["title"], start=c["start"], end=c["end"]) for c in chapters]
    words = sum(len(c["text"].split()) for c in chapters)
    return {
        **base,
        "chapter_index": index,
        "transcript_ref": ref,
        "transcript_words": words,
        "transcript_language": tr["language"],
        "rejection_reason": None,
        "rejection_code": None,
    }


def route_after_ingest(state: BlogState):
    return END if state.get("rejection_reason") else "clean_transcript"
