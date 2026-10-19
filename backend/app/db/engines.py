from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.iam import IamAsyncConnection


def make_engine(url: str, settings: Settings) -> AsyncEngine:
    kwargs: dict = {}
    if settings.db_iam_auth:
        conninfo = url.replace("postgresql+psycopg://", "postgresql://")
        kwargs["async_creator"] = lambda: IamAsyncConnection.connect(conninfo)
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        **kwargs,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
