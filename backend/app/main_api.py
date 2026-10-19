"""tube2dev-api: public FastAPI service."""

import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import RateLimiter
from app.api.v1 import articles, jobs, me, models, review, style_profiles, system, videos
from app.auth.firebase import TokenVerifier
from app.container import build_container
from app.core.config import get_settings
from app.core.http import install_error_handlers, install_middleware
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level, settings.service_name, settings.gcp_project)


def make_lifespan(overrides=None):
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with build_container(settings, listen_events=True, overrides=overrides) as container:
            app.state.container = container
            app.state.verifier = TokenVerifier(settings)
            app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
            app.state.client_log_limiter = RateLimiter(60)
            yield

    return lifespan


lifespan = make_lifespan()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(
        title="Tube2Dev API",
        version="1.0.0",
        description="Turn YouTube videos into dev.to posts with a human-in-the-loop LangGraph pipeline.",
        lifespan=lifespan_override or lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    install_middleware(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    for r in (videos, jobs, review, articles, style_profiles, me, models):
        app.include_router(r.router, prefix="/api/v1")
    app.include_router(system.router)
    return app


app = create_app()
