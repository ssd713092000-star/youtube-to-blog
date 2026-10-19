"""Runtime context passed to every node via `runtime.context`.

LangGraph does NOT checkpoint the runtime context, which is why the user's decrypted API keys live
here and nowhere else (not in state, not in `configurable`, not in run metadata)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel

from app.services.blobs import BlobStore, CachedBlobReader
from app.services.devto import DevtoClient
from app.services.youtube import YouTubeClient


class ArticleRegistry(Protocol):
    async def existing_url(self, user_id: str, video_id: str) -> str | None: ...
    async def record(self, *, user_id: str, job_id: str, video_id: str, devto_article_id: int, url: str,
                     title: str, thumbnail_url: str, publish_status: str) -> None: ...


@dataclass
class PublishAttemptRow:
    state: str  # in_flight | succeeded | failed
    is_new: bool
    devto_article_id: int | None = None
    url: str | None = None
    published: bool = False


class PublishLedger(Protocol):
    async def begin(self, job_id: str, published: bool) -> PublishAttemptRow: ...
    async def succeed(self, job_id: str, devto_article_id: int, url: str, published: bool) -> None: ...
    async def fail(self, job_id: str, error: str) -> None: ...


@dataclass
class GraphDeps:
    blobs: BlobStore
    youtube: YouTubeClient
    articles: ArticleRegistry
    publish_ledger: PublishLedger
    llm_factory: Callable[["JobContext", float], BaseChatModel]
    devto_factory: Callable[[str], DevtoClient] = DevtoClient
    max_no_chapter_duration: int = 3600
    window_seconds: int = 300
    reader: CachedBlobReader | None = None

    def __post_init__(self) -> None:
        if self.reader is None:
            self.reader = CachedBlobReader(self.blobs)


@dataclass
class JobContext:
    job_id: str
    user_id: str
    model: str
    deps: GraphDeps = field(repr=False)
    openrouter_key: str = field(default="", repr=False)
    devto_key: str = field(default="", repr=False)

    def llm(self, temperature: float = 0.2) -> BaseChatModel:
        return self.deps.llm_factory(self, temperature)

    def structured(self, schema: type, temperature: float = 0.2) -> Any:
        # function_calling works on far more OpenRouter models than native json_schema mode.
        return self.llm(temperature).with_structured_output(schema, method="function_calling")
