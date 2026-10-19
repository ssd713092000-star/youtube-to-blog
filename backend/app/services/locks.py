import contextlib
import uuid
from collections.abc import AsyncIterator

from psycopg_pool import AsyncConnectionPool


class JobBusy(Exception):
    """Another worker holds this job's lock; Cloud Tasks should retry later."""


@contextlib.asynccontextmanager
async def job_lock(pool: AsyncConnectionPool, job_id: uuid.UUID) -> AsyncIterator[None]:
    """Session-level advisory lock held on a dedicated pooled connection for the whole graph segment,
    so two workers can never resume the same LangGraph thread concurrently."""
    key = uuid.UUID(str(job_id)).int & 0x7FFF_FFFF_FFFF_FFFF  # signed bigint range
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (key,))
        row = await cur.fetchone()
        if not (row["ok"] if isinstance(row, dict) else row[0]):
            raise JobBusy(str(job_id))
        try:
            yield
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
