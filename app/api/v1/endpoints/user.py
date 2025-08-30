import re
from datetime import datetime, timezone, timedelta, UTC
from typing import List, TypeVar, Optional
from uuid import uuid4

from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi import APIRouter, Response, Depends, Request, Security, Path, HTTPException, UploadFile, BackgroundTasks, \
    Cookie
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.stream import StreemAPI
from app.core.config import algorithm_env, refresh_token_env, stream_token_env
from app.db.sessions import TransactionSessionDep, SessionDep
from app.api.v1.base_api import AnwillUserAPI
from app.db.models.base_sql import BaseSQL
from app.db.models.enums import BanTimeEnum
from app.db.models.associations import UserRole
from app.db.models.tables import Token, Role, EmailVerificationToken, ChangeEmailVerificationToken, User, Profile, \
    TokenTypeEnum, ResetPasswordToken
from app.db.dao.user import UserDAO, BaseDAO, AuthDAO
from app.db.schemas.user import (SUserRegister, EmailModel, SUserAddDB, PhoneModel, CheckIDModel, ProfileModel,
                                 CheckTokenModel, CheckTimeBan, SUserRefreshPassword, ResetPasswordSchema, ProfileInfo,
                                 SUserInfoRole, CheckEmailModel, CheckPhoneModel, SRoleInfo, RoleModel,
                                 SuccessfulResponseSchema, ProfilePutModel)
from app.db.sessions.utils import async_session_manager
from app.docs.responses_variants import user_get_resps, email_verify_resps, role_get_resps, role_post_resps, \
    role_del_resps, email_phone_resps, register_resps, login_resps, logout_resps, profile_get_resps, profile_put_resps, \
    users_get_resps, password_reset_resps, check_email_resps, check_phone_resps
from app.services.s3.tasks import delete_photo_file, get_photo_file
from app.services.stream.progress import progress_registry
from app.utils.http_exceptions import UserNotFoundException, RoleAlreadyAssignedException, RoleNotAssignedException, \
    DeleteErrorException, EmailAvailableException, EmailBusyException, PostEmailPhoneErrorException, \
    UpdateErrorException, DeleteEmailPhoneErrorException, PhoneAvailableException, PhoneBusyException, \
    UserAlreadyExistsException, IncorrectEmailOrPasswordException, IncorrectPhoneOrPasswordException, \
    UserBannedException, IncorrectPhoneOrEmailException, ForbiddenAccessException, TokenNotFoundException, \
    InvalidJwtException, UserIdNotFoundException, InvalidMatchJwtException, IncorrectRefreshPasswordException, \
    NotValidateException, TokenExpiredException
from app.utils.logger import logger

DAO = TypeVar("DAO", bound=BaseDAO)
PYDANTIC = TypeVar("PYDANTIC", bound=BaseModel)
SQL = TypeVar("SQL", bound=BaseSQL)


class ProfileAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.prefix = f"/me/profile"
        self.tags = ['Profile']
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)

    async def setup_routes(self):
        await self.get_profile()
        await self.put_profile()
        await self.put_avatar()
        await self.delete_avatar()
        await self.put_avatar_status()


    async def get_profile(self):
        @self.router.get("", responses=profile_get_resps)
        async def get_profile(user_data: User = Security(self.get_current_user, scopes=['USER'])) -> ProfileInfo:
            """
            ## Endpoint запроса данных профиля пользователя системы.

            ### Описание
            - Возвращает данные профиля пользователя сделавшего запрос.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            profile = ProfileInfo.model_validate(user_data.profile)
            return profile

    async def put_profile(self):
        @self.router.put("", responses=profile_put_resps)
        async def put_profile(schema: ProfilePutModel, db: AsyncSession = TransactionSessionDep,
                              user_data: User = Security(self.get_current_user, scopes=['USER'])) -> ProfileInfo:
            """
            ## Endpoint обновления профиля пользователя системы.

            ### Описание
            - Endpoint обновляет профиль пользователя
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException

            # Явно загружаем пользователя в текущую сессию
            user = await db.get(User, user_data.id)
            if not user:
                logger.remove()
                raise UserNotFoundException

            profile_dict = schema.model_dump(exclude_none=True)

            try:
                if user.profile is None:
                    new_profile = Profile(**profile_dict)
                    db.add(new_profile)
                    await db.flush()
                    user.profile_id = new_profile.id
                    # Явно добавляем пользователя в сессию для обновления
                    db.add(user)
                else:
                    for key, value in profile_dict.items():
                        setattr(user.profile, key, value)

                await db.commit()
                await db.refresh(user, attribute_names=["profile"])

                profile_dict = user.profile.to_dict_one_lap()
                profile_dict['user_id'] = user.id
                return ProfileInfo(**profile_dict)

            except SQLAlchemyError as e:
                await db.rollback()
                logger.error(f"Ошибка при обновлении профиля пользователя {user.id}: {e}")
                raise UpdateErrorException

    async def put_avatar(self):
        @self.router.put("/avatar/")
        async def put_avatar(
                file_content: UploadFile,
                background: BackgroundTasks,
                user_data: User = Security(self.get_current_user, scopes=['USER']),
                stream_cookie: Optional[str] = Cookie(default=None, alias="stream_token"),
        ) -> JSONResponse:
            """
            **Аутентификация:** Bearer `access_token`.

            **Назначение:** Загружает или обновляет аватарку пользователя (jpg/png/webp до 10 МБ), обрабатывает в фоне.

            **Ответы:**
            - `202 Accepted`
            ```json
            {
              "message": "Загрузка аватарки началась",
              "task_id": "<uuid>",
              "status": "running",
              "sse": {
                "url": "/sse/me/profile/avatar/stream",
                "auth": "cookie(stream_token)"
              },
              "websocket": {
                "url": "/ws/me/profile/avatar/stream",
                "auth": "cookie(stream_token) | Authorization: Bearer <stream_jwt> | ?token=<stream_jwt>"
              }
            }
            ```
              + `Location` header → `/account/me/profile/avatar/status`
              + при необходимости — установка/обновление HttpOnly cookie `stream_token`.

            - Ошибки: `404` (не изображение), `401`/`403`, `500`.

            **Жизненный цикл:**
            ```
            0%  -> queued
            5%  -> validate
            30% -> convert_to_webp
            60% -> make_preview
            85% -> uploading
            95% -> db_write
            100% done | error
            ```

            **Клиент:**
            1. После `202` — открыть SSE с `withCredentials: true`.
            2.WebSocket: подключиться к wss://<host>/account/ws/me/profile/avatar/stream
                        - Аутентификация (приоритет): Cookie: stream_token; затем Authorization: Bearer <stream_jwt>; затем ?token=<stream_jwt>.
            3. При сетевой ошибке — fallback на `GET /account/me/profile/avatar/status`.
            4. Завершение при `status` in {"done","error"}.
            5. После — `GET /me/profile` для обновления ссылок.

            """
            if user_data is None:
                raise UserNotFoundException

            set_stream_cookie = False
            if not stream_cookie:
                set_stream_cookie = True
            else:
                try:
                    payload = jwt.decode(stream_cookie, stream_token_env(), algorithms=[algorithm_env()])  # единый ALGO
                    exp = int(payload.get("exp", 0))
                    now = int(datetime.now(timezone.utc).timestamp())
                    if exp - now < 300:
                        set_stream_cookie = True
                except JWTError:
                    set_stream_cookie = True

            if set_stream_cookie:
                stream_jwt, ttl = StreemAPI.mint_stream_token(user_data.id)
            else:
                stream_jwt = None

            # читаем файл / запускаем процессинг
            content = await file_content.read()
            filename = file_content.filename

            task_id = str(uuid4())
            progress_registry.start(user_data.id, task_id)

            background.add_task(
                StreemAPI.process_avatar_task,
                user_id=user_data.id,
                file_bytes=content,
                filename=filename,
                db_session_factory=async_session_manager.create_session,
            )

            response = JSONResponse(
                status_code=202,
                headers={"Location": "/account/me/profile/avatar/status"},
                content={
                    "message": "Загрузка аватарки началась",
                    "task_id": task_id,
                    "status": "running",
                    "sse": {"url": "/sse/me/profile/avatar/stream", "auth": "cookie(stream_token)"},
                    "websocket": {
                        "url": "/ws/me/profile/avatar/stream",
                        "auth": "cookie(stream_token) | Authorization: Bearer <stream_jwt> | ?token=<stream_jwt>"
                    },
                },
            )

            if stream_jwt:
                response.set_cookie(
                    key="stream_token",
                    value=stream_jwt,
                    httponly=True,
                    secure=True,
                    samesite="none",
                    max_age=StreemAPI.TTL_SECONDS,
                    path="/account",
                )

            return response

    async def put_avatar_status(self):
        @self.router.get("/avatar/status")
        async def put_avatar_status(user: User = Security(self.get_current_user, scopes=['USER'])) -> JSONResponse:
            """
            **Название:** Получение текущего снимка прогресса (polling)

            **Аутентификация:** Требуется `Authorization: Bearer <JWT>` со скоупом `USER`.

            **Назначение:**
            Возвращает актуальный снимок прогресса фоновой задачи для текущего пользователя.
            Если задач нет — `{"status":"idle"}`.

            **Ответ 200 (application/json), примеры:**
            - RUNNING:
            ```json
            {
              "task_id": "1e0e4d7e-...",
              "percent": 60,
              "step": "make_preview",
              "status": "running"
            }
            ```
            - DONE:
            ```json
            {
              "task_id": "1e0e4d7e-...",
              "percent": 100,
              "step": "db_write",
              "status": "done",
              "error": null
            }
            ```
            - ERROR:
            ```json
            {
              "task_id": "1e0e4d7e-...",
              "percent": 85,
              "step": "uploading",
              "status": "error",
              "error": "db_error"
            }
            ```
            - IDLE:
            ```json
            {"status": "idle"}
            ```

            **Другие ответы:**
            - `401 Unauthorized` / `403 Forbidden`

            **Рекомендации по polling:**
            - Интервал опроса: 1000–2000 мс (1–2 секунды).
            - Таймаут запроса: 10–15 секунд.
            - Остановка: при `status` ∈ {"done","error","idle"} (при "idle" можно опрашивать реже — раз в 2–3 сек).
            - Бэкофф: при долгом отсутствии изменений увеличить интервал.
            """
            snap = progress_registry.snapshot(user.id) or {"status": "idle"}
            return JSONResponse(status_code=200, content=snap)

    async def delete_avatar(self):
        @self.router.delete("/avatar/")
        async def delete_avatar(db: AsyncSession = TransactionSessionDep,
                                user_data: User = Security(self.get_current_user, scopes=['USER'])) -> JSONResponse:
            """
            ### Удаление аватарки пользователя

            Эндпоинт удаляет текущую аватарку пользователя (и её превью) из хранилища (S3 или локального), а также отвязывает её от профиля пользователя в базе данных.

            #### Логика работы:
            - Если у пользователя есть аватарка:
              - Удаляет оригинал и превью изображения из хранилища по их ключам.
              - Обнуляет связь профиля с аватаркой (avatar становится None).
              - Все изменения фиксируются в базе.
            - Если аватарки не было — возвращает актуальную информацию о пользователе.

            #### Ответ:
            - 200: Возвращает статус операции.
            - 404: Физическое удаление аватарки из хранилища не удалось, либо ошибка обработки.
            - 500: Ошибка сервера или работы с базой данных.

            Пример успешного ответа:
            """
            try:
                user = await db.get(User, user_data.id)
                if user.profile.avatar:
                    orig_key = user.profile.avatar.orig_photo
                    preview_key = user.profile.avatar.preview_photo
                    logger.debug(f'Удаляем из S3: {orig_key}, {preview_key}')
                    del_orig = await delete_photo_file(link=orig_key)
                    del_preview = await delete_photo_file(link=preview_key)
                    if del_orig and del_preview:
                        user.profile.avatar = None
                    else:
                        logger.error('Физическое удаление аватарки из s3-хранилища не удалось')
                        raise HTTPException(status_code=404, detail="The removal of the avatar was unsuccessful")

                await db.flush()
                logger.info(f"Удалена аватарка у пользователя: {user.__repr__}")
                return JSONResponse(status_code=200, content={'message': "Аватарка очищена."})
            except SQLAlchemyError as exp:
                await db.rollback()
                logger.error(f"Ошибка при удалении аватарки в БД PostgreSql: {exp}")
                raise UpdateErrorException
            except Exception as exp:
                logger.error(f"Неожиданная ошибка при удалении аватарки: {exp}")
                await db.rollback()
                raise HTTPException(
                    status_code=404, detail="Error while processing image"
                )


class AdminAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.prefix = f"/user"
        self.tags = ['Admin Panel']
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)

    async def setup_routes(self):

        await self.get_users()
        await self.get_user_id_by_email()
        await self.get_user_by_id()
        await self.delete_user_by_id()
        await self.get_user_by_email()
        await self.get_user_by_phone_number()
        await self.get_user_roles()
        await self.post_user_role()
        await self.delete_user_role()
        await self.ban_on_user()
        await self.ban_off_user()
        await self.send_verify_email_by_user_id()

    async def get_users(self):
        @self.router.get("s/", responses=users_get_resps)
        async def get_users(db: AsyncSession = SessionDep,
                            adm_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN'])) -> List[
            SUserInfoRole]:
            """
            ## Endpoint запроса списка всех пользователей системы.

            ### Описание
            - Возвращает список всех пользователей системы.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if not adm_data:
                raise UserNotFoundException
            all_user = await UserDAO.find_all(db=db, filters=None)
            all_user = [SUserInfoRole.model_validate(user_data) for user_data in all_user]

            return all_user

    async def get_user_id_by_email(self):
        @self.router.get("/id/{address}")
        async def get_user_id_by_email(address: EmailStr, db: AsyncSession = SessionDep):
            """
            ## Endpoint запроса данных пользователя системы по email.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            email = CheckEmailModel(email=address)
            check_user = await UserDAO.find_one_or_none(db=db, filters=email)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(check_user)
            return user.id

    async def get_user_by_id(self):
        @self.router.get("/{id}", responses=user_get_resps)
        async def get_user_by_id(db: AsyncSession = SessionDep, check_id: CheckIDModel = Depends(),
                                 user_data: User = Security(self.get_current_user,
                                                            scopes=['ADMIN', 'SYSADMIN'])) -> SUserInfoRole:
            """
            ## Endpoint запроса данных пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none(db=db, filters=check_id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(check_user)
            return user

    async def delete_user_by_id(self):
        @self.router.delete("/{id}")
        async def delete_user_by_id(db: AsyncSession = TransactionSessionDep, check_id: CheckIDModel = Depends(),
                                    user_data: User = Security(self.get_current_user,
                                                               scopes=['ADMIN', 'SYSADMIN'])) -> JSONResponse:
            """
            ## Endpoint запроса данных пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none(db=db, filters=check_id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            await UserDAO.delete(db=db, filters=check_id)
            return JSONResponse(status_code=200, content={'message': f'Пользователь с {check_id} успешно удален!'})

    async def send_verify_email_by_user_id(self):
        @self.router.post("/{id}/email/verify", responses=email_verify_resps)
        async def send_verify_email(response: Response,
                                    db: AsyncSession = SessionDep, check_id: CheckIDModel = Depends(),
                                    user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN'])):

            """
            ## Endpoint запроса на верификацию email адреса.

            ### Описание
            - Генерирует токен и с помощью его формирует ссылку для верификации.
            - Отправляет ссылку на email пользователя.
            - Верификация  проходит автоматически при переходе по ссылке.
            - Возвращает сообщение о статусе операции.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none(db=db, filters=check_id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException

            result = await self.send_verify_email_to_user(db=db, email=check_user.email)

            response.headers["X-Success-Code"] = result.get("code", "2003")
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": result["message"]
                }
            )

    async def get_user_by_email(self):
        @self.router.get("/email/{address}", responses=user_get_resps)
        async def get_email(address: EmailStr, db: AsyncSession = SessionDep,
                            user_data: User = Security(self.get_current_user,
                                                       scopes=['ADMIN', 'SYSADMIN'])) -> SUserInfoRole:
            """
            ## Endpoint запроса данных пользователя системы по email.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            email = CheckEmailModel(email=address)
            check_user = await UserDAO.find_one_or_none(db=db, filters=email)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(check_user)
            return user

    async def get_user_by_phone_number(self):
        @self.router.get("/phone/{number}", responses=user_get_resps)
        async def get_email(number: str, db: AsyncSession = SessionDep,
                            user_data: User = Security(self.get_current_user,
                                                       scopes=['ADMIN', 'SYSADMIN'])) -> SUserInfoRole:
            """
            ## Endpoint запроса данных пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            phone = CheckPhoneModel(phone_number=number)
            check_user = await UserDAO.find_one_or_none(db=db, filters=phone)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(check_user)
            return user

    async def get_user_roles(self):
        @self.router.get("/{id}/role", responses=role_get_resps)
        async def get_user_roles(user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN']),
                                 check_id: CheckIDModel = Depends(), db: AsyncSession = SessionDep) -> SRoleInfo:
            """
            ## Endpoint информации о всех доступных ролях для пользователя

            ### Описание
            - Возвращает роли пользователя системы в виде списка.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none(db=db, filters=check_id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            roles = SRoleInfo.model_validate(check_user)
            return roles

    async def post_user_role(self):
        @self.router.post("/{id}/role", responses=role_post_resps)
        async def post_user_role(user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN']),
                                 check_id: CheckIDModel = Depends(), db: AsyncSession = TransactionSessionDep,
                                 schema_role: RoleModel = Depends()) -> SUserInfoRole:
            """
            ## Endpoint добавляет роль для пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none_by_id(db=db, data_id=check_id.id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            if schema_role.role in check_user.roles:
                logger.remove()
                raise RoleAlreadyAssignedException
            stmt = (
                select(Role)
                .options(selectinload(Role.users_assoc).joinedload(UserRole.user))
                .where(Role.name == schema_role.role)
            )
            role = await db.scalar(stmt)
            # Проверяем, что пользователя еще нет в ассоциации для роли
            if any(assoc.user_id == check_user.id for assoc in role.users_assoc):
                logger.remove()
                raise RoleAlreadyAssignedException

            # Добавляем связь между role и user
            check_user.roles_assoc.append(UserRole(role=role))  # И к пользователю
            await db.flush()
            # Валидация и возврат результата
            user = SUserInfoRole.model_validate(check_user)
            return user

    async def delete_user_role(self):
        @self.router.delete("/{id}/role", responses=role_del_resps)
        async def delete_user_role(user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN']),
                                   check_id: CheckIDModel = Depends(), db: AsyncSession = TransactionSessionDep,
                                   schema_role: RoleModel = Depends()) -> SUserInfoRole:
            """
            ## Endpoint удаляет роль для пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none_by_id(db=db, data_id=check_id.id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            if schema_role.role not in check_user.roles:
                logger.remove()
                raise RoleNotAssignedException
            try:
                await db.execute(
                    delete(UserRole).where(UserRole.user_id == check_user.id, UserRole.role_name == schema_role.role))
                await db.flush()
                await db.refresh(check_user)
                # Валидация и возврат результата
                user = SUserInfoRole.model_validate(check_user)
                return user
            except SQLAlchemyError as e:
                logger.error(f'Ошибка у user: {check_user.id}, {self.name_model} - delete_role: {e}')
                logger.remove()
                raise DeleteErrorException

    async def ban_on_user(self):
        @self.router.put("/{id}/ban_on", responses=role_post_resps)
        async def ban_on_user(user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN']),
                              check_id: CheckIDModel = Depends(), db: AsyncSession = TransactionSessionDep,
                              ban_time: CheckTimeBan = Depends()) -> SUserInfoRole:
            """
            ## Endpoint позволяет блокировать пользователя.

            ### Описание
            - Перманентная блокировка на сто лет.
            - Приложение автоматически снимает блокировку по назначенному времени.
            - Возвращает данные пользователя системы.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none_by_id(db=db, data_id=check_id.id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            check_user.is_banned = True
            ban = BanTimeEnum(ban_time.period)
            check_user.ban_until = datetime.now(timezone.utc) + ban.duration
            await db.flush()
            await db.refresh(check_user)
            user = SUserInfoRole.model_validate(check_user)
            return user

    async def ban_off_user(self):
        @self.router.put("/{id}/ban_off", responses=role_post_resps)
        async def ban_off_user(user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN']),
                               check_id: CheckIDModel = Depends(),
                               db: AsyncSession = TransactionSessionDep) -> SUserInfoRole:
            """
            ## Endpoint позволяет разблокировать пользователя.

            ### Описание
            - Отключает бан и очищает время блокировки.
            - Возвращает данные пользователя системы.
            - Этот эндпоинт доступен только для администраторов.
              Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none_by_id(db=db, data_id=check_id.id)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            check_user.is_banned = False
            check_user.ban_until = None
            await db.flush()
            await db.refresh(check_user)
            user = SUserInfoRole.model_validate(check_user)
            return user


class UserAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.prefix = f"/me"
        self.tags = ['Me']
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)

    async def setup_routes(self):
        await self.get_me()
        await self.delete_me()
        await self.get_roles()
        await self.get_email()
        await self.post_email()
        await self.put_email()
        await self.delete_email()
        await self.send_verify_email()
        await self.get_phone_number()
        await self.post_phone_number()
        await self.put_phone_number()
        await self.delete_phone_number()
        await self.put_password()
        await self.get_id_user_by_email()

    async def get_me(self):
        @self.router.get("", responses=user_get_resps)
        async def get_me(user_data: User = Security(self.get_current_user, scopes=['USER'])) -> SUserInfoRole:
            """
            ## Endpoint запроса данных пользователя системы.

            ### Описание
            - Возвращает данные пользователя сделавшего запрос.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def delete_me(self):
        @self.router.delete("")
        async def delete_me(db: AsyncSession = TransactionSessionDep,
                            user_data: User = Security(self.get_current_user, scopes=['USER'])) -> JSONResponse:
            """
            ## Endpoint запроса данных пользователя системы.

            ### Описание
            - Возвращает данные пользователя сделавшего запрос.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            schema_id = CheckIDModel(id=user_data.id)
            await UserDAO.delete(db=db, filters=schema_id)
            return JSONResponse(status_code=200, content={'message': 'Вы успешно удалили свой профиль.'})

    async def get_roles(self):
        @self.router.get("/role", responses=role_get_resps)
        async def get_roles(user_data: User = Security(self.get_current_user, scopes=['DEVELOPER', 'ADMIN', 'SYSADMIN'])
                            ) -> SRoleInfo:
            """
            ## Endpoint информации о всех доступных ролях для пользователя

            ### Описание
            - Возвращает роли пользователя системы в виде списка.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            roles = SRoleInfo.model_validate(user_data)
            return roles

    async def get_email(self):
        @self.router.get("/email", responses=email_phone_resps)
        async def get_email(user_data: User = Security(self.get_current_user, scopes=['USER'])) -> CheckEmailModel:
            """
            ## Endpoint запроса адреса email пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            if user_data.email is None:
                logger.remove()
                raise EmailAvailableException
            email = CheckEmailModel.model_validate(user_data)
            return email

    async def post_email(self):
        @self.router.post("/email", responses=user_get_resps)
        async def post_email(email: CheckEmailModel, db: AsyncSession = TransactionSessionDep,
                             user_data: User = Security(self.get_current_user, scopes=['USER'])) -> SUserInfoRole:
            """
            ## Endpoint добавления email пользователя системы.

            ### Описание
            - Endpoint добавляет email, если его еще нет у пользователя
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_email = (await db.execute(select(User).where(User.email == email.email))).scalar_one_or_none()
            if check_email:
                logger.remove()
                raise EmailBusyException
            if user_data.email:
                logger.remove()
                raise PostEmailPhoneErrorException
            user_data.email = email.email
            await db.flush()
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def put_email(self):
        @self.router.put("/email", responses=user_get_resps)
        async def put_email(email: CheckEmailModel, db: AsyncSession = TransactionSessionDep,
                            user_data: User = Security(self.get_current_user, scopes=['USER'])) -> SUserInfoRole:
            """
            ## Endpoint обновления email пользователя системы.

            ### Описание
            - Endpoint обновляет email пользователя
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_email = (await db.execute(select(User).where(User.email == email.email))).scalar_one_or_none()
            if check_email:
                logger.remove()
                raise EmailBusyException
            try:
                verify = await self.send_change_verify_email_to_user(db=db, new_email=email.email)
                return verify
            except SQLAlchemyError as e:
                logger.error(f"Ошибка при обновлении email: {e}")
                raise UpdateErrorException

    async def delete_email(self):
        @self.router.delete("/email", responses=user_get_resps)
        async def delete_email(db: AsyncSession = TransactionSessionDep,
                               user_data: User = Security(self.get_current_user,
                                                          scopes=['DEVELOPER', 'ADMIN', 'SYSADMIN'])) -> SUserInfoRole:
            """
            ## Endpoint удаления email пользователя системы.

            ### Описание
            - Endpoint удаляет email пользователя, если есть номер телефона.
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            if user_data.phone_number is None:
                logger.remove()
                raise DeleteEmailPhoneErrorException
            user_data.email = None
            await db.flush()
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def send_verify_email(self):
        @self.router.post("/email/verify", responses=email_verify_resps)
        async def send_verify_email(response: Response,
                                    user_data: User = Security(self.get_current_user, scopes=['USER']),
                                    db: AsyncSession = TransactionSessionDep):
            """
            ## Endpoint запроса на верификацию email адреса.

            ### Описание
            - Генерирует токен и с помощью его формирует ссылку для верификации.
            - Отправляет ссылку на email пользователя.
            - Верификация  проходит автоматически при переходе по ссылке.
            - Возвращает сообщение о статусе операции.
            - Endpoint доступен для всех авторизовавшихся пользователей.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            result = await self.send_verify_email_to_user(db=db, email=user_data.email)

            response.headers["X-Success-Code"] = result.get("code", "2003")
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": result["message"]
                }
            )

    async def get_phone_number(self):
        @self.router.get("/phone", responses=email_phone_resps)
        async def get_email(user_data: User = Security(self.get_current_user, scopes=['USER'])) -> CheckPhoneModel:
            """
            ## Endpoint запроса номера телефона пользователя системы.

            ### Описание
            - Возвращает данные пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.
            - Определяет автоматически email и номер телефона.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            if user_data.phone_number is None:
                logger.remove()
                raise PhoneAvailableException
            phone = CheckPhoneModel.model_validate(user_data)
            return phone

    async def post_phone_number(self):
        @self.router.post("/phone", responses=user_get_resps)
        async def post_phone_number(phone_number: CheckPhoneModel, db: AsyncSession = TransactionSessionDep,
                                    user_data: User = Security(self.get_current_user,
                                                               scopes=['USER'])) -> SUserInfoRole:
            """
            ## Endpoint добавления номера телефона пользователя системы.

            ### Описание
            - Endpoint добавляет номер телефона, если его еще нет у пользователя
            - Автоматически конвертирует его в формат +79991234567
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_phone_number = (await db.execute(
                select(User).where(User.phone_number == phone_number.phone_number))).scalar_one_or_none()
            if check_phone_number:
                logger.remove()
                raise PhoneBusyException
            if user_data.phone_number:
                logger.remove()
                raise PostEmailPhoneErrorException
            user_data.phone_number = phone_number.phone_number
            await db.flush()
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def put_phone_number(self):
        @self.router.put("/phone", responses=user_get_resps)
        async def put_phone_number(phone_number: CheckPhoneModel, db: AsyncSession = TransactionSessionDep,
                                   user_data: User = Security(self.get_current_user, scopes=['USER'])) -> SUserInfoRole:
            """
            ## Endpoint обновления номера телефона пользователя системы.

            ### Описание
            - Endpoint обновляет номер телефона пользователя
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_phone_number = (await db.execute(
                select(User).where(User.phone_number == phone_number.phone_number))).scalar_one_or_none()
            if check_phone_number:
                logger.remove()
                raise PhoneBusyException
            try:
                user_data.phone_number = phone_number.phone_number
                await db.flush()
            except SQLAlchemyError as e:
                logger.error(f"Ошибка при обновлении номера телефона: {e}")
                raise UpdateErrorException
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def delete_phone_number(self):
        @self.router.delete("/phone", responses=user_get_resps)
        async def put_phone_number(db: AsyncSession = TransactionSessionDep,
                                   user_data: User = Security(self.get_current_user, scopes=['DEVELOPER', 'ADMIN',
                                                                                             'SYSADMIN'])) -> SUserInfoRole:
            """
            ## Endpoint удаления номера телефона пользователя системы.

            ### Описание
            - Endpoint удаляет номер телефона пользователя, если есть email.
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            if user_data.email is None:
                logger.remove()
                raise DeleteEmailPhoneErrorException
            user_data.phone_number = None
            await db.flush()
            user = SUserInfoRole.model_validate(user_data)
            return user

    async def put_password(self):
        @self.router.put("/password", responses=user_get_resps)
        async def put_password(schema: SUserRefreshPassword, db: AsyncSession = TransactionSessionDep,
                               user_data: User = Security(self.get_current_user, scopes=['USER'])) -> JSONResponse:
            """
            ## Endpoint обновления email пользователя системы.

            ### Описание
            - Endpoint обновляет email пользователя
            - Endpoint доступен для всех авторизовавшихся пользователей.
            - Возвращает данные пользователя сделавшего запрос.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """

            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            pass_verify = await AuthDAO.verify_password(schema.password, user_data.password)
            if not pass_verify:
                logger.remove()
                raise IncorrectRefreshPasswordException
            try:
                user_data.password = schema.new_password
                await db.flush()
            except SQLAlchemyError as e:
                logger.error(f"Ошибка при обновлении пароля: {e}")
                raise UpdateErrorException
            return JSONResponse(status_code=200, content={'message': 'Пароль успешно обновлен.'})

    async def get_id_user_by_email(self):
        @self.router.get("/email/", responses=user_get_resps)
        async def get_email(db: AsyncSession = SessionDep, address: CheckEmailModel = Depends(CheckEmailModel),
                            user_data: User = Depends(self.get_current_user)) -> int:
            """
            ## Endpoint запроса id пользователя системы по email.

            ### Описание
            - Возвращает id пользователя системы.
            - Проверяется уровень доступа, при положительном результате обрабатывает запрос.
                Данный функционал доступен только для администраторов.
                Если текущий пользователь не является USER, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if user_data is None:
                logger.remove()
                raise UserNotFoundException
            check_user = await UserDAO.find_one_or_none(db=db, filters=address)
            if check_user is None:
                logger.remove()
                raise UserNotFoundException
            user = SUserInfoRole.model_validate(check_user)
            return user.id


class AuthAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.tags = ['Auth']
        self.router = APIRouter(tags=self.tags)

    async def setup_routes(self):
        await self.register()
        await self.login()
        await self.logout()
        await self.refresh()

    async def register(self):
        @self.router.post("/register", responses=register_resps)
        async def register_user(user_data: SUserRegister, db: AsyncSession = TransactionSessionDep) -> JSONResponse:
            """
            ## Регистрация нового пользователя

            ### Описание
            - Этот эндпоинт используется для регистрации нового пользователя. Пользователь должен указать либо адрес электронной почты (`email`), либо номер телефона (`phone_number`), а также другую необходимую информацию.
            - Чтобы зарегистрироваться с правами администратора используйте тестовые адреса email: **test_adm^@example.com**. Вместо **^** используйте любое число от 2 до 30. Например, **test_adm17@example.com**.

            ### Требования
            - **Либо `email`, либо `phone_number`** должны быть указаны. Если оба поля пустые, запрос будет отклонен.
            - Пароль должен быть подтвержден путем указания одинаковых значений в полях `password` и `confirm_password`.

            ### Схема запроса
            ```json
            {
                "phone_number": "string | null",  // Номер телефона в международном формате, начинающийся с "+"
                "email": "string | null",         // Адрес электронной почты
                "password": "string",             // Пароль (от 5 до 50 символов)
                "confirm_password": "string"      // Подтверждение пароля (должно совпадать с `password`)
            }
            """
            user_email, user_phone = None, None
            email_mess, phone_mess = '', ''

            if user_data.email:
                email_mess = f"email {user_data.email}"
                user_email = await UserDAO.find_one_or_none(db=db, filters=EmailModel(email=user_data.email))

            if user_data.phone_number:
                phone_mess = f"телефоном {user_data.phone_number}"
                user_phone = await UserDAO.find_one_or_none(db=db,
                                                            filters=PhoneModel(phone_number=user_data.phone_number))

            if user_data.email or user_data.phone_number:
                logger.info(f"Попытка регистрации нового пользователя с {', '.join([email_mess, phone_mess])}")
            if user_email or user_phone:
                logger.remove()
                raise UserAlreadyExistsException
            user_data_dict = user_data.model_dump()
            del user_data_dict['confirm_password']
            new_user = await UserDAO.add(db=db, values=SUserAddDB(**user_data_dict))
            new_user: User
            profile_data = ProfileModel(**user_data_dict)
            profile_data_dict = profile_data.model_dump()
            new_user.profile = Profile(**profile_data_dict)

            # Генерируем токен доступа
            scopes_rights = ["USER"]
            list_adm_email = ['dblmokdima@gmail.com', 'egor.martinenko01@gmail.com']
            if new_user.email in list_adm_email:
                scopes_rights.append("ADMIN")
                scopes_rights.append("SYSADMIN")
            list_dev_email = ['dblmokdima@gmail.com', 'egor.martinenko01@gmail.com']
            if new_user.email in list_dev_email:
                scopes_rights.append("DEVELOPER")

            for r_scope in scopes_rights:
                stmt = (
                    select(Role)
                    .options(selectinload(Role.users_assoc).joinedload(UserRole.user))
                    .where(Role.name == r_scope)
                )
                roles = await db.scalars(stmt)
                for role in roles:
                    role.users_assoc.append(UserRole(user=new_user))
            user = await UserDAO.find_one_or_none_by_id_with_tokens(db=db, data_id=new_user.id)
            access_token, refresh_token = await AuthDAO.creating_recording_all_token_to_user(db=db, user=user,
                                                                                             token_scopes=scopes_rights)
            response = await self.response_tokens_in_cookie(access_token=access_token, refresh_token=refresh_token, user_id=user.id)
            if user_data.email:
                await self.send_verify_email_to_user(email=user_data.email, db=db)

            logger.info(
                f"Пользователь {new_user.id}"
                f" успешно зарегистрирован.")
            return response

    async def login(self):
        @self.router.post("/login", responses=login_resps)
        async def login_user(form_data: OAuth2PasswordRequestForm = Depends(),
                             db: AsyncSession = TransactionSessionDep):
            """
            ### Endpoint авторизации пользователя

            Эндпоинт предоставляет возможность авторизации пользователя с использованием email или номера телефона.

            #### Содержимое запроса (form-data):

            1. **`grant_type`** (обязательное поле)
               - Указывает тип потока авторизации.
               - Допустимые значения:
                 - `password` - для аутентификации с использованием учетных данных пользователя.

            2. **`username`** (обязательное поле для `grant_type=password`)
               - Имя пользователя, может быть email или номер телефона.

            3. **`password`** (обязательное поле для `grant_type=password`)
               - Пароль пользователя.

            4. **`scope`** (опционально)
               - Указывает области доступа (scopes), предоставляемые в процессе авторизации.
               - По умолчанию: `USER`.

            5. **`client_id`** (опционально)
               - Уникальный идентификатор клиента.

            6. **`client_secret`** (опционально)
               - Секретный ключ клиента.

            #### Логика работы:

             **Авторизация пользователя (`grant_type=password`)**:
               - Проверяет, является ли `username` email или номером телефона.
               - Аутентифицирует пользователя на основе предоставленных учетных данных.
               - Генерирует `access_token` (срок действия 30 минут) и `refresh_token` (срок действия 7 дней).
               - Возвращает `access_token` в теле ответа и устанавливает `refresh_token` в cookie с параметром `HttpOnly`.

            """

            username: str = form_data.username
            password: str = form_data.password

            # Проверка, является ли username email или телефон
            if re.match(r"[^@]+@[^@]+\.[^@]+", username):  # Если это email
                username: EmailStr
                user_model = EmailModel(email=username)
                user = await AuthDAO.authenticate_user(db=db, email=user_model.email, password=password)
                if user is None:
                    logger.remove()
                    raise IncorrectEmailOrPasswordException
            elif re.match(r"^\+\d{5,15}$", username):  # Если это телефон
                user_model = PhoneModel(phone_number=username)
                user = await AuthDAO.authenticate_user(db=db, phone=user_model.phone_number, password=password)
                if user is None:
                    logger.remove()
                    raise IncorrectPhoneOrPasswordException
            else:
                raise IncorrectPhoneOrEmailException
            if user.is_banned:
                logger.remove()
                raise UserBannedException
            token_scopes_stmt = (
                select(UserRole.role_name)
                .where(UserRole.user_id == user.id)
            )

            token_scopes_db = await db.scalars(token_scopes_stmt)
            token_scopes = {role.name for role in token_scopes_db}
            # Получаем запрошенные роли из токена
            scopes = set(form_data.scopes)  # Доступные роли из токена
            for sc in scopes:
                if not sc in token_scopes:
                    logger.remove()
                    raise ForbiddenAccessException
            if scopes:
                # Находим пересечение ролей
                token_scopes = list(token_scopes.intersection(scopes))

            access_token, refresh_token = await AuthDAO.creating_recording_all_token_to_user(db=db, user=user,
                                                                                             token_scopes=token_scopes)
            response = await self.response_tokens_in_cookie(access_token=access_token, refresh_token=refresh_token, user_id=user.id)
            await db.commit()
            logger.info(
                f"Пользователь {user.id}"
                f" успешно вошел в систему. Доступы: {list(token_scopes)}")
            return response

    async def logout(self):
        @self.router.post("/logout", responses=logout_resps)
        async def logout_user(response: Response, user_data: User = Security(self.get_current_user, scopes=['USER'])
                              ) -> SuccessfulResponseSchema:
            """
            ## Endpoint выхода из системы (Logout)

            ### Описание
            Этот эндпоинт выполняет выход пользователя из системы, полностью завершая его сессию.
             При вызове удаляются все cookie, связанные с аутентификацией, включая токены доступа и защиты от CSRF.
             Также очищает активный токен из БД.

            ### Требования
            - Эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie).

            ### Действия
            - Удаляет следующие cookie:
              - `users_access_token` — токен доступа.
              - `refresh_token` — токен обновления.
              - `csrf_token` — токен защиты от CSRF.
            - Устанавливает заголовки для предотвращения кэширования.
            - Возвращает сообщение об успешном выходе из системы.
            """
            # Удаление всех токенов из куки
            user_data.refresh_token_assoc.ban = True
            response.delete_cookie(key="refresh_token")
            response.delete_cookie(key="site_token")
            response.delete_cookie(key="csrf_token")

            # Для безопасности можно добавить заголовки, запрещающие кэширование
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

            logger.info(f"Пользователь {user_data.id} вышел из системы")

            return SuccessfulResponseSchema(**{'message': 'Пользователь успешно вышел из системы'})

    async def refresh(self):
        @self.router.put("/refresh", responses=login_resps)
        async def refresh(request: Request, db: AsyncSession = TransactionSessionDep):
            try:
                refresh_token_cookie = request.cookies.get("refresh_token")
                if not refresh_token_cookie:
                    raise TokenNotFoundException

                # Декодируем refresh тем "refresh"-секретом
                try:
                    payload_refresh = jwt.decode(
                        refresh_token_cookie,
                        refresh_token_env(),
                        algorithms=[algorithm_env()],
                    )
                    user_id = payload_refresh.get("sub")
                except JWTError:
                    raise InvalidMatchJwtException

                if not user_id:
                    raise UserIdNotFoundException
                user_id = int(user_id)
                user = await UserDAO.find_one_or_none_by_id_with_tokens(data_id=user_id, db=db)
                if user is None:
                    raise UserNotFoundException

                check_refresh_token: Token | None = (
                    await db.execute(
                        select(Token).where(
                            Token.user_id == user.id,
                            Token.token_type == TokenTypeEnum.REFRESH,
                            Token.ban == False,
                            Token.token == refresh_token_cookie,
                        )
                    )
                ).scalar_one_or_none()

                if not check_refresh_token:
                    raise InvalidMatchJwtException

                token_scopes_stmt = (select(UserRole.role_name).where(UserRole.user_id == user.id))
                token_scopes_db = await db.scalars(token_scopes_stmt)
                token_scopes_db = set(token_scopes_db.all())
                token_scopes = list(token_scopes_db)

                if token_scopes:
                    token_scopes = list(token_scopes_db.intersection(token_scopes))
                refresh_token_to_set: str = refresh_token_cookie

                now_utc = datetime.now(UTC)
                time_left: timedelta = check_refresh_token.expires_at - now_utc

                if time_left <= timedelta(days=1):
                    check_refresh_token.ban = True
                    check_refresh_token.expires_at = now_utc

                    await db.flush()

                    access_token_new, refresh_token_new = await AuthDAO.creating_recording_all_token_to_user(
                        db=db,
                        user=user,
                        token_scopes=token_scopes,
                    )
                    access_token = access_token_new
                    refresh_token_to_set = refresh_token_new
                else:
                    access_token = await AuthDAO.creating_recording_access_token_to_user(
                        user=user,
                        token_scopes=token_scopes,
                    )

                response = await self.response_tokens_in_cookie(
                    access_token=access_token,
                    refresh_token=refresh_token_to_set,
                    user_id=user.id,
                )

                logger.info(f"Пользователь {user.id} обновил токены. Доступы: {token_scopes}."
                            f" Ротация refresh: {time_left <= timedelta(days=1)}")
                return response

            except JWTError:
                # токен испорчен/просрочен и т.п.
                raise NotValidateException


class SecurityAPI(AuthAPI):
    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.tags = ['Security']
        self.router = APIRouter(tags=self.tags)

    async def setup_routes(self):
        await self.check_email()
        await self.check_phone()
        await self.get_roles()
        await self.send_reset_password()

    async def send_reset_password(self):
        @self.router.post("/password/reset", responses=password_reset_resps)
        async def send_reset_password(email: CheckEmailModel, db: AsyncSession = TransactionSessionDep):
            """
            ## Endpoint запроса на сброс пароля.

            ### Описание
            - Генерирует токен и с помощью его формирует ссылку для страницы сброса пароля.
            - Отправляет ссылку на email пользователя.
            - Пользователь переходит по ссылке и вводит новый пароль.
            - Проходит проверка токена и далее смена пароля
            - Возвращает сообщение о статусе операции.

            ### Требования
            - Этот эндпоинт требует передачи email адреса в теле запроса.
            - Пользователь не должен быть авторизован.
            """

            verify = await self.send_reset_password_to_user(db=db, email=email.email)
            return verify

    async def check_email(self):
        @self.router.get("/email", responses=check_email_resps)
        async def check_email(data: CheckEmailModel = Depends(), db: AsyncSession = SessionDep):
            """
            ## Endpoint проверки существования email в базе данных.
            ### Описание
            Этот эндпоинт доступен для всех.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь не должен быть авторизован.
            """
            logger.info(f"Проверка email: {data.email}")

            try:
                exists = await UserDAO.find_one_or_none(db=db, filters=data)
                if exists:
                    logger.info(f"Email {data.email} существует в базе.")
                    return JSONResponse(
                        status_code=200,
                        content={
                            "status": "success",
                            "message": "Email exists",
                            "data": {"exists": True}
                        }
                    )
                else:
                    logger.info(f"Email {data.email} не найден.")
                    return JSONResponse(
                        status_code=200,
                        content={
                            "status": "success",
                            "message": "Email not found",
                            "data": {"exists": False}
                        }
                    )
            except Exception as e:
                logger.error(f"Ошибка при проверке email: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "message": "Database error",
                        "error": str(e)
                    }
                )

    async def check_phone(self):
        @self.router.get("/phone", responses=check_phone_resps)
        async def check_phone(data: CheckPhoneModel = Depends(), db: AsyncSession = SessionDep):
            """
            ## Endpoint проверки существования номера телефона в базе данных.
            ### Описание
            Этот эндпоинт доступен для всех.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь не должен быть авторизован.
            """
            logger.info(f"Проверка номера телефона: {data.phone_number}")

            try:
                exists = await UserDAO.find_one_or_none(db=db, filters=data)

                if exists:
                    logger.info(f"Номер телефона {data.phone_number} существует в базе.")
                    return JSONResponse(
                        status_code=200,
                        content={
                            "status": "success",
                            "message": "Phone number exists",
                            "data": {"exists": True}
                        }
                    )
                else:
                    logger.info(f"Номер телефона {data.phone_number} не найден.")
                    return JSONResponse(
                        status_code=200,
                        content={
                            "status": "success",
                            "message": "Phone number not found",
                            "data": {"exists": False}
                        }
                    )
            except Exception as e:
                logger.error(f"Ошибка при проверке email: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "message": "Database error",
                        "error": str(e)
                    }
                )

    async def get_roles(self):
        @self.router.get("/roles", responses=role_get_resps)
        async def get_roles(db: AsyncSession = SessionDep,
                            user_data: User = Security(self.get_current_user, scopes=['ADMIN', 'SYSADMIN'])):
            """
            ## Endpoint извлекает все роли доступные в системе.
            ### Описание
            Возвращает роли пользователя системы в виде списка.
            Этот эндпоинт доступен только для администраторов.
            Если текущий пользователь не является ADMIN, SYSADMIN, доступ будет запрещен.

            ### Требования
            - Этот эндпоинт не требует передачи данных в теле запроса.
            - Пользователь должен быть авторизован (наличие токена в cookie-файле).
            """
            if not user_data:
                raise UserNotFoundException
            result = await db.execute(select(Role.name))
            roles = result.scalars().all()
            roles = [role.name for role in roles]
            roles = SRoleInfo(roles=roles)
            return roles


class BackgroundAPI(AuthAPI):
    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.tags = ['Background']
        self.router = APIRouter(tags=self.tags)

    async def setup_routes(self):
        await self.verify_email()
        await self.verify_email_for_change_email()
        await self.applying_new_password()
        await self.get_file_from_s3_without_id()

    async def verify_email(self):
        @self.router.get("/email/verify/{token}", response_class=HTMLResponse)
        async def verify_email(token: str = Path(), db: AsyncSession = TransactionSessionDep):
            """
            ## Endpoint верификации email адреса.

            ### Описание
            - Ручной способ верификации по токену.
            - Возвращает сообщение о статусе операции.
            - Endpoint доступен для всех.

            ### Требования
            - Этот эндпоинт требует передачи данных в строке запроса.
            - Пользователь не должен быть авторизован.
            """
            verify_token = CheckTokenModel(token=token)
            token_data = await db.execute(
                select(EmailVerificationToken).where(EmailVerificationToken.token == verify_token.token))
            token_data = token_data.scalar_one_or_none()
            if not token_data:
                return TokenNotFoundException
            if datetime.now(timezone.utc) > token_data.expires_at or token_data.ban:
                return TokenExpiredException
            email_schema = CheckEmailModel(email=token_data.email)  # type: ignore
            check_user = await UserDAO.find_one_or_none(db=db, filters=email_schema)
            if not check_user:
                return UserNotFoundException
            token_data.ban = True
            check_user.is_email_confirmed = True
            await db.flush()
            return JSONResponse(
                status_code=200,
                content={
                    'message': 'Email Successfully confirmed'
                },
                headers={"X-Success-Code": "2032"}
            )

    async def verify_email_for_change_email(self):
        @self.router.get("/email/change/verify/{token}")
        async def verify_email_for_change_email(token: str = Path(), db: AsyncSession = TransactionSessionDep):
            """
            ## Endpoint верификации нового email адреса.

            ### Описание
            - Ручной способ верификации нового email адреса по токену.
            - Возвращает сообщение о статусе операции и меняет email при удаче.
            - Endpoint доступен для всех.

            ### Требования
            - Этот эндпоинт требует передачи данных в строке запроса.
            - Пользователь не должен быть авторизован.
            """
            verify_token = CheckTokenModel(token=token)
            token_data = await db.execute(
                select(ChangeEmailVerificationToken).where(ChangeEmailVerificationToken.token == verify_token.token))
            token_data = token_data.scalar_one_or_none()
            if not token_data:
                return TokenNotFoundException
            if datetime.now(timezone.utc) > token_data.expires_at or token_data.ban:
                return TokenExpiredException
            email_schema = CheckEmailModel(email=token_data.email)  # type: ignore
            check_user = await UserDAO.find_one_or_none(db=db, filters=email_schema)
            if not check_user:
                return UserNotFoundException
            try:

                token_data.ban = True

                check_user.email = token_data.new_email
                check_user.is_email_confirmed = True
                await db.flush()
            except SQLAlchemyError as e:
                logger.error(f"Ошибка при обновлении email: {e}")
                raise UpdateErrorException
            user = SUserInfoRole.model_validate(check_user)
            answer = user.model_dump(exclude_none=True)
            return JSONResponse(
                status_code=200,
                content=answer,
                headers={"X-Success-Code": "2032"}
            )

    async def applying_new_password(self):
        @self.router.post("/password/apply")
        async def applying_new_password(form_data: ResetPasswordSchema = Depends(ResetPasswordSchema.as_form),
                                        db: AsyncSession = TransactionSessionDep) -> JSONResponse:
            """
            ## Endpoint сброса пароля.

            ### Описание
            - Ручной способ сброса пароля. На него с фронта приходят данные для обновления пароля после перехода по ссылке, которую пользователе получил по email.
            - Возвращает сообщение о статусе операции.
            - Endpoint доступен для всех.

            ### Требования
            - Этот эндпоинт требует передачи данных в теле запроса в виде **form_data (application/x-www-form-urlencoded**).
            - Пользователь не должен быть авторизован.
            """

            verify_token = CheckTokenModel(token=form_data.token)
            token_data = await db.execute(
                select(ResetPasswordToken).where(ResetPasswordToken.token == verify_token.token))
            token_data = token_data.scalar_one_or_none()
            if not token_data:
                raise TokenNotFoundException
            if datetime.now(timezone.utc) > token_data.expires_at or token_data.ban:
                raise TokenExpiredException
            email_schema = CheckEmailModel(email=token_data.email)  # type: ignore
            check_user = await UserDAO.find_one_or_none(db=db, filters=email_schema)
            if not check_user:
                raise UserNotFoundException
            check_user.password = form_data.password
            await db.flush()
            return JSONResponse(
                status_code=200,
                content={
                    'message': 'The password is successfully updated'
                },
                headers={"X-Success-Code": "2033"}
            )

    async def get_file_from_s3_without_id(self):
        @self.router.get("/{object_type}/{date}/{identifier}/{filename}")
        async def route_get_content_for_widget_app(
            object_type: str = Path(..., description="Тип объекта"),
            date: str = Path(..., description="Дата в формате YYYY-MM-DD"),
            identifier: int = Path(..., description="UUID изображения"),
            filename: str = Path(
                ..., description="Имя файла с расширением (например, image.jpg)"
            ),
        ) -> StreamingResponse:
            """
            Возвращает изображение из каталога, если виджет опубликован.

            - **Проверяет права доступа** через JWT-токен (scope: DEVELOPER).
            - **Проверяет существование файла** на диске.
            - **Определяет MIME-тип** автоматически.
            - **Возвращает 404**, если изображение не найдено или доступ запрещён.
            """
            if not object_type in ["avatar"]:
                raise HTTPException(status_code=404, detail="Недопустимый тип объекта")
            return await get_photo_file(
                object_type=object_type, date=date, identifier=identifier, filename=filename
            )
