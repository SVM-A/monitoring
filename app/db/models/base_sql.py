# app/models/base_sql.py
import uuid

from app.utils.logger import logger
from datetime import datetime
from typing import Annotated, Dict, Any

from enum import Enum
from sqlalchemy import func, UUID, String, TIMESTAMP, Boolean, BigInteger, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, class_mapper
from sqlalchemy.ext.asyncio import AsyncAttrs


# Аннотации
expires_at = Annotated[datetime, mapped_column(TIMESTAMP(timezone=True), nullable=False)]
created_at = Annotated[datetime, mapped_column(TIMESTAMP, server_default=func.now())]
updated_at = Annotated[datetime, mapped_column(TIMESTAMP, server_default=func.now(), onupdate=func.now())]
str_255_uniq_null_false = Annotated[str, mapped_column(String(255), unique=True, nullable=False)]
str_255_uniq_null_true = Annotated[str, mapped_column(String(255), unique=True, nullable=True)]
str_255_null_true = Annotated[str, mapped_column(String(255), nullable=True)]
str_255_null_false = Annotated[str, mapped_column(String(255), nullable=False)]
str_1000_null_true = Annotated[str, mapped_column(String(1000), nullable=True)]
str_1000_null_false = Annotated[str, mapped_column(String(1000), nullable=False)]
int_def_0 = Annotated[int, mapped_column(default=0)]
int_def_1 = Annotated[int, mapped_column(default=1)]
bool_true = Annotated[bool, mapped_column(Boolean, default=True)]
bool_false = Annotated[bool, mapped_column(Boolean, default=False)]
array_or_none_an = Annotated[list[str] | None, mapped_column(ARRAY(String))]



class AbstractBaseSQL(AsyncAttrs, DeclarativeBase):
    __abstract__ = True  # Класс абстрактный, чтобы не создавать отдельную таблицу для него

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Проверяем, что это прямой наследник BaseDAO, а не внутренний класс SQLAlchemy
        if cls.__bases__[0] == AbstractBaseSQL:
            logger.info(f"{cls.__name__} инициализирован")

    def __repr__(self) -> str:
        """Строковое представление объекта для удобства отладки."""
        return f"<{self.__class__.__name__}(created_at={self.created_at}, updated_at={self.updated_at})>"


    def to_dict(self) -> Dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}  # type: ignore

    def to_dict_one_lap(self) -> Dict[str, Any]:
        """Универсальный метод для конвертации объекта SQLAlchemy в словарь."""
        result = {c.name: getattr(self, c.name) for c in self.__table__.columns}  # type: ignore
        # Преобразуем типы данных для сериализации
        for key, value in result.items():
            if isinstance(value, uuid.UUID):
                result[key] = str(value)  # Преобразуем UUID в строку
            elif isinstance(value, datetime):
                result[key] = value.isoformat()  # Преобразуем datetime в ISO строку
            elif isinstance(value, Enum):
                result[key] = value.value  # Преобразуем Enum в строку
            elif isinstance(value, bytes):
                result[key] = value.decode('utf-8')  # Преобразуем байты в строку
        return result

    def to_dict_two_lap(self) -> Dict[str, Any]:
        # Получаем маппер для модели и извлекаем все столбцы
        mapper = class_mapper(self.__class__)
        result = {}
        # Проходим по всем атрибутам модели
        for column in mapper.columns:
            value = getattr(self, column.name)
            # Преобразуем отношения в списки словарей
            if isinstance(value, list):  # Проверка на список отношений
                if len(value) > 0 and hasattr(value[0],
                                              'to_dict_one_lap'):  # Проверка, если объект в списке имеет метод to_dict
                    result[column.name] = [item.to_dict_one_lap() for item in value]
                else:
                    result[column.name] = value  # Если это не объект с to_dict, просто добавляем значение
            else:
                # Для обычных атрибутов
                if isinstance(value, UUID):
                    result[column.name] = str(value)  # Преобразуем UUID в строку
                else:
                    result[column.name] = value

        return result

    def to_dict_to_the_bottom(self):
        # Получаем маппер для модели и извлекаем все столбцы
        mapper = class_mapper(self.__class__)
        result = {}
        # Проходим по всем атрибутам модели
        for column in mapper.columns:
            value = getattr(self, column.name)
            # Преобразуем отношения в списки словарей
            if isinstance(value, list):  # Проверка на список отношений
                if len(value) > 0 and hasattr(value[0],
                                              'to_dict_to_the_bottom'):  # Проверка, если объект в списке имеет метод to_dict
                    result[column.name] = [item.to_dict_to_the_bottom() for item in value]
                else:
                    result[column.name] = value  # Если это не объект с to_dict, просто добавляем значение
            else:
                # Для обычных атрибутов
                if isinstance(value, UUID):
                    result[column.name] = str(value)  # Преобразуем UUID в строку
                else:
                    result[column.name] = value

        return result



# Базовый класс для всех моделей
class BaseSQL(AbstractBaseSQL):
    __abstract__ = True  # Класс абстрактный, чтобы не создавать отдельную таблицу для него

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Проверяем, что это прямой наследник BaseDAO, а не внутренний класс SQLAlchemy
        if cls.__bases__[0] == BaseSQL:
            logger.info(f"{cls.__name__} инициализирован")

    def __repr__(self) -> str:
        """Строковое представление объекта для удобства отладки."""
        return f"<{self.__class__.__name__}(id={self.id}, created_at={self.created_at}, updated_at={self.updated_at})>"


