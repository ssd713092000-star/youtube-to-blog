"""Operational commands (run with `uv run python -m app.cli <command>`).

  migrate       Alembic (app + creds) -> LangGraph checkpoint/store setup -> runtime grants.
                Runs as the Cloud Run job `tube2dev-migrate` before each deploy.
  bootstrap-db  One-time: as the built-in `postgres` user, hand both databases to the migrate IAM user
                and lock the credentials DB down. Needs POSTGRES_PASSWORD (from Secret Manager).
  openapi       Write the OpenAPI spec (the frontend generates its typed client from it).
  cleanup       Retention: purge old checkpoints, GCS objects, events and idempotency keys.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.aio import run
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging

log = logging.getLogger("tube2dev.cli")
ROOT = Path(__file__).resolve().parent.parent


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _alembic_upgrade(name: str, url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"), ini_section=name)
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


async def _grant(conninfo: str, db: str, grantees: list[str], iam_auth: bool = False) -> None:
    from app.db.iam import connection_class

    async with await connection_class(iam_auth).connect(conninfo, autocommit=True) as conn:
        for g in grantees:
            u = _ident(g)
            for stmt in (
                f"GRANT CONNECT ON DATABASE {_ident(db)} TO {u}",
                f"GRANT USAGE ON SCHEMA public TO {u}",
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {u}",
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {u}",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {u}",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {u}",
            ):
                await conn.execute(stmt)
            log.info("granted runtime privileges on %s to %s", db, g)


def _dbname(conninfo: str) -> str:
    return conninfo.rsplit("/", 1)[-1].split("?", 1)[0]


async def migrate(s: Settings) -> None:
    from app.graph.persistence import setup_langgraph_tables

    # env.py runs its own event loop, so Alembic must run off this loop's thread.
    log.info("alembic upgrade app")
    await asyncio.to_thread(_alembic_upgrade, "app", s.app_db_url)
    log.info("alembic upgrade creds")
    await asyncio.to_thread(_alembic_upgrade, "creds", s.creds_db_url)
    log.info("langgraph checkpointer/store setup")
    await setup_langgraph_tables(s.app_db_conninfo, s.db_iam_auth)
    await _grant(s.app_db_conninfo, _dbname(s.app_db_conninfo), s.db_app_grantees, s.db_iam_auth)
    await _grant(s.creds_db_conninfo, _dbname(s.creds_db_conninfo), s.db_creds_grantees, s.db_iam_auth)
    log.info("migrations complete")


async def bootstrap_db(s: Settings, migrate_user: str, host: str, port: int) -> None:
    """Connect as `postgres` (password auth via the proxy) and make the migrate IAM user own both DBs."""
    import psycopg

    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        sys.exit("POSTGRES_PASSWORD is required")
    m = _ident(migrate_user)
    for db_url in (s.app_db_url, s.creds_db_url):
        db = _dbname(db_url)
        dsn = f"host={host} port={port} dbname={db} user=postgres password={password}"
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            await conn.execute(f"GRANT {m} TO postgres")
            await conn.execute(f"ALTER DATABASE {_ident(db)} OWNER TO {m}")
            await conn.execute(f"ALTER SCHEMA public OWNER TO {m}")
            await conn.execute(f"REVOKE ALL ON DATABASE {_ident(db)} FROM PUBLIC")
            await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            log.info("database %s now owned by %s; PUBLIC access revoked", db, migrate_user)


async def cleanup(s: Settings) -> None:
    from sqlalchemy import and_, delete, or_, select

    from app.db.engines import make_engine, make_session_factory
    from app.db.models_app import Job, JobEvent
    from app.graph.persistence import graph_persistence
    from app.services import idempotency
    from app.services.blobs import GcsBlobStore, LocalBlobStore, job_prefix

    engine = make_engine(s.app_db_url, s)
    sessions = make_session_factory(engine)
    blobs = (LocalBlobStore(s.local_blob_dir, s.gcs_bucket or "local") if s.blob_backend == "local"
             else GcsBlobStore(s.gcs_bucket, s.gcp_project))
    now = datetime.now(UTC)
    finished_before = now - timedelta(days=s.checkpoint_retention_days)
    abandoned_before = now - timedelta(days=s.abandoned_job_days)
    async with graph_persistence(s.app_db_conninfo, max_size=2, iam_auth=s.db_iam_auth) as p:
        async with sessions() as sess:
            jobs = (await sess.execute(select(Job.id, Job.user_id).where(Job.purged.is_(False), or_(
                and_(Job.status.in_(("completed", "rejected", "cancelled", "failed")), Job.updated_at < finished_before),
                and_(Job.status.in_(("awaiting_review", "awaiting_publish")), Job.updated_at < abandoned_before),
            )))).all()
        for jid, uid in jobs:
            await p.checkpointer.adelete_thread(str(jid))
            n = await blobs.delete_prefix(job_prefix(str(uid), str(jid)))
            async with sessions.begin() as sess:
                j = await sess.get(Job, jid)
                if j.status in ("awaiting_review", "awaiting_publish"):
                    j.status, j.pending_action = "cancelled", None
                j.purged = True
            log.info("purged job", extra={"purged_job": str(jid), "objects": n})
    # Cloud Tasks gave up on a segment (or a worker vanished): don't leave the job "running" forever.
    async with sessions.begin() as sess:
        stalled = (await sess.scalars(select(Job).where(
            Job.status.in_(("queued", "running", "publishing")), Job.updated_at < now - timedelta(hours=2),
        ))).all()
        for j in stalled:
            j.status, j.pending_run = "failed", None
            j.errors = [*j.errors, {"step": j.current_step, "code": "stalled", "at": now.isoformat(), "retryable": True,
                                    "message": "The pipeline stopped responding. Retry to continue from the last checkpoint."}]
        if stalled:
            log.warning("marked %s stalled job(s) as failed", len(stalled))
    async with sessions.begin() as sess:
        r = await sess.execute(delete(JobEvent).where(JobEvent.created_at < finished_before))
        log.info("deleted %s old job events", r.rowcount)
    log.info("deleted %s idempotency keys", await idempotency.prune(sessions))
    await engine.dispose()


def openapi(out: str) -> None:
    os.environ.setdefault("AUTH_MODE", "dev")
    from app.main_api import create_app

    spec = create_app().openapi()
    Path(out).write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(f"wrote {out}")


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    b = sub.add_parser("bootstrap-db")
    b.add_argument("--migrate-user", required=True, help='e.g. "sa-migrate@PROJECT.iam"')
    b.add_argument("--host", default="127.0.0.1")
    b.add_argument("--port", type=int, default=5432)
    o = sub.add_parser("openapi")
    o.add_argument("--out", default="openapi.json")
    sub.add_parser("cleanup")
    args = p.parse_args()

    s = get_settings()
    setup_logging(s.log_level, f"tube2dev-{args.cmd}", s.gcp_project)
    if args.cmd == "migrate":
        run(migrate(s))
    elif args.cmd == "bootstrap-db":
        run(bootstrap_db(s, args.migrate_user, args.host, args.port))
    elif args.cmd == "openapi":
        openapi(args.out)
    elif args.cmd == "cleanup":
        run(cleanup(s))


if __name__ == "__main__":
    main()
