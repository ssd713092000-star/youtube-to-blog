"""Idempotency-Key handling for state-changing endpoints (review, publish, cancel, retry).

A double-clicked "Approve & publish" or a client retry after a network blip must replay the first
response instead of resuming the graph twice."""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, Conflict
from app.db.models_app import IdempotencyKey


def request_hash(path: str, body: Any) -> str:
    return hashlib.sha256(f"{path}|{json.dumps(body, sort_keys=True, default=str)}".encode()).hexdigest()


async def run_idempotent(
    sessions: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    key: str | None,
    req_hash: str,
    fn: Callable[[], Awaitable[dict[str, Any]]],
    status_code: int = 202,
) -> tuple[int, dict[str, Any]]:
    if not key:
        raise AppError("Idempotency-Key header is required.", code="idempotency_key_required", status_code=400)
    if len(key) > 128:
        raise AppError("Idempotency-Key is too long.", code="idempotency_key_invalid", status_code=400)

    async with sessions.begin() as s:
        inserted = await s.execute(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, request_hash=req_hash)
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.key)
        )
        is_new = inserted.scalar_one_or_none() is not None
        if not is_new:
            row = await s.get(IdempotencyKey, (user_id, key))
            assert row is not None
            if row.request_hash != req_hash:
                raise AppError("Idempotency-Key was reused with a different request.",
                               code="idempotency_key_mismatch", status_code=422)
            if row.response is None:
                raise Conflict("The same request is still being processed.", code="request_in_progress")
            return row.status_code or status_code, row.response

    try:
        response = await fn()
    except Exception:
        # Let the client retry with the same key after a failure.
        async with sessions.begin() as s:
            await s.execute(delete(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key))
        raise
    async with sessions.begin() as s:
        row = await s.get(IdempotencyKey, (user_id, key))
        if row:
            row.response = response
            row.status_code = status_code
    return status_code, response


async def prune(sessions: async_sessionmaker[AsyncSession], older_than: timedelta = timedelta(days=2)) -> int:
    async with sessions.begin() as s:
        r = await s.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < datetime.now(UTC) - older_than))
        return r.rowcount or 0
