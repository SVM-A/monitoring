import hashlib
import hmac
from typing import Generic, TypeVar, List, Any, Sequence

from pydantic import BaseModel

from sqlalchemy import select, Row, RowMapping
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update as sqlalchemy_update, delete as sqlalchemy_delete, func

from app.core.config import pepper_token_env
from app.db.models.base_sql import BaseSQL

import bcrypt
bcrypt.__about__ = bcrypt

from app.utils.http_exceptions import ValidErrorException
from app.utils.logger import logger

SQL = TypeVar("SQL", bound=BaseSQL)


class MainBaseDAO(Generic[SQL]):
    model: type[SQL]


    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Проверяем, что это прямой наследник BaseDAO, а не внутренний класс SQLAlchemy
        if issubclass(cls, MainBaseDAO) and cls is not MainBaseDAO:
            logger.info(f"{cls.__name__} инициализирован")



class BaseDAO(MainBaseDAO):
    """
    Базовый класс DAO(Объекта доступа к данным).
    Принимает модель SQLAlchemy и данные обернутые в Pydantic.
    """

    model: type[SQL]
    name_object_model: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Проверяем, что это прямой наследник BaseDAO, а не внутренний класс SQLAlchemy
        if issubclass(cls, BaseDAO) and cls is not BaseDAO:
            cls.name_object_model = cls.__name__[:-3].lower()
            logger.info(f"{cls.__name__} инициализирован")

    @classmethod
    async def find_one_or_none_by_id(cls, data_id: int, db: AsyncSession) -> BaseSQL:
        # Найти запись по ID
        logger.info(f"Поиск {cls.model.__name__} с ID: {data_id}")
        try:
            query = select(cls.model).filter_by(id=data_id)
            result = await db.execute(query)
            record = result.scalar_one_or_none()
            if record:
                logger.info(f"Запись с ID {data_id} найдена.")
            else:
                logger.info(f"Запись с ID {data_id} не найдена.")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записи с ID {data_id}: {e}")
            raise

    @classmethod
    async def find_one_or_none(cls, db: AsyncSession, filters: BaseModel):
        logger.info('# Найти одну запись по фильтрам. (BaseDAO.find_one_or_none)')

        filter_dict = filters.model_dump()
        logger.info(f"Поиск одной записи {cls.model.__name__} по фильтрам: {filter_dict}")
        try:
            query = select(cls.model).filter_by(**filter_dict)
            result = await db.execute(query)
            record = result.scalar_one_or_none()
            if record:
                logger.info(f"Запись найдена по фильтрам: {filter_dict}")
            else:
                logger.info(f"Запись не найдена по фильтрам: {filter_dict}")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записи по фильтрам {filter_dict}: {e}")
            raise

    @classmethod
    async def find_all(cls, db: AsyncSession, filters: BaseModel | None):
        if filters:
            filter_dict = filters.model_dump(exclude_unset=True)
        else:
            filter_dict = {}
        logger.info(f"Поиск всех записей {cls.model.__name__} по фильтрам: {filter_dict}")
        try:
            query = select(cls.model).filter_by(**filter_dict)
            result = await db.execute(query)
            records = result.scalars().all()
            logger.info(f"Найдено {len(records)} записей.")
            return records
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске всех записей по фильтрам {filter_dict}: {e}")
            raise

    @classmethod
    async def add(cls, db: AsyncSession, values: BaseModel):
        # Добавить одну запись
        values_dict = values.model_dump(exclude_unset=True)
        logger.info(f"Добавление записи {cls.model.__name__} с параметрами: {values_dict}")
        new_instance = cls.model(**values_dict)
        db.add(new_instance)
        try:
            await db.flush()
            logger.info(f"Запись {cls.model.__name__} успешно добавлена.")
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при добавлении записи: {e}")
            raise e
        return new_instance

    @classmethod
    async def add_many(cls, db: AsyncSession, instances: List[BaseModel]):
        # Добавить несколько записей
        values_list = [item.model_dump(exclude_unset=True) for item in instances]
        logger.info(f"Добавление нескольких записей {cls.model.__name__}. Количество: {len(values_list)}")
        new_instances = [cls.model(**values) for values in values_list]
        db.add_all(new_instances)
        try:
            await db.flush()
            logger.info(f"Успешно добавлено {len(new_instances)} записей.")
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при добавлении нескольких записей: {e}")
            raise e
        return new_instances

    @classmethod
    async def update(cls, db: AsyncSession, filters: BaseModel, values: BaseModel):
        # Обновить записи по фильтрам
        filter_dict = filters.model_dump(exclude_unset=True)
        values_dict = values.model_dump(exclude_unset=True)
        logger.info(f"Обновление записей {cls.model.__name__} по фильтру: {filter_dict} с параметрами: {values_dict}")
        query = (
            sqlalchemy_update(cls.model)
            .where(*[getattr(cls.model, k) == v for k, v in filter_dict.items()])
            .values(**values_dict)
            .execution_options(synchronize_session="fetch")
        )
        try:
            result = await db.execute(query)
            await db.flush()
            logger.info(f"Обновлено {result.rowcount} записей.")
            return result.rowcount
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при обновлении записей: {e}")
            raise e

    @classmethod
    async def delete(cls, db: AsyncSession, filters: BaseModel):
        # Удалить записи по фильтру
        filter_dict = filters.model_dump(exclude_unset=True)
        logger.info(f"Удаление записей {cls.model.__name__} по фильтру: {filter_dict}")
        if not filter_dict:
            logger.error("Нужен хотя бы один фильтр для удаления.")
            raise ValidErrorException("Нужен хотя бы один фильтр для удаления.")


        query = sqlalchemy_delete(cls.model).filter_by(**filter_dict)
        try:
            result = await db.execute(query)
            await db.flush()
            logger.info(f"Удалено {result.rowcount} записей.")
            return result.rowcount
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при удалении записей: {e}")
            raise e

    @classmethod
    async def count(cls, db: AsyncSession, filters: BaseModel):
        # Подсчитать количество записей
        filter_dict = filters.model_dump(exclude_unset=True)
        logger.info(f"Подсчет количества записей {cls.model.__name__} по фильтру: {filter_dict}")
        try:
            query = select(func.count(cls.model.id)).filter_by(**filter_dict)
            result = await db.execute(query)
            count = result.scalar()
            logger.info(f"Найдено {count} записей.")
            return count
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при подсчете записей: {e}")
            raise

    @classmethod
    async def paginate(cls, db: AsyncSession, page: int = 1, page_size: int = 10, filters: BaseModel = None):
        # Пагинация записей
        filter_dict = filters.model_dump(exclude_unset=True) if filters else {}
        logger.info(
            f"Пагинация записей {cls.model.__name__} по фильтру: {filter_dict}, страница: {page}, размер страницы: {page_size}")
        try:
            query = select(cls.model).filter_by(**filter_dict)
            result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
            records = result.scalars().all()
            logger.info(f"Найдено {len(records)} записей на странице {page}.")
            return records
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при пагинации записей: {e}")
            raise

    @classmethod
    async def find_by_ids(cls, db: AsyncSession, ids: List[int]) -> Sequence[Row[Any] | RowMapping | Any]:
        """Найти несколько записей по списку ID"""
        logger.info(f"Поиск записей {cls.model.__name__} по списку ID: {ids}")
        try:
            query = select(cls.model).filter(cls.model.id.in_(ids))
            result = await db.execute(query)
            records = result.scalars().all()
            logger.info(f"Найдено {len(records)} записей по списку ID.")
            return records
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записей по списку ID: {e}")
            raise

    @classmethod
    async def upsert(cls, db: AsyncSession, unique_fields: List[str], values: BaseModel):
        """Создать запись или обновить существующую"""
        values_dict = values.model_dump(exclude_unset=True)
        filter_dict = {field: values_dict[field] for field in unique_fields if field in values_dict}

        logger.info(f"Upsert для {cls.model.__name__}")
        try:
            existing = await cls.find_one_or_none(db, BaseModel.model_construct(**filter_dict))
            if existing:
                # Обновляем существующую запись
                for key, value in values_dict.items():
                    setattr(existing, key, value)
                await db.flush()
                logger.info(f"Обновлена существующая запись {cls.model.__name__}")
                return existing
            else:
                # Создаем новую запись
                new_instance = cls.model(**values_dict)
                db.add(new_instance)
                await db.flush()
                logger.info(f"Создана новая запись {cls.model.__name__}")
                return new_instance
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при upsert: {e}")
            raise

    @classmethod
    async def bulk_update(cls, db: AsyncSession, records: List[BaseModel]) -> int:
        """Массовое обновление записей"""
        logger.info(f"Массовое обновление записей {cls.model.__name__}")
        try:
            updated_count = 0
            for record in records:
                record_dict = record.model_dump(exclude_unset=True)
                if 'id' not in record_dict:
                    continue

                update_data = {k: v for k, v in record_dict.items() if k != 'id'}
                stmt = (
                    sqlalchemy_update(cls.model)
                    .filter_by(id=record_dict['id'])
                    .values(**update_data)
                )
                result = await db.execute(stmt)
                updated_count += result.rowcount

            await db.flush()
            logger.info(f"Обновлено {updated_count} записей")
            return updated_count
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error(f"Ошибка при массовом обновлении: {e}")
            raise


    def hash_refresh_token(raw_token: str) -> str:
        """Хэшируем refresh токен безопасно (HMAC-SHA256)."""
        secret: bytes = pepper_token_env().encode("utf-8")
        return hmac.new(secret, raw_token.encode("utf-8"), digestmod=hashlib.sha256).hexdigest() # type: ignore


