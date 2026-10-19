"""Runs one graph *segment* (from start/resume until the next interrupt or the end) for a job, and
mirrors progress into the `jobs` row and `job_events` stream the UI consumes."""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import BudgetExceeded, NonRetryableError
from app.core.logging import job_id_var, user_id_var
from app.db.models_app import Job
from app.db.repos import PgUsageSink
from app.graph.build import STEPS
from app.graph.context import GraphDeps, JobContext
from app.services import events
from app.services.credentials import CredentialService
from app.services.locks import job_lock
from app.services.tasks import RunPayload
from app.services.usage import UsageRecord, UsageTracker

log = logging.getLogger(__name__)

STEP_LABELS = {
    "ingest_video": "Ingest video", "clean_transcript": "Clean transcript", "plan_outline": "Plan outline",
    "write_section": "Write sections", "assemble_post": "Assemble post", "fact_check": "Fact-check",
    "revise_draft": "Revise", "prepare_metadata": "Prepare metadata", "human_review": "Human review",
    "publish": "Publish to dev.to", "social_and_store": "Social posts",
}
TERMINAL = {"completed", "rejected", "cancelled"}


def initial_steps() -> list[dict]:
    return [{"step": s, "label": STEP_LABELS[s], "state": "pending", "attempt": 0} for s in STEPS]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StepTracker:
    """Translates LangGraph `tasks` stream events into per-step UI state."""

    def __init__(self, steps: list[dict]):
        self.steps = {s["step"]: s for s in (steps or initial_steps())}
        for s in STEPS:
            self.steps.setdefault(s, {"step": s, "label": STEP_LABELS[s], "state": "pending", "attempt": 0})
        self._task_names: dict[str, str] = {}
        self._task_sub: dict[str, str] = {}

    def as_list(self) -> list[dict]:
        return [self.steps[s] for s in STEPS]

    def on_task(self, ev: dict) -> list[tuple[str, dict]]:
        """Returns (event_type, payload) pairs to emit."""
        name = ev.get("name")
        if name not in self.steps:
            return []
        st = self.steps[name]
        out: list[tuple[str, dict]] = []
        if "input" in ev and "result" not in ev:  # task started
            self._task_names[ev["id"]] = name
            if name == "write_section":
                sec = (ev.get("input") or {}).get("section") or {}
                sub_id = sec.get("id", ev["id"])
                self._task_sub[ev["id"]] = sub_id
                subs = st.setdefault("sub_items", [])
                existing = next((x for x in subs if x["id"] == sub_id), None)
                if existing:
                    existing["state"] = "running"
                else:
                    subs.append({"id": sub_id, "label": sec.get("heading", sub_id), "state": "running"})
                out.append(("sub_item_update", {"step": name, "id": sub_id, "state": "running"}))
                if st["state"] != "running":
                    st.update(state="running", started_at=_now(), attempt=st.get("attempt", 0) + 1)
                    out.append(("step_started", {"step": name, "attempt": st["attempt"]}))
            else:
                st.update(state="running", started_at=_now(), finished_at=None, attempt=st.get("attempt", 0) + 1)
                out.append(("step_started", {"step": name, "attempt": st["attempt"]}))
            return out

        # task finished
        if ev.get("error"):
            st.update(state="failed", finished_at=_now())
            out.append(("step_failed", {"step": name, "message": str(ev["error"])[:500]}))
        elif ev.get("interrupts"):
            st.update(state="waiting")
            out.append(("step_finished", {"step": name, "state": "waiting"}))
        elif name == "write_section":
            sub_id = self._task_sub.get(ev["id"])
            for x in st.get("sub_items", []):
                if x["id"] == sub_id:
                    x["state"] = "done"
            out.append(("sub_item_update", {"step": name, "id": sub_id, "state": "done"}))
            if all(x["state"] == "done" for x in st.get("sub_items", [])):
                st.update(state="done", finished_at=_now())
                out.append(("step_finished", {"step": name, "state": "done"}))
        else:
            st.update(state="done", finished_at=_now())
            out.append(("step_finished", {"step": name, "state": "done"}))
        return out

    def current(self) -> str | None:
        running = [s for s in STEPS if self.steps[s]["state"] in ("running", "waiting")]
        return running[-1] if running else None

    def fail_running(self) -> str | None:
        failed = None
        for s in STEPS:
            if self.steps[s]["state"] == "running":
                self.steps[s].update(state="failed", finished_at=_now())
                failed = s
        return failed

    def skip_pending(self) -> None:
        for s in STEPS:
            if self.steps[s]["state"] == "pending":
                self.steps[s]["state"] = "skipped"


