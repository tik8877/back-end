import asyncio
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from common.config import CommonSettings


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(settings: CommonSettings) -> AsyncEngine:
    options: dict[str, object] = {"pool_pre_ping": True}
    if not settings.database_url.startswith("sqlite"):
        options.update(
            pool_size=settings.database_pool_size,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
    return create_async_engine(settings.database_url, **options)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def wait_for_database(engine: AsyncEngine, settings: CommonSettings) -> None:
    log = structlog.get_logger()
    delay = settings.dependency_retry_initial_seconds
    for attempt in range(1, settings.dependency_connect_attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "database_connection_wait",
                details={"attempt": attempt, "error_type": type(exc).__name__},
            )
            if attempt == settings.dependency_connect_attempts:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, settings.dependency_retry_max_seconds)


def session_dependency(
    factory: async_sessionmaker[AsyncSession],
):
    async def dependency() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return dependency
