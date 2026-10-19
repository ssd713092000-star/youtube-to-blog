"""Hands graph segments to the worker. Cloud Tasks in deployed envs; in-process for local dev."""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, TypedDict

log = logging.getLogger(__name__)

RunKind = Literal["start", "resume", "retry"]


class RunPayload(TypedDict):
    job_id: str
    segment: int
    kind: RunKind
    resume: Any


class Dispatcher(Protocol):
    async def dispatch(self, payload: RunPayload) -> None: ...


class CloudTasksDispatcher:
    def __init__(self, project: str, region: str, queue: str, worker_url: str, invoker_sa: str):
        from google.cloud import tasks_v2

        self._tasks_v2 = tasks_v2
        self._client = tasks_v2.CloudTasksAsyncClient()
        self._parent = self._client.queue_path(project, region, queue)
        self._url = worker_url.rstrip("/") + "/internal/run-job"
        self._audience = worker_url.rstrip("/")
        self._sa = invoker_sa

    async def dispatch(self, payload: RunPayload) -> None:
        from google.api_core.exceptions import AlreadyExists

        # Deterministic task name -> Cloud Tasks de-duplicates double enqueues of the same segment.
        name = f"{self._parent}/tasks/{payload['job_id']}-{payload['segment']}-{payload['kind']}"
        task = {
            "name": name,
            "dispatch_deadline": {"seconds": 1800},
            "http_request": {
                "http_method": self._tasks_v2.HttpMethod.POST,
                "url": self._url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {"service_account_email": self._sa, "audience": self._audience},
            },
        }
        try:
            await self._client.create_task(request={"parent": self._parent, "task": task})
        except AlreadyExists:
            log.info("task %s already enqueued", name)


class InlineDispatcher:
    """Local only: runs the segment as a background asyncio task in this process."""

    def __init__(self) -> None:
        self.handler: Callable[[RunPayload], Awaitable[None]] | None = None
        self._tasks: set[asyncio.Task] = set()

    async def dispatch(self, payload: RunPayload) -> None:
        if self.handler is None:
            raise RuntimeError("InlineDispatcher has no handler")
        t = asyncio.create_task(self._run(payload), name=f"run-{payload['job_id']}")
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _run(self, payload: RunPayload) -> None:
        try:
            await self.handler(payload)  # type: ignore[misc]
        except Exception:
            log.exception("inline run failed for job %s", payload["job_id"])

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def cancel_all(self) -> None:
        """On shutdown: stop in-flight segments instead of blocking until they finish. Their state is
        checkpointed and `recover_inflight` resumes them on the next start."""
        for t in list(self._tasks):
            t.cancel()
        await self.drain()


def new_payload(job_id: uuid.UUID, segment: int, kind: RunKind, resume: Any = None) -> RunPayload:
    return {"job_id": str(job_id), "segment": segment, "kind": kind, "resume": resume}