async def recover_inflight(sessions: async_sessionmaker[AsyncSession], dispatch) -> int:
    """Inline mode only: re-dispatch segments that were running when this process last stopped.
    (Deployed envs don't need this: Cloud Tasks redelivers a task whose worker died.) The runner
    continues from the last checkpoint, so finished steps aren't re-run or re-billed."""
    from sqlalchemy import select

    async with sessions() as s:
        jobs = (await s.scalars(select(Job).where(
            Job.status.in_(("queued", "running", "publishing")), Job.purged.is_(False), Job.pending_run.is_not(None),
        ))).all()
    for j in jobs:
        log.info("recovering interrupted job", extra={"recovered_job": str(j.id), "segment": j.segment})
        await dispatch(j.pending_run)
    return len(jobs)


class GraphRunner:
    def __init__(self, graph: CompiledStateGraph, sessions: async_sessionmaker[AsyncSession],
                 pool: AsyncConnectionPool, creds: CredentialService, deps: GraphDeps,
                 prices: Callable[[str], tuple[float, float] | None] | None = None):
        self.graph = graph
        self._s = sessions
        self._pool = pool
        self._creds = creds
        self.deps = deps
        self._prices = prices

    async def _emit(self, job_id: uuid.UUID, type_: str, payload: dict) -> None:
        async with self._s.begin() as s:
            await events.emit(s, job_id, type_, payload)

    async def _update(self, job_id: uuid.UUID, **values: Any) -> None:
        async with self._s.begin() as s:
            job = await s.get(Job, job_id)
            if job:
                for k, v in values.items():
                    setattr(job, k, v)

    async def run_segment(self, payload: RunPayload) -> None:
        job_id = uuid.UUID(payload["job_id"])
        job_id_var.set(str(job_id))
        async with job_lock(self._pool, job_id):
            await self._run(job_id, payload)

    async def _run(self, job_id: uuid.UUID, payload: RunPayload) -> None:
        async with self._s() as s:
            job = await s.get(Job, job_id)
        if job is None or job.purged:
            log.warning("job %s not found or purged", job_id)
            return
        user_id_var.set(str(job.user_id))
        if job.status in TERMINAL or payload["segment"] < job.segment:
            log.info("skipping stale task (status=%s, segment %s < %s)", job.status, payload["segment"], job.segment)
            return

        config: dict[str, Any] = {
            "configurable": {"thread_id": str(job_id)},
            "recursion_limit": 100,
            "run_name": "tube2dev-job",
            "metadata": {"job_id": str(job_id), "user_id": str(job.user_id), "segment": payload["segment"]},
        }
        snap = await self.graph.aget_state(config)
        has_checkpoint = bool(snap.values)
        kind = payload["kind"]
        # A redelivered task (worker crashed mid-run) must continue from the checkpoint, never restart.
        if kind == "start" and not has_checkpoint:
            inp: Any = {
                "job_id": str(job_id), "user_id": str(job.user_id), "video_id": job.video_id,
                "attribution_mode": job.config.get("attribution_mode", "credited"),
                "style_profile_id": job.config.get("style_profile_id"),
                "max_revisions": int(job.config.get("max_revisions", 2)),
                "min_faithfulness": float(job.config.get("min_faithfulness", 0.85)),
                "revision_count": 0, "errors": [],
            }
        elif kind == "resume" and snap.interrupts:
            inp = Command(resume=payload["resume"])
        else:
            inp = None

        try:
            openrouter_key = await self._creds.get_plaintext(job.user_id, "openrouter")
            devto_key = await self._creds.get_plaintext(job.user_id, "devto")
        except Exception as e:
            await self._fail(job_id, StepTracker(job.steps), "keys_missing", str(e), retryable=True)
            return

        ctx = JobContext(job_id=str(job_id), user_id=str(job.user_id), model=job.config.get("model", ""),
                         deps=self.deps, openrouter_key=openrouter_key, devto_key=devto_key)

        async def on_usage(rec: UsageRecord, total: float) -> None:
            await self._emit(job_id, "usage", {"step": rec.step, "prompt_tokens": rec.prompt_tokens,
                                               "completion_tokens": rec.completion_tokens, "cost_usd": round(total, 6)})

        tracker = UsageTracker(PgUsageSink(self._s, job_id, job.user_id), budget_usd=job.budget_usd,
                               spent_usd=job.cost_usd, prices=self._prices, on_record=on_usage)
        config["callbacks"] = [tracker]

        steps = StepTracker(job.steps)
        status = "publishing" if job.pending_action == "publish_approval" or job.status == "publishing" else "running"
        await self._update(job_id, status=status, pending_action=None, started_at=job.started_at or datetime.now(UTC))
        await self._emit(job_id, "status_changed", {"status": status, "pending_action": None})

        cancelled = False
        try:
            n = 0
            async for mode, chunk in self.graph.astream(inp, config, context=ctx, stream_mode=["tasks"],
                                                        durability="async"):
                if mode != "tasks":
                    continue
                emitted = steps.on_task(chunk)
                if emitted:
                    async with self._s.begin() as s:
                        j = await s.get(Job, job_id)
                        j.steps = steps.as_list()
                        j.current_step = steps.current()
                        for t, p in emitted:
                            await events.emit(s, job_id, t, p)
                        cancelled = j.cancel_requested
                n += 1
                if cancelled:
                    break
        except BudgetExceeded as e:
            await self._fail(job_id, steps, "budget_exceeded", str(e), retryable=True,
                             details={"spent_usd": e.spent, "budget_usd": e.budget})
            return
        except NonRetryableError as e:
            await self._fail(job_id, steps, getattr(e, "code", "non_retryable"), str(e), retryable=False)
            return
        except Exception as e:
            log.exception("graph segment failed")
            await self._fail(job_id, steps, type(e).__name__, str(e)[:1000] or type(e).__name__, retryable=True)
            return

        if cancelled:
            steps.fail_running()
            await self._update(job_id, status="cancelled", steps=steps.as_list(), current_step=None,
                               finished_at=datetime.now(UTC), pending_run=None)
            await self._emit(job_id, "status_changed", {"status": "cancelled", "pending_action": None})
            return
        await self._finalize(job_id, config, steps)

    async def _finalize(self, job_id: uuid.UUID, config: dict, steps: StepTracker) -> None:
        snap = await self.graph.aget_state(config)
        v = snap.values
        fields: dict[str, Any] = {
            "checkpoint_id": snap.config["configurable"].get("checkpoint_id"),
            "video_title": v.get("title") or "", "channel_name": v.get("channel_name") or "",
            "thumbnail_url": v.get("thumbnail_url") or "", "duration_seconds": v.get("duration") or 0,
            "has_chapters": bool(v.get("has_chapters")), "transcript_words": v.get("transcript_words"),
            "faithfulness_score": v.get("faithfulness_score"), "revision_count": v.get("revision_count", 0),
            "current_draft_rev": v.get("draft_rev"), "devto_url": v.get("devto_url"),
            "publish_status": v.get("publish_status"),
            "result": {"devto_url": v.get("devto_url"), "devto_article_id": v.get("devto_article_id"),
                       "publish_status": v.get("publish_status"), "social": v.get("social_snippets") or {}},
        }
        pending = None
        if snap.interrupts:
            kind = snap.interrupts[0].value.get("kind")
            pending = kind
            status = "awaiting_review" if kind == "draft_review" else "awaiting_publish"
        else:
            steps.skip_pending()
            fields["finished_at"] = datetime.now(UTC)
            if v.get("rejection_reason"):
                status = "rejected"
                fields.update(rejection_reason=v["rejection_reason"], rejection_code=v.get("rejection_code"))
            elif v.get("review_status") == "rejected":
                status = "rejected"
                fields.update(rejection_reason="Aborted by reviewer.", rejection_code="aborted")
            elif v.get("status") == "publish_rejected":
                status = "rejected"
                fields.update(rejection_reason="Publish was rejected by the reviewer.", rejection_code="publish_rejected")
            else:
                status = "completed"
        fields.update(status=status, pending_action=pending, steps=steps.as_list(), current_step=steps.current(),
                      pending_run=None)
        await self._update(job_id, **fields)
        if pending:
            await self._emit(job_id, "interrupt", {"kind": pending})
        await self._emit(job_id, "status_changed", {"status": status, "pending_action": pending})

    async def _fail(self, job_id: uuid.UUID, steps: StepTracker, code: str, message: str, *, retryable: bool,
                    details: dict | None = None) -> None:
        step = steps.fail_running()
        async with self._s.begin() as s:
            job = await s.get(Job, job_id)
            if job is None:
                return
            err = {"step": step or job.current_step, "code": code, "message": message, "at": _now(),
                   "retryable": retryable, **({"details": details} if details else {})}
            job.errors = [*job.errors, err]
            job.pending_run = None
            job.status = "failed"
            job.pending_action = None
            job.steps = steps.as_list()
            job.current_step = step
            await events.emit(s, job_id, "step_failed", err)
            await events.emit(s, job_id, "status_changed", {"status": "failed", "pending_action": None})
