"""Test doubles: a scripted chat model that supports tool binding/structured output, plus in-memory
YouTube, dev.to, article registry and publish ledger."""

import json
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.graph.context import GraphDeps, JobContext, PublishAttemptRow
from app.services.blobs import MemoryBlobStore


def _last_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m.content, str) and m.content:
            return m.content
    return ""


class ScriptedChatModel(BaseChatModel):
    """`structured` maps a schema/tool name to a function (prompt -> args dict). Anything else gets `text(prompt)`."""

    structured: dict[str, Callable[[str], dict]] = {}
    text: Callable[[str], str] = lambda p: "ok"
    bound_names: list[str] = []
    cost_per_call: float = 0.001
    calls: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
        names = [convert_to_openai_tool(t)["function"]["name"] for t in tools]
        return self.model_copy(update={"bound_names": names})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        prompt = _last_text(messages)
        target = next((n for n in self.bound_names if n in self.structured), None)
        self.calls.append(target or "text")
        usage = {"input_tokens": len(prompt) // 4, "output_tokens": 50, "total_tokens": len(prompt) // 4 + 50}
        meta = {"cost": self.cost_per_call}
        if target:
            args = self.structured[target](prompt)
            msg = AIMessage(content="", tool_calls=[{"name": target, "args": args, "id": f"call_{len(self.calls)}"}],
                            usage_metadata=usage, response_metadata=meta)
        else:
            msg = AIMessage(content=self.text(prompt), usage_metadata=usage, response_metadata=meta)
        return ChatResult(generations=[ChatGeneration(message=msg)])


def default_llm(fact_check_rounds: list[bool] | None = None) -> ScriptedChatModel:
    """fact_check_rounds: per fact-check call, whether every claim is supported."""
    rounds = list(fact_check_rounds or [True])

    def fact(_: str) -> dict:
        ok = rounds.pop(0) if rounds else True
        claims = [
            {"text": "cargo new creates a project", "supported": True, "evidence": "said at 00:12",
             "section": "Getting started", "timestamp": "00:12"},
            {"text": "anyhow cuts binary size by 40%", "supported": ok, "evidence": "" if not ok else "00:31",
             "section": "Errors", "timestamp": "00:31"},
        ]
        return {"claims": claims, "readability": 8, "structure": 9, "revision_notes": ["Tighten the intro"]}

    def text(prompt: str) -> str:
        if "Revise this section" in prompt:
            heading = next((ln for ln in prompt.splitlines() if ln.startswith("## ")), "## Section")
            if "DROP_CODE" in prompt:
                return f"{heading}\n\nRevised but the code block is gone."
            return f"{heading}\n\nRevised body without the unsupported claim.\n\n```python\nprint('hi')\n```"
        if "Revise this" in prompt:
            return "Revised text."
        if "SECTION_HEADING" in prompt or "Section heading:" in prompt:
            heading = prompt.split("Section heading:", 1)[1].splitlines()[0].strip()
            return f"## {heading}\n\nBody for {heading}.\n\n```python\nprint('hi')\n```"
        if "Clean this auto-generated" in prompt:
            return prompt.split("<transcript>\n", 1)[1].split("\n</transcript>", 1)[0].replace(" um", "")
        return "SUPPORTED | Getting started | cargo new | 00:12"

    return ScriptedChatModel(
        structured={
            "Glossary": lambda p: {"terms": ["Rust", "cargo", "anyhow"]},
            "Outline": lambda p: {
                "angle": "Ship a CLI fast", "target_reader": "Backend devs", "tags": ["Rust", "CLI!", "tutorial"],
                "sections": [
                    {"heading": "Getting started", "chapter_idxs": [0], "key_points": ["cargo new"]},
                    {"heading": "Errors", "chapter_idxs": [1], "key_points": ["anyhow"]},
                ],
            },
            "Framing": lambda p: {"intro": "Intro text.", "tldr": ["One", "Two", "Three"], "conclusion": "Bye."},
            "FactCheck": fact,
            "RevisionPlan": lambda p: {"items": [{"target": "Errors", "instruction": "Remove the 40% claim"}]},
            "Metadata": lambda p: {"title_options": ["Build a Rust CLI", "Rust CLI 101", "From shell to Rust"],
                                   "description": "A short summary.", "tags": ["rust", "cli"]},
            "Social": lambda p: {"linkedin": "New post!", "x": "New post"},
        },
        text=text,
    )


class FakeYouTube:
    def __init__(self, chapters: bool = True, duration: int = 120, transcript_error: Exception | None = None):
        self.chapters = chapters
        self.duration = duration
        self.transcript_error = transcript_error
        self.calls = 0

    async def get_metadata(self, video_id: str) -> dict:
        chapters = [{"title": "Intro", "start": 0.0, "end": 60.0}, {"title": "Errors", "start": 60.0, "end": 120.0}]
        return {"video_id": video_id, "title": "Building a Rust CLI", "description": "Rust cargo anyhow",
                "channel": "Ferris Talks", "duration": self.duration,
                "chapters": chapters if self.chapters else [], "thumbnail_url": "https://img/x.jpg"}

    async def get_transcript(self, video_id: str) -> dict:
        self.calls += 1
        if self.transcript_error:
            raise self.transcript_error
        return {"language": "en", "snippets": [
            {"text": "so um the first thing is cargo new", "start": 12.0, "duration": 3.0},
            {"text": "anyhow just wraps any error type", "start": 72.0, "duration": 3.0},
        ]}


class MemoryArticles:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    async def existing_url(self, user_id: str, video_id: str) -> str | None:
        r = self.rows.get((user_id, video_id))
        return r["url"] if r else None

    async def record(self, **kw: Any) -> None:
        self.rows.setdefault((kw["user_id"], kw["video_id"]), kw)


class MemoryLedger:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def begin(self, job_id: str, published: bool) -> PublishAttemptRow:
        if job_id in self.rows:
            r = self.rows[job_id]
            return PublishAttemptRow(state=r["state"], is_new=False, devto_article_id=r.get("id"),
                                     url=r.get("url"), published=r.get("published", False))
        self.rows[job_id] = {"state": "in_flight", "published": published}
        return PublishAttemptRow(state="in_flight", is_new=True, published=published)

    async def succeed(self, job_id: str, devto_article_id: int, url: str, published: bool) -> None:
        self.rows[job_id] = {"state": "succeeded", "id": devto_article_id, "url": url, "published": published}

    async def fail(self, job_id: str, error: str) -> None:
        self.rows[job_id]["state"] = "failed"


class FakeDevto:
    def __init__(self, fail_times: int = 0) -> None:
        self.created: list[dict] = []
        self.fail_times = fail_times

    async def create_article(self, article: dict) -> dict:
        self.created.append(article)  # the POST "lands" even when the response is lost
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("connection reset after POST")
        return {"id": 1000 + len(self.created), "url": f"https://dev.to/u/post-{len(self.created)}",
                "published": article["published"]}

    async def find_my_article(self, title: str) -> dict | None:
        for i, a in enumerate(self.created):
            if a["title"] == title:
                return {"id": 1001 + i, "url": f"https://dev.to/u/post-{i + 1}", "published": a["published"]}
        return None


def make_deps(llm: ScriptedChatModel | None = None, youtube: FakeYouTube | None = None,
              devto: FakeDevto | None = None) -> tuple[GraphDeps, dict]:
    llm = llm or default_llm()
    devto = devto or FakeDevto()
    parts = {"blobs": MemoryBlobStore("test-bucket"), "youtube": youtube or FakeYouTube(),
             "articles": MemoryArticles(), "ledger": MemoryLedger(), "devto": devto, "llm": llm}
    deps = GraphDeps(
        blobs=parts["blobs"], youtube=parts["youtube"], articles=parts["articles"],
        publish_ledger=parts["ledger"], llm_factory=lambda ctx, t=0.2: llm, devto_factory=lambda key: devto,
    )
    return deps, parts


def ctx_for(deps: GraphDeps, job_id: str = "job-1", user_id: str = "user-1") -> JobContext:
    return JobContext(job_id=job_id, user_id=user_id, model="fake/model", deps=deps,
                      openrouter_key="sk-or-SECRET-KEY", devto_key="DEVTO-SECRET")


def initial_state(job_id: str = "job-1", user_id: str = "user-1", **kw: Any) -> dict:
    return {"job_id": job_id, "user_id": user_id, "video_id": "q9Xk2LmPa0e", "attribution_mode": "credited",
            "style_profile_id": None, "max_revisions": 2, "min_faithfulness": 0.85, "revision_count": 0,
            "errors": [], **kw}


def dump(obj: Any) -> str:
    return json.dumps(obj, default=str)
