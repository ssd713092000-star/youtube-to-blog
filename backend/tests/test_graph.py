import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from app.core.errors import BudgetExceeded
from app.graph.build import build_graph
from app.graph.persistence import strict_serde
from app.services.usage import MemoryUsageSink, UsageTracker
from tests.fakes import FakeDevto, FakeYouTube, ctx_for, default_llm, dump, initial_state, make_deps


def cfg(job_id: str = "job-1", **extra):
    return {"configurable": {"thread_id": job_id}, "recursion_limit": 80, **extra}


async def run(graph, inp, ctx, config):
    async for _ in graph.astream(inp, config, context=ctx, stream_mode="updates"):
        pass
    return await graph.aget_state(config)


@pytest.fixture
def graph():
    return build_graph(InMemorySaver(serde=strict_serde()), InMemoryStore())


async def test_full_flow_with_revision_both_interrupts_and_publish(graph):
    llm = default_llm(fact_check_rounds=[False, True])
    deps, parts = make_deps(llm=llm)
    ctx, config = ctx_for(deps), cfg()

    snap = await run(graph, initial_state(), ctx, config)
    assert snap.interrupts and snap.interrupts[0].value["kind"] == "draft_review"
    v = snap.values
    assert v["revision_count"] == 1 and v["faithfulness_score"] == 1.0
    assert [d["kind"] for d in v["draft_versions"]] == ["auto", "revised", "final"]
    assert v["devto_tags"] == ["rust", "cli"]

    # No transcript/draft text and no API keys in checkpointed state.
    blob = dump(v)
    assert "the first thing is" not in blob and "Body for" not in blob
    assert "SECRET" not in blob
    assert len(blob) < 20_000

    # Revised section: unsupported claim removed, heading + watch link preserved.
    revised = await deps.reader.get_text(v["draft_ref"]["uri"])
    assert "Revised body without the unsupported claim." in revised
    assert revised.count("▶ Watch this part") == 2
    final = await deps.reader.get_text(v["final_ref"]["uri"])
    assert final.startswith("{% embed https://www.youtube.com/watch?v=q9Xk2LmPa0e %}")
    assert "Ferris Talks" in final

    snap = await run(graph, Command(resume={"action": "approve", "title": "My chosen title"}), ctx, config)
    assert snap.interrupts[0].value["kind"] == "publish_approval"
    assert snap.interrupts[0].value["title"] == "My chosen title"

    snap = await run(graph, Command(resume={"type": "approve", "published": False}), ctx, config)
    assert not snap.next
    v = snap.values
    assert v["status"] == "done" and v["publish_status"] == "saved_as_draft"
    assert v["social_snippets"]["linkedin"] == "New post!"
    assert len(parts["devto"].created) == 1 and parts["devto"].created[0]["published"] is False
    assert ("user-1", "q9Xk2LmPa0e") in parts["articles"].rows


async def test_revision_that_drops_code_is_discarded(graph):
    llm = default_llm(fact_check_rounds=[False, True])
    llm.structured["RevisionPlan"] = lambda p: {"items": [{"target": "Errors", "instruction": "DROP_CODE"}]}
    deps, _ = make_deps(llm=llm)
    snap = await run(graph, initial_state(), ctx_for(deps), cfg())
    revised = await deps.reader.get_text(snap.values["draft_ref"]["uri"])
    assert "code block is gone" not in revised
    assert any("discarded" in e for e in snap.values["errors"])


async def test_human_edit_and_revise_feedback_goes_to_store(graph):
    deps, parts = make_deps()
    ctx, config = ctx_for(deps), cfg()
    await run(graph, initial_state(), ctx, config)

    snap = await run(graph, Command(resume={"action": "revise", "feedback": "Shorter intro"}), ctx, config)
    assert snap.interrupts[0].value["kind"] == "draft_review"
    items = await graph.store.asearch(("users", "user-1", "feedback"))
    assert items and items[0].value["feedback"] == "Shorter intro"

    ref = await deps.blobs.put_text("users/user-1/jobs/job-1/human_edit/x.md", "# edited")
    snap = await run(graph, Command(resume={"action": "edit", "draft_ref": ref, "tags": ["Go", "go", "web"]}), ctx, config)
    v = snap.values
    assert v["final_ref"] == ref and v["devto_tags"] == ["go", "web"]
    assert v["draft_versions"][-1]["kind"] == "human_edit"


