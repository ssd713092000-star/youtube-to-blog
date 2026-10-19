import asyncio
import uuid

import pytest

from tests.integration.conftest import pytestmark  # noqa: F401  (skip without Docker)


def auth(email: str) -> dict:
    return {"Authorization": f"Bearer dev:{email}"}


def idem() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def wait_for(api, job_id: str, h: dict, statuses: set[str], limit_s: float = 20) -> dict:
    deadline = asyncio.get_event_loop().time() + limit_s
    while True:
        r = await api.get(f"/api/v1/jobs/{job_id}", headers=h)
        body = r.json()
        if body["status"] in statuses:
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"job stuck in {body['status']}: {body.get('errors')}")
        await asyncio.sleep(0.1)


async def connect_keys(api, h: dict) -> None:
    for p, key in (("openrouter", "sk-or-v1-test-123456"), ("devto", "devto-test-abcdef")):
        r = await api.put(f"/api/v1/me/integrations/{p}", json={"api_key": key}, headers=h)
        assert r.status_code == 200, r.text


async def test_end_to_end_job_through_both_interrupts(api):
    h = auth(f"maya-{uuid.uuid4().hex[:6]}@example.com")

    # Keys are required before creating a job.
    r = await api.post("/api/v1/jobs", json={"video_url": "https://youtu.be/q9Xk2LmPa0e?t=42"}, headers=h)
    assert r.status_code == 412 and r.json()["error"]["code"] == "keys_missing"

    r = await api.put("/api/v1/me/integrations/devto", json={"api_key": "bad-key-123"}, headers=h)
    assert r.status_code == 422
    await connect_keys(api, h)
    integ = (await api.get("/api/v1/me/integrations", headers=h)).json()
    assert integ["openrouter"]["connected"] and integ["openrouter"]["last4"] == "3456"
    assert integ["devto"]["username"] == "mayakern"
    assert "sk-or" not in str(integ)

    # Preview + model picker
    pv = (await api.post("/api/v1/videos/preview", json={"url": "https://youtu.be/q9Xk2LmPa0e?t=42"}, headers=h)).json()
    assert pv["eligible"] and pv["transcript_available"] and pv["estimated_cost_usd"]["low"] > 0
    models = (await api.get("/api/v1/models", params={"video_id": "q9Xk2LmPa0e", "budget_usd": 0.0001}, headers=h)).json()
    ids = [m["id"] for m in models["items"]]
    assert ids[0] == "fake/model" and "notools/model" not in ids and models["basis"] == "video"
    assert "fake/model:batch" not in ids  # async batch endpoints would hang the pipeline
    r = await api.post("/api/v1/jobs", json={"video_url": "q9Xk2LmPa0e", "model": "fake/model:batch"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_model"
    assert next(m for m in models["items"] if m["id"] == "big/model")["over_budget"]

    # Create -> runs inline -> pauses for review
    r = await api.post("/api/v1/jobs", json={"video_url": "https://youtu.be/q9Xk2LmPa0e", "max_revisions": 1},
                       headers=h)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    job = await wait_for(api, job_id, h, {"awaiting_review", "failed"})
    assert job["status"] == "awaiting_review", job["errors"]
    assert job["pending_action"] == "draft_review" and job["checkpoint_id"]
    assert job["usage"]["cost_usd"] > 0 and job["video_title"] == "Building a Rust CLI"
    steps = {s["step"]: s for s in job["steps"]}
    assert steps["write_section"]["state"] == "done" and len(steps["write_section"]["sub_items"]) == 2
    assert steps["human_review"]["state"] == "waiting"

    review = (await api.get(f"/api/v1/jobs/{job_id}/review", headers=h)).json()
    drafts = (await api.get(f"/api/v1/jobs/{job_id}/drafts", headers=h)).json()
    assert drafts[-1]["kind"] == "final" and review["draft_rev"] == drafts[-1]["rev"]
    md = (await api.get(f"/api/v1/jobs/{job_id}/drafts/{review['draft_rev']}", headers=h)).json()["markdown"]
    assert md.startswith("{% embed")
    assert len((await api.get(f"/api/v1/jobs/{job_id}/outline", headers=h)).json()["sections"]) == 2
    assert (await api.get(f"/api/v1/jobs/{job_id}/fact-check", headers=h)).json()["faithfulness_score"] == 1.0

    # Another user can't see it
    other = auth("intruder@example.com")
    assert (await api.get(f"/api/v1/jobs/{job_id}", headers=other)).status_code == 404

    # Stale checkpoint -> 409; missing idempotency key -> 400
    body = {"action": "edit", "markdown": "# Edited by me\n\nHello", "title": "My Title",
            "expected_checkpoint_id": "stale"}
    r = await api.post(f"/api/v1/jobs/{job_id}/review", json=body, headers={**h, **idem()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_checkpoint"
    body["expected_checkpoint_id"] = job["checkpoint_id"]
    assert (await api.post(f"/api/v1/jobs/{job_id}/review", json=body, headers=h)).status_code == 400

    # Same idempotency key twice -> one resume, same response
    key = idem()
    r1 = await api.post(f"/api/v1/jobs/{job_id}/review", json=body, headers={**h, **key})
    r2 = await api.post(f"/api/v1/jobs/{job_id}/review", json=body, headers={**h, **key})
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    job = await wait_for(api, job_id, h, {"awaiting_publish", "failed"})
    assert job["status"] == "awaiting_publish", job["errors"]

    pr = (await api.get(f"/api/v1/jobs/{job_id}/publish-request", headers=h)).json()
    assert pr["title"] == "My Title" and pr["devto_username"] == "mayakern"
    r = await api.post(f"/api/v1/jobs/{job_id}/publish", headers={**h, **idem()},
                       json={"decision": "approve", "published": True, "expected_checkpoint_id": job["checkpoint_id"]})
    assert r.status_code == 202 and r.json()["status"] == "publishing"
    job = await wait_for(api, job_id, h, {"completed", "failed"})
    assert job["status"] == "completed" and job["publish_status"] == "published", job["errors"]
    assert api.devto.created[-1]["body_markdown"] == "# Edited by me\n\nHello"

    res = (await api.get(f"/api/v1/jobs/{job_id}/result", headers=h)).json()
    assert res["devto_url"] and res["social"]["linkedin"] == "New post!" and res["summary"]["cost_usd"] > 0
    arts = (await api.get("/api/v1/articles", headers=h)).json()["items"]
    assert arts[0]["devto_url"] == res["devto_url"]

    # Already published -> preview ineligible, create conflicts
    pv = (await api.post("/api/v1/videos/preview", json={"url": "q9Xk2LmPa0e"}, headers=h)).json()
    assert pv["ineligible_reason"] == "already_published"
    r = await api.post("/api/v1/jobs", json={"video_url": "q9Xk2LmPa0e"}, headers=h)
    assert r.status_code == 409

    # Lists, counts, dashboard, usage
    lst = (await api.get("/api/v1/jobs", headers=h)).json()
    assert lst["counts"]["completed"] == 1 and lst["items"][0]["progress_label"] == "public"
    dash = (await api.get("/api/v1/me/dashboard", headers=h)).json()
    assert dash["posts_this_month"] == 1 and dash["spend_this_month"] > 0
    usage = (await api.get("/api/v1/me/usage", params={"period": "7d"}, headers=h)).json()
    assert usage["jobs"] == 1 and usage["by_model"][0]["model"]

    # Events were recorded in order for SSE replay
    from app.services.events import events_after

    evs = await events_after(api.app.state.container.sessions, uuid.UUID(job_id), 0)
    types = [e.type for e in evs]
    assert types[0] == "status_changed" and "interrupt" in types and "usage" in types
    assert [e.id for e in evs] == sorted(e.id for e in evs)

    # Checkpoints hold refs, not text or keys
    snap = await api.app.state.container.graph.aget_state({"configurable": {"thread_id": job_id}})
    blob = str(snap.values)
    assert "Edited by me" not in blob and "sk-or-v1-test" not in blob


async def test_style_profiles_settings_and_validation(api):
    h = auth(f"sam-{uuid.uuid4().hex[:6]}@example.com")
    r = await api.post("/api/v1/style-profiles", json={"name": "Conversational", "examples": ["Hi there"],
                                                       "is_default": True}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    profiles = (await api.get("/api/v1/style-profiles", headers=h)).json()
    assert profiles[0]["is_default"]
    s = (await api.get("/api/v1/me/settings", headers=h)).json()
    assert s["default_style_profile_id"] == pid
    s["default_model"] = "notools/model"
    r = await api.put("/api/v1/me/settings", json=s, headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "default_model"
    assert (await api.delete(f"/api/v1/style-profiles/{pid}", headers=h)).status_code == 204

    r = await api.post("/api/v1/videos/preview", json={"url": "https://example.com/nope"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_url"
    r = await api.post("/api/v1/jobs", json={"video_url": "x"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert (await api.get("/api/v1/jobs")).status_code == 401


async def test_interrupted_segment_is_recovered_on_restart(api):
    """Inline mode: a segment killed by a process restart is re-dispatched from jobs.pending_run."""
    from app.graph.runner import recover_inflight

    h = auth(f"rec-{uuid.uuid4().hex[:6]}@example.com")
    await connect_keys(api, h)
    c = api.app.state.container
    job_id = (await api.post("/api/v1/jobs", json={"video_url": "https://youtu.be/DDDDDDDDDDD"}, headers=h)).json()["job_id"]
    await api.dispatcher.cancel_all()  # simulate the process dying mid-segment
    job = (await api.get(f"/api/v1/jobs/{job_id}", headers=h)).json()
    assert job["status"] in ("queued", "running")

    assert await recover_inflight(c.sessions, api.dispatcher.dispatch) >= 1
    job = await wait_for(api, job_id, h, {"awaiting_review", "failed"})
    assert job["status"] == "awaiting_review", job["errors"]


async def test_cancel_while_waiting_and_client_logs(api):
    h = auth(f"kim-{uuid.uuid4().hex[:6]}@example.com")
    await connect_keys(api, h)
    job_id = (await api.post("/api/v1/jobs", json={"video_url": "https://youtu.be/AAAAAAAAAAA"}, headers=h)).json()["job_id"]
    await wait_for(api, job_id, h, {"awaiting_review"})
    r = await api.post(f"/api/v1/jobs/{job_id}/cancel", headers={**h, **idem()})
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    assert (await api.delete(f"/api/v1/jobs/{job_id}", headers=h)).status_code == 204
    assert (await api.get(f"/api/v1/jobs/{job_id}", headers=h)).status_code == 404

    r = await api.post("/api/v1/client-logs", json={"entries": [
        {"level": "error", "message": "boom with sk-or-v1-abcdefghijkl", "route": "/jobs/x",
         "context": {"api_key": "secret"}}]})
    assert r.status_code == 204


@pytest.mark.parametrize("n", [1])
async def test_daily_quota(api, n):
    h = auth(f"q-{uuid.uuid4().hex[:6]}@example.com")
    await connect_keys(api, h)
    for i in range(5):
        r = await api.post("/api/v1/jobs", json={"video_url": f"https://youtu.be/BBBBBBBBBB{i}"}, headers=h)
        assert r.status_code == 202
    r = await api.post("/api/v1/jobs", json={"video_url": "https://youtu.be/CCCCCCCCCCC"}, headers=h)
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded"
    await api.dispatcher.drain()
