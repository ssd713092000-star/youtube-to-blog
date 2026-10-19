import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.aio import loop_factory
from app.core.config import get_settings
from app.db.models_creds import CredsBase as Base

target_metadata = Base.metadata
URL = context.config.attributes.get("url") or get_settings().creds_db_url

# LangGraph's checkpoint/store tables live in the app DB but are managed by .setup(), not Alembic.
IGNORED = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations",
           "store", "store_migrations", "store_vectors", "vector_migrations"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in IGNORED)


def do_run(connection) -> None:
    role = get_settings().db_migrate_role
    if role:
        connection.exec_driver_sql('SET ROLE "' + role.replace('"', '""') + '"')
        connection.commit()  # SET ROLE is session-level; commit so Alembic manages its own transaction
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object,
                      version_table="alembic_version_creds", compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    settings = get_settings()
    kwargs = {}
    if settings.db_iam_auth:
        from app.db.iam import IamAsyncConnection

        conninfo = URL.replace("postgresql+psycopg://", "postgresql://")
        kwargs["async_creator"] = lambda: IamAsyncConnection.connect(conninfo)
    engine = create_async_engine(URL, **kwargs)
    async with engine.connect() as conn:
        await conn.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, version_table="alembic_version_creds")
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async(), loop_factory=loop_factory())
