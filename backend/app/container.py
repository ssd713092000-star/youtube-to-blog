"""Builds every long-lived dependency once per process (API or worker)."""

import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.engines import make_engine, make_session_factory
from app.db.iam import connection_class
from app.db.repos import PgArticleRegistry, PgPublishLedger
from app.graph.build import build_graph
from app.graph.context import GraphDeps
from app.graph.llm import openrouter_factory
from app.graph.persistence import graph_persistence
from app.graph.runner import GraphRunner, recover_inflight
from app.services.blobs import BlobStore, GcsBlobStore, LocalBlobStore
from app.services.credentials import CredentialService, KeyVerifier
from app.services.events import EventListener
from app.services.kms import KeyCipher, KmsCipher, LocalCipher
from app.services.openrouter_models import ModelCatalog
from app.services.tasks import CloudTasksDispatcher, Dispatcher, InlineDispatcher
from app.services.youtube import LiveYouTubeClient, ProxySettings, YouTubeClient

log = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    app_engine: AsyncEngine
    creds_engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    creds_sessions: async_sessionmaker[AsyncSession]
    pool: AsyncConnectionPool
    store: AsyncPostgresStore
    graph: CompiledStateGraph
    blobs: BlobStore
    youtube: YouTubeClient
    credentials: CredentialService
    catalog: ModelCatalog
    dispatcher: Dispatcher
    runner: GraphRunner
    http: httpx.AsyncClient
    listener: EventListener | None = None


@dataclass
class Overrides:
    """Test/offline hooks: swap any external dependency without touching the wiring."""

    blobs: BlobStore | None = None
    youtube: YouTubeClient | None = None
    cipher: KeyCipher | None = None
    verifier: KeyVerifier | None = None
    llm_factory: Callable | None = None
    devto_factory: Callable | None = None
    catalog_http: httpx.AsyncClient | None = None
    dispatcher: Dispatcher | None = None


@contextlib.asynccontextmanager
async def build_container(settings: Settings, *, listen_events: bool,
                          overrides: Overrides | None = None) -> AsyncIterator[Container]:
    o = overrides or Overrides()
    app_engine = make_engine(settings.app_db_url, settings)
    creds_engine = make_engine(settings.creds_db_url, settings)
    sessions = make_session_factory(app_engine)
    creds_sessions = make_session_factory(creds_engine)
    http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async with graph_persistence(settings.app_db_conninfo, max_size=settings.db_pool_size,
                                  iam_auth=settings.db_iam_auth) as p:
        graph = build_graph(p.checkpointer, p.store)
        blobs = o.blobs or (
            LocalBlobStore(settings.local_blob_dir, settings.gcs_bucket or "local")
            if settings.blob_backend == "local"
            else GcsBlobStore(settings.gcs_bucket, settings.gcp_project)
        )
        youtube = o.youtube or LiveYouTubeClient(
            ProxySettings(settings.yt_proxy_secret, settings.yt_proxy_url), cache=blobs
        )
        cipher = o.cipher or (
            LocalCipher(settings.local_encryption_key) if settings.cipher_backend == "local"
            else KmsCipher(settings.kms_key_name)
        )
        credentials = CredentialService(creds_sessions, cipher,
                                        o.verifier or KeyVerifier(http))
        catalog = ModelCatalog(sessions, o.catalog_http or http)

        prices: dict[str, tuple[float, float]] = {}
        try:
            prices = {m.id: (m.price_in, m.price_out) for m in await catalog.list()}
        except Exception:
            log.warning("model catalogue unavailable at startup; cost falls back to OpenRouter-reported values")

        deps = GraphDeps(
            blobs=blobs, youtube=youtube, articles=PgArticleRegistry(sessions),
            publish_ledger=PgPublishLedger(sessions), llm_factory=o.llm_factory or openrouter_factory(settings),
            max_no_chapter_duration=settings.max_no_chapter_duration, window_seconds=settings.window_seconds,
        )
        if o.devto_factory:
            deps.devto_factory = o.devto_factory
        runner = GraphRunner(graph, sessions, p.pool, credentials, deps, prices=prices.get)

        if o.dispatcher:
            dispatcher: Dispatcher = o.dispatcher
            if isinstance(dispatcher, InlineDispatcher):
                dispatcher.handler = runner.run_segment
        elif settings.task_mode == "cloud_tasks":
            dispatcher = CloudTasksDispatcher(
                settings.gcp_project, settings.region, settings.tasks_queue, settings.worker_url,
                settings.tasks_invoker_sa,
            )
        else:
            inline = InlineDispatcher()
            inline.handler = runner.run_segment
            dispatcher = inline

        listener = (EventListener(settings.app_db_conninfo, connection_class(settings.db_iam_auth))
                    if listen_events else None)
        if listener:
            await listener.start()

        if isinstance(dispatcher, InlineDispatcher) and listen_events:
            n = await recover_inflight(sessions, dispatcher.dispatch)
            if n:
                log.info("re-dispatched %s interrupted job(s)", n)

        c = Container(settings, app_engine, creds_engine, sessions, creds_sessions, p.pool, p.store, graph,
                      blobs, youtube, credentials, catalog, dispatcher, runner, http, listener)
        try:
            yield c
        finally:
            if listener:
                await listener.stop()
            if isinstance(dispatcher, InlineDispatcher):
                await dispatcher.cancel_all()
            await http.aclose()
            await app_engine.dispose()
            await creds_engine.dispose()
