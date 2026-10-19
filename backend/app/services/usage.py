"""LLM token/cost accounting and per-job budget enforcement via a LangChain callback.

The callback is attached once to the graph run config, so it sees every chat-model call in every
node and nested agent. It records each call through a `UsageSink` (Postgres in prod, memory in tests)
and raises BudgetExceeded *before* a new call once the job has spent its budget."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.core.errors import BudgetExceeded

log = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    step: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class UsageSink(Protocol):
    async def record(self, rec: UsageRecord) -> float:
        """Persist one call; return the job's total cost so far."""
        ...


@dataclass
class MemoryUsageSink:
    records: list[UsageRecord] = field(default_factory=list)

    async def record(self, rec: UsageRecord) -> float:
        self.records.append(rec)
        return sum(r.cost_usd for r in self.records)


class UsageTracker(AsyncCallbackHandler):
    raise_error = True  # let BudgetExceeded propagate instead of being logged and swallowed
    run_inline = True

    def __init__(
        self,
        sink: UsageSink,
        budget_usd: float,
        spent_usd: float = 0.0,
        prices: Callable[[str], tuple[float, float] | None] | None = None,
        on_record: Callable[[UsageRecord, float], Awaitable[None]] | None = None,
    ):
        self.sink = sink
        self.budget = budget_usd
        self.spent = spent_usd
        self._prices = prices
        self._on_record = on_record
        self._runs: dict[UUID, tuple[str, str]] = {}

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID,
                                  metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        if self.spent >= self.budget:
            raise BudgetExceeded(self.spent, self.budget)
        md = metadata or {}
        model = md.get("ls_model_name") or (serialized.get("kwargs") or {}).get("model_name") or "unknown"
        self._runs[run_id] = (md.get("langgraph_node") or "unknown", model)

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        step, model = self._runs.pop(run_id, ("unknown", "unknown"))
        pin = pout = 0
        cost: float | None = None
        for gens in response.generations:
            for g in gens:
                msg = getattr(g, "message", None)
                if msg is None:
                    continue
                um = getattr(msg, "usage_metadata", None) or {}
                pin += int(um.get("input_tokens", 0))
                pout += int(um.get("output_tokens", 0))
                c = (getattr(msg, "response_metadata", None) or {}).get("cost")
                if c is not None:
                    cost = (cost or 0.0) + float(c)
        if cost is None and self._prices and (p := self._prices(model)):
            cost = pin * p[0] + pout * p[1]
        rec = UsageRecord(step, model, pin, pout, round(cost or 0.0, 6))
        try:
            self.spent = await self.sink.record(rec)
        except Exception:  # accounting must never break the pipeline
            log.exception("usage sink failed")
            self.spent += rec.cost_usd
        if self._on_record:
            await self._on_record(rec, self.spent)

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._runs.pop(run_id, None)
