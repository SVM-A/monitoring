import random
from datetime import datetime, timezone, timedelta
from typing import Tuple, Annotated, Any

from jose import jwt
from passlib.context import CryptContext

from pydantic import EmailStr, BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, raiseload
from sqlalchemy.sql import and_, literal
from sqlalchemy import select, Row, RowMapping
from fastapi.responses import JSONResponse

from app.core.config import algorithm_env, access_token_env, refresh_token_env
from app.db.dao.base_dao import BaseDAO
from app.db.schemas.user import EmailModel, PhoneModel, TokenBase
from app.db.models.enums import RoleEnum, TokenTypeEnum
from app.db.models.tables import User, Token, Role
from app.db.sessions import SessionDep
from app.db.sessions.utils import async_connect_db
from app.utils.http_exceptions import TokenGenerationException, IncorrectRefreshPasswordException
from app.utils.logger import logger


import bcrypt
bcrypt.__about__ = bcrypt




class AuthDAO(BaseDAO):
    model = User

    @classmethod
    async def creating_recording_access_token_to_user(cls, user: User, token_scopes: list) -> str:
        if not isinstance(token_scopes, list):
            token_scopes = list(token_scopes)

        # # 1. Удаляем ВСЕ предыдущие access токены этого пользователя
        # await db.execute(
        #     delete(Token).where(
        #         Token.user_id == user.id,
        #         Token.token_type == TokenTypeEnum.ACCESS  # Удаляем все ACCESS токены, независимо от ban
        #     )
        # )
        # await db.flush()  # Или await db.commit() если это отдельная операция

        # 2. Генерируем гарантированно уникальный токен
        access_token = AuthDAO.creating_recording_token_to_user(
            user=user,
            token_scopes=token_scopes,
            expires_delta=timedelta(minutes=15),
            token_type=TokenTypeEnum.ACCESS
        )

        # 3. Сохраняем новый токен
        return access_token.token

    @classmethod
    async def creating_recording_all_token_to_user(cls, db: AsyncSession, user: User, token_scopes: list
                                                   ) -> Annotated[Tuple[str, str], "access_token, refresh_token"]:
        if not isinstance(token_scopes, list):
            token_scopes = list(token_scopes)

        access_token: TokenBase = AuthDAO.creating_recording_token_to_user(user=user, token_scopes=token_scopes,
                                                                expires_delta=timedelta(minutes=15),
                                                                token_type=TokenTypeEnum.ACCESS)
        if not access_token:
            logger.error(f'Ошибка при генерации access_token (user_id: {user.id})')
            raise TokenGenerationException
        logger.info(f'Новый access_token создан (user_id: {user.id})')
        refresh_token = AuthDAO.creating_recording_token_to_user(user=user, token_scopes=token_scopes,
                                                                 expires_delta=timedelta(days=30),
                                                                 token_type=TokenTypeEnum.REFRESH)
        if not refresh_token:
            logger.error(f'Ошибка при генерации refresh_token (user_id: {user.id})')
            raise TokenGenerationException
        logger.info(f'Новый refresh_token создан (user_id: {user.id})')

        try:
            user.refresh_token_assoc.append(Token(**refresh_token.model_dump()))
            await db.flush()
            logger.info(f'Токены успешно записаны! (user_id: {user.id})')
        except SQLAlchemyError as e:
            logger.error(f'Ошибка при записи access_token, refresh_token (user_id: {user.id}): {e}')
        return access_token.token, refresh_token.token

    @classmethod
    def creating_recording_token_to_user(cls, user: User, token_scopes: list,
                                         expires_delta: timedelta, token_type: TokenTypeEnum) -> TokenBase:
        token, expire_token = AuthDAO.create_token(data={"sub": str(user.id)}, scopes=token_scopes,
                                                   expires_delta=expires_delta, token_type=token_type)
        schema_token = TokenBase(user_id=user.id, token=token, expires_at=expire_token, token_type=token_type)
        return schema_token

    @classmethod
    def create_token(cls, data: dict, scopes: list[str], expires_delta: timedelta, token_type: TokenTypeEnum) -> tuple[str, datetime]:
        to_encode = data.copy()
        to_encode.update({"scopes": scopes})
        expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=15))
        to_encode.update({"exp": expire})
        token_env = access_token_env() if token_type == TokenTypeEnum.ACCESS else refresh_token_env()
        encode_jwt = jwt.encode(to_encode, token_env, algorithm=algorithm_env())
        return encode_jwt, expire

    @classmethod
    async def get_refresh_token(cls, db: AsyncSession, values: TokenBase):
        # Достать токен из БД
        values_dict = values.model_dump(exclude_unset=True)
        token = values_dict.get('token')

        logger.info(f"Поиск токена : {token}")
        try:
            query = select(Token).filter_by(**values_dict)
            result = await db.execute(query)
            record = result.scalar_one_or_none()
            if record:
                logger.info(f"Токен {token} найден.")
            else:
                logger.info(f"Токен {token} не найден.")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске токена {token}: {e}")
            raise

    @classmethod
    async def authenticate_user(cls, password: str, email: EmailStr = None, phone: str = None,
                                db: AsyncSession = SessionDep):
        user = None
        if email:
            user = await UserDAO.find_one_or_none_with_tokens(db=db, filters=EmailModel(email=email))
        elif phone:
            user = await UserDAO.find_one_or_none_with_tokens(db=db, filters=PhoneModel(phone_number=phone))
        if user:
            verify_password = await cls.verify_password(plain_password=password, hashed_password=user.password)
            if not verify_password:
                logger.remove()
                raise IncorrectRefreshPasswordException
        return user

    @staticmethod
    async def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Проверка пароля: сравнение введённого пароля с хэшированным паролем в базе данных.

        :param plain_password: Обычный пароль, введённый пользователем.
        :param hashed_password: Хэшированный пароль, сохранённый в базе данных.
        :return: True, если пароли совпадают, иначе False.
        """
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        is_valid = pwd_context.verify(plain_password, hashed_password)
        if is_valid:
            logger.info("Пароль успешно верифицирован")
        else:
            logger.warning("Ошибка верификации пароля")
        return is_valid



class UserDAO(BaseDAO):
    model = User
    adjectives = ["cool", "fast", "cuted", "bright", "wild", "crazy", "funny", "happy", "smart", "brave"]
    animals = ["dog", "cat", "wolf", "fox", "bear", "lion", "tiger", "bird", "shark", "panda"]

    @classmethod
    async def handle_failed_login(cls, user: User, db: AsyncSession):
        """
        Обрабатывает неудачную попытку входа и блокирует пользователя при превышении попыток.
        """

        # Проверяем, забанен ли пользователь
        if user.is_banned:
            return None

        # Увеличиваем количество неудачных попыток
        user.failed_attempts += 1

        # Если количество неудачных попыток достигло 10, блокируем пользователя
        if user.failed_attempts >= 10:
            user.is_banned = True
            user.ban_until = datetime.now(timezone.utc) + timedelta(minutes=10)
            await db.commit()

            ban_until = user.ban_until or datetime.now(timezone.utc)
            ban_until_str = ban_until.strftime('%Y-%m-%d %H:%M:%S %Z')
            logger.warning(f"Пользователь {user.email} заблокирован на 10 минут до {ban_until_str}.")

            return JSONResponse(
                status_code=403,
                content={
                    "status": "error",
                    "message": f"User {user.email} is banned for 10 minutes due to too many "
                               f"failed login attempts. Blocked until: {ban_until_str}",
                    "error_code": 1006
                }
            )

        await db.commit()  # Сохраняем изменения после увеличения попыток
        return None

    @classmethod
    async def remove_bans(cls, db: AsyncSession):
        """
        Снимает блокировку у пользователей, время которой истекло.
        :param db: Сессия базы данных.
        """
        now = datetime.now(timezone.utc)
        query = select(cls.model).where(
            and_(
                User.is_banned,
                User.ban_until <= now
            )
        )
        result = await db.execute(query)
        users_to_unban = result.scalars().all()

        for user in users_to_unban:
            user.is_banned = False
            user.failed_attempts = 0
            user.ban_until = None

        await db.commit()
        for user in users_to_unban:
            logger.info(f"Пользователь {user.email} успешно разблокирован.")

        return users_to_unban

    @classmethod
    async def check_user_ban(cls, user: User, db: AsyncSession):
        """
        Проверяет, забанен ли пользователь, и снимает блокировку, если время бана истекло.
        Возвращает оставшееся время блокировки или None, если пользователь не забанен.

        :param user: Пользователь, который пытается войти.
        :param db: Сессия базы данных.
        :return: Строка с оставшимся временем блокировки или None.
        """
        if not user.is_banned:
            return None

        # Приводим оба времени к UTC для точности и логируем для отладки
        ban_until_utc = user.ban_until.replace(tzinfo=timezone.utc)  # Принудительно устанавливаем UTC для ban_until
        current_time_utc = datetime.now(timezone.utc)

        # Проверяем, истёк ли бан
        if current_time_utc >= ban_until_utc:
            # Бан истёк, снимаем блокировку
            user.is_banned = False
            user.failed_attempts = 0
            user.ban_until = None
            await db.commit()
            logger.info(f"Бан пользователя {user.email} снят, так как время бана истекло.")
            return None

        # Вычисляем оставшееся время
        remaining_ban_time = ban_until_utc - current_time_utc
        remaining_seconds = int(remaining_ban_time.total_seconds())
        remaining_minutes, _ = divmod(remaining_seconds, 60)

        # Формируем строку с оставшимся временем
        remaining_time_str = f"{remaining_minutes} minute(s)"

        logger.warning(f"Пользователь {user.email} забанен. Оставшееся время бана: {remaining_time_str}.")
        return remaining_time_str

    @classmethod
    async def generate_username(cls) -> str:
        """
        Генерирует случайное имя пользователя из комбинации прилагательного и названия животного.

        :return: Сгенерированное имя пользователя.
        """
        adjective = random.choice(cls.adjectives)
        animal = random.choice(cls.animals)
        number = random.randint(10, 99)
        username = f"{adjective}{animal}{number}"
        logger.info(f"Сгенерировано имя пользователя: {username}")
        return username

    @classmethod
    async def generate_unique_user_id(cls, db: AsyncSession) -> int:
        """
        Генерирует уникальный идентификатор пользователя, проверяя наличие в базе данных.

        :param db: Сессия базы данных.
        :return: Уникальный идентификатор пользователя.
        """
        while True:
            user_id = random.randint(1, 999999)

            # Создаем запрос для проверки существования user_id
            query = select(User.id).where(User.id == literal(user_id))
            result = await db.execute(query)
            existing_user = result.fetchone()

            if not existing_user:
                logger.info(f"Сгенерирован уникальный ID пользователя: {user_id}")
                return user_id
            logger.info(f"ID {user_id} уже существует. Попытка генерации нового.")

    @classmethod
    async def find_one_or_none_by_id(cls, data_id: int, db: AsyncSession) -> User:
        # Найти запись по ID
        logger.info(f"Поиск {cls.model.__name__} с ID: {data_id}")
        try:
            query = select(cls.model).filter_by(id=data_id).options(
                selectinload(User.roles_assoc)
            )
            result = await db.execute(query)
            record = result.scalars().first()
            if record:
                logger.info(f"Запись с ID {data_id} найдена.")
            else:
                logger.info(f"Запись с ID {data_id} не найдена.")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записи с ID {data_id}: {e}")
            raise

    @classmethod
    async def find_one_or_none(cls, db: AsyncSession, filters: BaseModel) -> User:
        logger.info('# Найти одну запись по фильтрам. (UsersDAO.find_one_or_none)')
        filter_dict = filters.model_dump()
        logger.info(f"Поиск одной записи {cls.model.__name__} по фильтрам: {filter_dict}")
        try:
            query = select(cls.model).filter_by(**filter_dict).options(
                selectinload(User.roles_assoc)
            )
            result = await db.execute(query)
            record = result.scalars().first()
            if record:
                logger.info(f"Запись найдена по фильтрам: {filter_dict}")
            else:
                logger.info(f"Запись не найдена по фильтрам: {filter_dict}")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записи по фильтрам {filter_dict}: {e}")
            raise

    @classmethod
    async def find_one_or_none_by_id_with_tokens(cls, data_id: int, db: AsyncSession) -> User:
        # Найти запись по ID
        logger.info(f"Поиск {cls.model.__name__} с ID: {data_id}")
        try:
            query = (
                select(cls.model)
                .filter_by(id=data_id)
                .options(
                    selectinload(User.roles_assoc),
                    selectinload(User.refresh_token_assoc),
                )
            )
            result = await db.execute(query)
            record = result.scalars().first()
            if record:
                logger.info(f"Запись с ID {data_id} найдена.")
            else:
                logger.info(f"Запись с ID {data_id} не найдена.")
            return record
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске записи с ID {data_id}: {e}")
            raise

    @classmethod
    async def find_one_or_none_with_tokens(cls, db: AsyncSession, filters: BaseModel):
        logger.info('# Найти одну запись по фильтрам. (UsersDAO.find_one_or_none_with_tokens)')
        filter_dict = filters.model_dump()
        logger.info(f"Поиск одной записи {cls.model.__name__} по фильтрам: {filter_dict}")
        try:
            query = (
                select(cls.model)
                .filter_by(**filter_dict)
                .options(
                    selectinload(User.roles_assoc),
                    selectinload(User.refresh_token_assoc),
                    raiseload("*")  # type: ignore[arg-type]
                )
            )
            result = await db.execute(query)
            record: Row[Any] | RowMapping | None | Any = result.scalars().first()
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
            query = select(cls.model).filter_by(**filter_dict).options(
                selectinload(User.roles_assoc)
            )
            result = await db.execute(query)
            records = result.scalars().all()

            logger.info(f"Найдено {len(records)} записей.")
            return records
        except SQLAlchemyError as e:
            logger.error(f"Ошибка при поиске всех записей по фильтрам {filter_dict}: {e}")
            raise

    @staticmethod
    @async_connect_db(commit=True)
    async def check_roles_in_db(db: AsyncSession):
        """Функция для проверки и создания ролей"""

        # Получаем все существующие роли из базы данных
        result = (await db.execute(select(Role.name))).scalars().all()
        existing_roles = {RoleEnum(role) for role in result}  # Преобразуем str в RoleEnum

        # Все возможные роли из RoleEnum
        required_roles = {role for role in RoleEnum}

        # Определяем роли, которые нужно добавить
        roles_to_add = required_roles - existing_roles
        roles_to_remove = existing_roles - required_roles

        # Добавляем недостающие роли
        for role_name in roles_to_add:
            new_role = Role(name=role_name)
            db.add(new_role)

        # Удаляем лишние роли
        for role_name in roles_to_remove:
            role_del = await db.scalar(select(Role).filter(Role.name == role_name))
            if role_del:
                await db.delete(role_del)

        await db.flush()
