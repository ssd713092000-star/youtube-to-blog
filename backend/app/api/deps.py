import time
import uuid
from collections import defaultdict, deque
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth.firebase import TokenVerifier, Unauthorized
from app.container import Container
from app.core.errors import AppError, NotFound
from app.core.logging import user_id_var
from app.db.models_app import Job, User


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_verifier(request: Request) -> TokenVerifier:
    return request.app.state.verifier


ContainerDep = Annotated[Container, Depends(get_container)]


class RateLimiter:
    """Per-user sliding window. Per instance, which is fine as a safety net; quotas live in Postgres."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            retry = int(60 - (now - q[0])) + 1
            raise AppError("Too many requests.", code="rate_limited", status_code=429,
                           details={"retry_after": retry})
        q.append(now)


async def current_user(
    request: Request,
    c: ContainerDep,
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token.")
    ident = await verifier.verify(authorization.split(" ", 1)[1].strip())
    request.app.state.rate_limiter.check(ident.uid)

    async with c.sessions.begin() as s:
        user = await s.scalar(
            insert(User)
            .values(firebase_uid=ident.uid, email=ident.email, display_name=ident.name, photo_url=ident.picture)
            .on_conflict_do_update(
                index_elements=[User.firebase_uid],
                set_={"email": ident.email, "display_name": ident.name, "photo_url": ident.picture},
            )
            .returning(User)
        )
    user_id_var.set(str(user.id))
    return user


UserDep = Annotated[User, Depends(current_user)]


async def owned_job(job_id: uuid.UUID, user: UserDep, c: ContainerDep) -> Job:
    async with c.sessions() as s:
        job = await s.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None or job.purged:
        raise NotFound("Job not found.")  # also for other users' jobs: never reveal existence
    return job


JobDep = Annotated[Job, Depends(owned_job)]


def thread_config(job_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(job_id)}}


async def job_state(c: Container, job_id: uuid.UUID):
    return await c.graph.aget_state(thread_config(job_id))
