"""LangGraph checkpointer + long-term store on Cloud SQL Postgres (tube2dev_app database)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.db.iam import connection_class


def strict_serde() -> JsonPlusSerializer:
    """Restrict checkpoint deserialization to LangGraph's safe-type allowlist (datetime, uuid,
    langchain messages, ...). Our state is plain dicts/TypedDicts, so nothing else is needed, and a
    compromised checkpoint table can't be turned into code execution."""
    return JsonPlusSerializer(allowed_msgpack_modules=None)


@dataclass
class GraphPersistence:
    pool: AsyncConnectionPool
    checkpointer: AsyncPostgresSaver
    store: AsyncPostgresStore


def make_pool(conninfo: str, max_size: int = 10, iam_auth: bool = False, role: str = "") -> AsyncConnectionPool:
    # autocommit + dict_row are required by AsyncPostgresSaver/AsyncPostgresStore.
    # prepare_threshold=0 keeps it safe behind poolers that don't support prepared statements.
    async def set_role(conn) -> None:
        await conn.execute('SET ROLE "' + role.replace('"', '""') + '"')

    return AsyncConnectionPool(
        conninfo,
        min_size=1,
        max_size=max_size,
        open=False,
        configure=set_role if role else None,
        connection_class=connection_class(iam_auth),
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
    )


@asynccontextmanager
async def graph_persistence(conninfo: str, max_size: int = 10, iam_auth: bool = False, role: str = ""
                            ) -> AsyncIterator[GraphPersistence]:
    pool = make_pool(conninfo, max_size, iam_auth, role)
    await pool.open(wait=True)
    try:
        yield GraphPersistence(
            pool=pool,
            checkpointer=AsyncPostgresSaver(pool, serde=strict_serde()),
            store=AsyncPostgresStore(pool),
        )
    finally:
        await pool.close()


async def setup_langgraph_tables(conninfo: str, iam_auth: bool = False, role: str = "") -> None:
    """Run once from the migrate job (not at service startup)."""
    async with graph_persistence(conninfo, max_size=2, iam_auth=iam_auth, role=role) as p:
        await p.checkpointer.setup()
        await p.store.setup()
