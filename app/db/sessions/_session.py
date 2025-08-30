# sessions/_session.py
from typing import Callable, Optional, AsyncGenerator, Generator

from app.utils.logger import logger
from functools import wraps
from contextlib import asynccontextmanager, \
    contextmanager  # это декоратор для создания асинхронных контекстных менеджеров.

from fastapi import Depends  # используется для создания зависимостей в FastAPI.
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession  # асинхронные сессии SQLAlchemy.
from sqlalchemy import text  # для работы с сырыми SQL-запросами.
from sqlalchemy.orm import sessionmaker, Session



class DatabaseSessionManager:
    """
    Класс для управления синхронными и асинхронными сессиями базы данных, включая поддержку транзакций.
    """
    def __init__(
        self,
        async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None,
        sync_session_maker: Optional[sessionmaker] = None
    ):
        self.async_session_maker = async_session_maker  # Фабрика для асинхронных сессий
        self.sync_session_maker = sync_session_maker  # Фабрика для синхронных сессий

    # ───────────────────[ АСИНХРОННЫЕ СЕССИИ ]───────────────────
    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Создаёт и предоставляет новую сессию базы данных.
        Гарантирует закрытие сессии по завершении работы.
        """
        async with self.async_session_maker() as session:  # type: ignore
            try:
                yield session
            except Exception as e:
                logger.error(f"Ошибка при создании сессии базы данных: {e}")
                raise
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self, session: AsyncSession) -> AsyncGenerator[None, None]:
        """
        Управление транзакцией: коммит при успехе, откат при ошибке.
        """
        try:
            yield
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.exception(f"Ошибка транзакции: {e}")
            raise

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию без управления транзакцией.
        """
        async with self.create_session() as session:
            yield session

    async def get_transaction_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию с управлением транзакцией.
        """
        async with self.create_session() as session:
            async with self.transaction(session):
                yield session

    def async_connection(self, isolation_level: Optional[str] = None, commit: bool = True):
        """
        Декоратор для управления сессией с возможностью настройки уровня изоляции и коммита.

        Параметры:
        - `isolation_level`: уровень изоляции для транзакции (например, "SERIALIZABLE").
        - `commit`: если `True`, выполняется коммит после вызова метода.
        """

        def decorator(method):
            @wraps(method)
            async def wrapper(*args, **kwargs):
                async with self.async_session_maker() as db:
                    try:
                        if isolation_level:
                            await db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))

                        result = await method(*args, db=db, **kwargs)

                        if commit:
                            await db.commit()

                        return result
                    except Exception as e:
                        await db.rollback()
                        logger.error(f"Ошибка при выполнении транзакции: {e}")
                        raise
                    finally:
                        await db.close()

            return wrapper

        return decorator

    # ───────────────────[ СИНХРОННЫЕ СЕССИИ ]───────────────────
    @contextmanager
    def sync_create_session(self) -> Generator[Session, None, None]:
        """Создаёт и предоставляет новую **синхронную** сессию базы данных."""
        session = self.sync_session_maker()  # type: ignore
        try:
            yield session
        except Exception as e:
            logger.error(f"Ошибка при создании синхронной сессии базы данных: {e}")
            raise
        finally:
            session.close()

    @contextmanager
    def sync_transaction(self, session: Session):
        """Коммит при успехе, откат при ошибке (синхронная версия)."""
        try:
            yield
            session.commit()
        except Exception as e:
            session.rollback()
            logger.exception(f"Ошибка синхронной транзакции: {e}")
            raise

    def sync_get_session(self) -> Generator[Session, None, None]:
        """Зависимость FastAPI, возвращающая синхронную сессию."""
        with self.sync_create_session() as session:
            yield session

    def sync_get_transaction_session(self) -> Generator[Session, None, None]:
        """Зависимость FastAPI, возвращающая синхронную сессию с транзакцией."""
        with self.sync_create_session() as session:
            with self.sync_transaction(session):
                yield session

    def sync_connection(self, isolation_level: Optional[str] = None, commit: bool = True):
        """
        Декоратор для синхронной работы с БД.
        """
        def decorator(method):
            @wraps(method)
            def wrapper(*args, **kwargs):
                with self.sync_session_maker() as db:
                    try:
                        if isolation_level:
                            db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))

                        result = method(*args, db=db, **kwargs)

                        if commit:
                            db.commit()

                        return result
                    except Exception as e:
                        db.rollback()
                        logger.error(f"Ошибка транзакции: {e}")
                        raise
                    finally:
                        db.close()

            return wrapper

        return decorator

    # ───────────────────[ FASTAPI DEPENDENCIES ]───────────────────
    @property
    def async_session_dependency(self) -> Callable:
        """Зависимость для FastAPI (асинхронная сессия без транзакции)."""
        return Depends(self.get_session)

    @property
    def async_transaction_session_dependency(self) -> Callable:
        """Зависимость для FastAPI (асинхронная сессия с транзакцией)."""
        return Depends(self.get_transaction_session)

    @property
    def sync_session_dependency(self) -> Callable:
        """Зависимость для FastAPI (синхронная сессия без транзакции)."""
        return Depends(self.sync_get_session)

    @property
    def sync_transaction_session_dependency(self) -> Callable:
        """Зависимость для FastAPI (синхронная сессия с транзакцией)."""
        return Depends(self.sync_get_transaction_session)