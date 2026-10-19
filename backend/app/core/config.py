from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Comma-separated env values (e.g. WEB_ORIGINS=a,b); NoDecode stops pydantic-settings parsing them as JSON.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """All runtime configuration. GCP access always goes through Application Default Credentials."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "stage", "prod"] = "local"
    service_name: str = "tube2dev-api"
    log_level: str = "INFO"

    # GCP
    gcp_project: str = ""
    region: str = "us-east1"

    # Databases (Cloud SQL via the Auth Proxy with --auto-iam-authn -> no password in the URL)
    app_db_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/tube2dev_app"
    creds_db_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/tube2dev_credentials"
    db_pool_size: int = 10
    # true on Cloud Run (built-in /cloudsql socket): use an ADC OAuth token as the DB password.
    # false locally when the Auth Proxy runs with --auto-iam-authn.
    db_iam_auth: bool = False
    # Run migrations as this role (SET ROLE), e.g. "sa-migrate@PROJECT.iam", so a developer who is a
    # member of it can migrate Cloud SQL from their laptop and every object is still owned by sa-migrate.
    db_migrate_role: str = ""
    # IAM DB users that migrations grant table privileges to, e.g. "sa-api@proj.iam"
    db_app_grantees: CsvList = Field(default_factory=list)
    db_creds_grantees: CsvList = Field(default_factory=list)

    # Storage / crypto / queue
    # "local" backends exist only for running the whole stack on a laptop before GCP resources
    # exist (docker-compose.offline.yml). They are refused outside ENV=local.
    blob_backend: Literal["gcs", "local"] = "gcs"
    local_blob_dir: str = ".data/blobs"
    cipher_backend: Literal["kms", "local"] = "kms"
    local_encryption_key: str = ""  # base64 32-byte key for the local AES-GCM cipher
    gcs_bucket: str = ""
    kms_key_name: str = ""  # projects/P/locations/us-east1/keyRings/tube2dev/cryptoKeys/user-api-keys
    task_mode: Literal["cloud_tasks", "inline"] = "inline"
    tasks_queue: str = "graph-runs"
    tasks_invoker_sa: str = ""  # sa-tasks-invoker@P.iam.gserviceaccount.com
    worker_url: str = "http://localhost:8001"

    # Auth
    auth_mode: Literal["firebase", "dev"] = "firebase"
    firebase_project_id: str = ""
    web_origins: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])

    # YouTube proxy (YouTube blocks most cloud IPs). Either a Secret Manager secret holding
    # {"username": "...", "password": "..."} for Webshare, or a generic proxy URL.
    yt_proxy_secret: str = ""
    yt_proxy_url: str = ""

    # LLM defaults
    default_model: str = "deepseek/deepseek-v4.1-flash"
    # Per-call limits. LangGraph's RetryPolicy retries the whole node, so keep client retries low
    # to bound the worst case (timeout x (client retries + 1) x node attempts).
    llm_timeout_seconds: int = 90
    llm_max_retries: int = 1

    # Pipeline limits
    max_no_chapter_duration: int = 3600
    window_seconds: int = 300
    default_budget_usd: float = 0.50
    max_budget_usd: float = 20.0
    daily_job_quota: int = 10
    rate_limit_per_minute: int = 120

    # Retention
    checkpoint_retention_days: int = 30
    abandoned_job_days: int = 14

    @field_validator("db_app_grantees", "db_creds_grantees", "web_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @property
    def creds_db_conninfo(self) -> str:
        return self.creds_db_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def app_db_conninfo(self) -> str:
        """Plain libpq URL for psycopg (LangGraph pool, LISTEN connection)."""
        return self.app_db_url.replace("postgresql+psycopg://", "postgresql://")

    def assert_safe(self) -> None:
        if self.env != "local" and self.auth_mode == "dev":
            raise RuntimeError("AUTH_MODE=dev is only allowed when ENV=local")
        if self.env != "local" and self.task_mode == "inline":
            raise RuntimeError("TASK_MODE=inline is only allowed when ENV=local")
        if self.env != "local" and (self.blob_backend == "local" or self.cipher_backend == "local"):
            raise RuntimeError("Local blob/cipher backends are only allowed when ENV=local")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.assert_safe()
    return s
