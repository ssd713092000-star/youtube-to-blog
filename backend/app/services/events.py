"""Job progress events.

Writers (the worker) insert a `job_events` row and `pg_notify('job_events', '<job_id>')`.
Readers (the API's SSE endpoint) replay rows after `Last-Event-ID` from the table and use a single
LISTEN connection per API instance only as a wake-up signal, so no event is lost if a notification is."""

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict
from typing import Any

import psycopg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models_app import JobEvent

log = logging.getLogger(__name__)
CHANNEL = "job_events"


async def emit(session: AsyncSession, job_id: uuid.UUID, type_: str, payload: dict[str, Any]) -> int:
    ev = JobEvent(job_id=job_id, type=type_, payload=payload)
    session.add(ev)
    await session.flush()
    await session.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": str(job_id)})
    return ev.id


async def events_after(sessions: async_sessionmaker[AsyncSession], job_id: uuid.UUID, after_id: int,
                       limit: int = 500) -> list[JobEvent]:
    async with sessions() as s:
        q = select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > after_id).order_by(JobEvent.id).limit(limit)
        return list((await s.scalars(q)).all())


class EventListener:
    """One LISTEN connection per process; fans wake-ups out to SSE subscribers."""

    def __init__(self, conninfo: str, conn_class: type[psycopg.AsyncConnection] = psycopg.AsyncConnection):
        self._conninfo = conninfo
        self._conn_class = conn_class
        self._subs: dict[str, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="event-listener")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with await self._conn_class.connect(self._conninfo, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    backoff = 1.0
                    async for n in conn.notifies():
                        for ev in list(self._subs.get(n.payload, ())):
                            ev.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("LISTEN connection lost; reconnecting in %.0fs", backoff)
                # Wake everyone so they re-poll the table while we reconnect.
                for evs in self._subs.values():
                    for ev in evs:
                        ev.set()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    @contextlib.contextmanager
    def subscribe(self, job_id: uuid.UUID):
        ev = asyncio.Event()
        key = str(job_id)
        self._subs[key].add(ev)
        try:
            yield ev
        finally:
            self._subs[key].discard(ev)
            if not self._subs[key]:
                self._subs.pop(key, None)
