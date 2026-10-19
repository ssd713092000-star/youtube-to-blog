"""Integration fixtures: a throwaway Postgres (testcontainers), migrations, and the real FastAPI app
with only the outside world (GCS, KMS, YouTube, OpenRouter, dev.to) faked."""

import asyncio
import base64
import os
import shutil
import subprocess

import httpx
import psycopg
import pytest

from tests.fakes import FakeDevto, FakeYouTube, default_llm


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="Docker is required for integration tests")


@pytest.fixture(scope="session")
def pg_urls():
    if not _docker_ok():
        pytest.skip("Docker is required for integration tests")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        base = pg.get_connection_url()  # postgresql://test:test@host:port/test
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute("CREATE DATABASE tube2dev_app")
            conn.execute("CREATE DATABASE tube2dev_credentials")
        root = base.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://")
        urls = {"APP_DB_URL": f"{root}/tube2dev_app", "CREDS_DB_URL": f"{root}/tube2dev_credentials"}
        os.environ.update(urls)
        os.environ.update({"ENV": "local", "AUTH_MODE": "dev", "TASK_MODE": "inline", "GCS_BUCKET": "test-bucket",
                           "DEFAULT_MODEL": "fake/model", "DAILY_JOB_QUOTA": "5"})
        from app.core.config import get_settings

        get_settings.cache_clear()
        from app.cli import migrate

        asyncio.run(migrate(get_settings()), loop_factory=asyncio.SelectorEventLoop if os.name == "nt" else None)
        yield urls


class FakeCipher:
    async def encrypt(self, plaintext: bytes, aad: bytes) -> tuple[bytes, str]:
        return base64.b64encode(aad + b"|" + plaintext), "projects/p/keyRings/k/cryptoKeys/c/cryptoKeyVersions/1"

    async def decrypt(self, ciphertext: bytes, aad: bytes) -> bytes:
        got_aad, plain = base64.b64decode(ciphertext).split(b"|", 1)
        assert got_aad == aad, "AAD mismatch"
        return plain


class FakeVerifier:
    async def verify(self, provider, api_key):
        from app.services.credentials import VerifyResult

        if "bad" in api_key:
            return VerifyResult(ok=False, message="401")
        return VerifyResult(ok=True, username="mayakern" if provider == "devto" else None)


MODELS = {"data": [
    {"id": "fake/model", "name": "Fake Model", "context_length": 128000,
     "pricing": {"prompt": "0.00000014", "completion": "0.00000028"}, "supported_parameters": ["tools"]},
    {"id": "big/model", "name": "Big Model", "context_length": 1000000,
     "pricing": {"prompt": "0.000015", "completion": "0.000075"}, "supported_parameters": ["tools"]},
    {"id": "notools/model", "name": "No tools", "context_length": 8000,
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": []},
    {"id": "fake/model:batch", "name": "Fake (batch)", "context_length": 128000,
     "pricing": {"prompt": "0.00000007", "completion": "0.00000014"}, "supported_parameters": ["tools"]},
]}


@pytest.fixture
async def api(pg_urls):
    from app.container import Overrides
    from app.main_api import create_app, make_lifespan
    from app.services.blobs import MemoryBlobStore
    from app.services.tasks import InlineDispatcher

    llm = default_llm(fact_check_rounds=[True])
    devto = FakeDevto()
    catalog_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MODELS)))
    dispatcher = InlineDispatcher()
    overrides = Overrides(
        blobs=MemoryBlobStore("test-bucket"), youtube=FakeYouTube(), cipher=FakeCipher(), verifier=FakeVerifier(),
        llm_factory=lambda ctx, t=0.2: llm, devto_factory=lambda key: devto, catalog_http=catalog_http,
        dispatcher=dispatcher,
    )
    app = create_app(make_lifespan(overrides))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.app = app
            client.devto = devto
            client.dispatcher = dispatcher
            yield client
        await dispatcher.drain()
