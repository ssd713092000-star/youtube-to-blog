"""OpenRouter model catalogue (public endpoint, cached 1h in Postgres) and per-video cost estimates."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models_app import Job, ModelCache

log = logging.getLogger(__name__)

CACHE_KEY = "openrouter"
CACHE_TTL = timedelta(hours=1)
TOKENS_PER_WORD = 1.35
WORDS_PER_MINUTE = 150

# Prompt/completion tokens per transcript token for a whole run, derived from the pipeline shape
# (clean + write sections + framing + fact-check agent loop + metadata). "high" assumes 2 revisions.
DEFAULT_MULTIPLIERS = {"low": (8.5, 2.2), "high": (19.5, 3.4)}


@dataclass
class ModelInfo:
    id: str
    name: str
    context_length: int
    price_in: float  # USD per token
    price_out: float

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.id.split("/")[0],
            "context_length": self.context_length,
            "price_per_mtok_in": round(self.price_in * 1e6, 4),
            "price_per_mtok_out": round(self.price_out * 1e6, 4),
        }


def _parse(raw: list[dict[str, Any]]) -> list[ModelInfo]:
    out = []
    for m in raw:
        if "tools" not in (m.get("supported_parameters") or []):
            continue  # the pipeline needs tool calling (structured output + agents)
        if m["id"].endswith(":batch"):
            continue  # batch endpoints answer asynchronously (minutes to hours); unusable interactively
        p = m.get("pricing") or {}
        try:
            price_in, price_out = float(p.get("prompt", 0)), float(p.get("completion", 0))
        except (TypeError, ValueError):
            continue
        if price_in < 0 or price_out < 0:
            continue
        out.append(ModelInfo(m["id"], m.get("name") or m["id"], int(m.get("context_length") or 0), price_in, price_out))
    return out


class ModelCatalog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], http: httpx.AsyncClient | None = None):
        self._sessions = sessions
        self._http = http or httpx.AsyncClient(timeout=20.0)

    async def list(self) -> list[ModelInfo]:
        async with self._sessions() as s:
            row = await s.get(ModelCache, CACHE_KEY)
        if row and datetime.now(UTC) - row.fetched_at < CACHE_TTL:
            return _parse(row.data)
        try:
            r = await self._http.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            data = r.json()["data"]
        except Exception:
            log.exception("OpenRouter model list fetch failed")
            if row:
                return _parse(row.data)  # stale is better than nothing
            raise
        async with self._sessions.begin() as s:
            existing = await s.get(ModelCache, CACHE_KEY)
            if existing:
                existing.data = data
                existing.fetched_at = datetime.now(UTC)
            else:
                s.add(ModelCache(id=CACHE_KEY, data=data))
        return _parse(data)

    async def get(self, model_id: str) -> ModelInfo | None:
        return next((m for m in await self.list() if m.id == model_id), None)

    async def multipliers(self, user_id: uuid.UUID | None = None) -> dict[str, tuple[float, float]]:
        """Calibrate from real runs in the last 30 days when there are enough of them."""
        since = datetime.now(UTC) - timedelta(days=30)
        q = select(
            func.count(Job.id),
            func.sum(Job.prompt_tokens),
            func.sum(Job.completion_tokens),
            func.sum(Job.transcript_words),
        ).where(Job.status == "completed", Job.created_at >= since, Job.transcript_words > 0)
        if user_id:
            q = q.where(Job.user_id == user_id)
        async with self._sessions() as s:
            n, pin, pout, words = (await s.execute(q)).one()
        if not n or n < 5 or not words:
            return DEFAULT_MULTIPLIERS
        t = words * TOKENS_PER_WORD
        avg_in, avg_out = pin / t, pout / t
        return {"low": (avg_in * 0.75, avg_out * 0.75), "high": (avg_in * 1.6, avg_out * 1.6)}


def words_from_duration(duration_seconds: int) -> int:
    return int(duration_seconds / 60 * WORDS_PER_MINUTE)


def estimate_cost(model: ModelInfo, words: int, mult: dict[str, tuple[float, float]]) -> dict[str, float]:
    t = words * TOKENS_PER_WORD
    out = {}
    for k in ("low", "high"):
        mi, mo = mult[k]
        out[k] = round(t * mi * model.price_in + t * mo * model.price_out, 6)
    return out
