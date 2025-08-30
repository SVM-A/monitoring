# app/migrations/env.py

import asyncio
from datetime import datetime
from logging.config import fileConfig
from alembic import context
from asyncpg import Connection
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from app.db.models import tables, associations # type: ignore
from app.db.models.base_sql import AbstractBaseSQL
from app.core.config import get_pstgr_settings

load_dotenv()


# Загружаем конфигурацию Alembic
config = context.config
config.set_main_option(
    "sqlalchemy.url", get_pstgr_settings().async_user_pstgr_url
)  # Устанавливаем URL базы данных

# Настройка логирования
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# Метаданные всех моделей для генерации миграций
target_metadata = AbstractBaseSQL.metadata

def get_migration_name():
    # Получаем текущее время с секундами
    now = datetime.now()
    return now.strftime("%Y-%m-%d_%H:%M:%S")

def run_migrations_offline() -> None:
    """Запуск миграций в офлайн-режиме"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнение миграций"""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Запуск миграций в асинхронном режиме"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """Запуск миграций в онлайн-режиме"""
    asyncio.run(run_async_migrations())

# Определяем, запускать ли миграции в офлайн или онлайн режиме
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()