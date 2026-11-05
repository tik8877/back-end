import asyncio

from alembic import context
from sqlalchemy import MetaData, pool
from sqlalchemy.ext.asyncio import async_engine_from_config


def configure_migrations(database_url: str, metadata: MetaData) -> None:
    config = context.config
    config.set_main_option("sqlalchemy.url", database_url)
    if context.is_offline_mode():
        context.configure(
            url=database_url,
            target_metadata=metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    async def run() -> None:
        engine = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        async with engine.connect() as connection:
            await connection.run_sync(
                lambda sync_connection: _run_sync(sync_connection, metadata)
            )
        await engine.dispose()

    asyncio.run(run())


def _run_sync(connection, metadata: MetaData) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