async def test_abort_and_publish_reject(graph):
    deps, _ = make_deps()
    ctx = ctx_for(deps)
    await run(graph, initial_state(), ctx, cfg())
    snap = await run(graph, Command(resume={"action": "abort"}), ctx, cfg())
    assert not snap.next and snap.values["review_status"] == "rejected"

    ctx2 = ctx_for(deps, job_id="job-2")
    await run(graph, initial_state("job-2"), ctx2, cfg("job-2"))
    await run(graph, Command(resume={"action": "approve"}), ctx2, cfg("job-2"))
    snap = await run(graph, Command(resume={"type": "reject", "message": "not yet"}), ctx2, cfg("job-2"))
    assert not snap.next and snap.values["publish_status"] == "not_published"


async def test_publish_is_idempotent_after_a_crash(graph):
    devto = FakeDevto(fail_times=1)
    deps, parts = make_deps(devto=devto)
    ctx, config = ctx_for(deps), cfg()
    await run(graph, initial_state(), ctx, config)
    await run(graph, Command(resume={"action": "approve"}), ctx, config)

    with pytest.raises(ConnectionError):
        await run(graph, Command(resume={"type": "approve", "published": True}), ctx, config)
    assert parts["ledger"].rows["job-1"]["state"] == "in_flight"

    snap = await run(graph, None, ctx, config)  # "Retry from last checkpoint"
    assert snap.values["publish_status"] == "published"
    assert len(devto.created) == 1, "retry must find the landed article instead of posting twice"


@pytest.mark.parametrize("youtube,code", [
    (FakeYouTube(chapters=False, duration=7200), "too_long_without_chapters"),
])
async def test_ingest_gates(graph, youtube, code):
    deps, _ = make_deps(youtube=youtube)
    snap = await run(graph, initial_state(), ctx_for(deps), cfg())
    assert not snap.next and snap.values["rejection_code"] == code


async def test_already_published_gate(graph):
    deps, parts = make_deps()
    await parts["articles"].record(user_id="user-1", video_id="q9Xk2LmPa0e", url="https://dev.to/x")
    snap = await run(graph, initial_state(), ctx_for(deps), cfg())
    assert snap.values["rejection_code"] == "already_published"


async def test_no_chapters_uses_windows(graph):
    deps, _ = make_deps(youtube=FakeYouTube(chapters=False, duration=120))
    snap = await run(graph, initial_state(), ctx_for(deps), cfg())
    assert [c["title"] for c in snap.values["chapter_index"]] == ["Part 1 (00:00:00)"]


async def test_budget_is_enforced(graph):
    deps, _ = make_deps()
    sink = MemoryUsageSink()
    tracker = UsageTracker(sink, budget_usd=0.0025)
    with pytest.raises(BudgetExceeded):
        await run(graph, initial_state(), ctx_for(deps), cfg(callbacks=[tracker]))
    assert 0.0025 <= tracker.spent < 0.01
    assert {r.step for r in sink.records} <= {"clean_transcript"}


async def test_local_blob_store_and_cipher(tmp_path):
    import base64
    import os

    from app.services.blobs import LocalBlobStore
    from app.services.kms import LocalCipher

    store = LocalBlobStore(str(tmp_path), "b")
    ref = await store.put_text("users/u/jobs/j/drafts/x.md", "hello")
    assert await store.get_text(ref["uri"]) == "hello" and await store.exists("users/u/jobs/j/drafts/x.md")
    with pytest.raises(ValueError):
        await store.put_text("../escape.md", "x")
    assert await store.delete_prefix("users/u/jobs/j/") == 1

    c = LocalCipher(base64.b64encode(os.urandom(32)).decode())
    ct, _ = await c.encrypt(b"sk-or-secret", b"u1:openrouter")
    assert await c.decrypt(ct, b"u1:openrouter") == b"sk-or-secret"
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        await c.decrypt(ct, b"u2:openrouter")  # AAD binds the ciphertext to its owner


def test_openrouter_factory_timeout_is_in_milliseconds():
    from app.core.config import Settings
    from app.graph.llm import openrouter_factory

    llm = openrouter_factory(Settings(llm_timeout_seconds=90))(ctx_for(make_deps()[0]), 0.2)
    assert llm.request_timeout == 90_000  # 90 would mean 90 ms: every call would ConnectTimeout
