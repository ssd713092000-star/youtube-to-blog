from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from app.core.config import Settings
from app.graph.context import JobContext


def openrouter_factory(settings: Settings):
    """One ChatOpenRouter per call site, built with the job owner's own key."""

    def make(ctx: JobContext, temperature: float = 0.2) -> BaseChatModel:
        return ChatOpenRouter(
            model=ctx.model,
            api_key=ctx.openrouter_key,
            temperature=temperature,
            timeout=settings.llm_timeout_seconds * 1000,  # ChatOpenRouter's timeout is in milliseconds
            max_retries=settings.llm_max_retries,
            app_title="Tube2Dev",
        )

    return make
