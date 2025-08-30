import hashlib
import hmac
import json
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import TypeVar, Optional, Tuple
from uuid import uuid4

import httpx
from jose import jwt, JWTError, ExpiredSignatureError
from app.utils.logger import logger

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from fastapi import APIRouter, Request, HTTPException, status, Security, Cookie, Query, Header, WebSocket
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from fastapi.security.utils import get_authorization_scheme_param
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import algorithm_env, access_token_env, base_api_user_url, get_urls_to_services, \
    get_mail_sender_config, get_project_path_settings, stream_token_env, pepper_token_env
from app.db.dao.user import UserDAO
from app.db.dao.base_dao import BaseDAO
from app.db.models.tables import User, EmailVerificationToken, ResetPasswordToken, ChangeEmailVerificationToken
from app.db.models.base_sql import BaseSQL
from app.db.sessions import TransactionSessionDep
from app.utils.http_exceptions import (InvalidJwtException, TokenExpiredException, UserIdNotFoundException,
                                       ForbiddenAccessException, UserNotFoundException, UserBannedException)


DAO = TypeVar("DAO", bound=BaseDAO)
PYDANTIC = TypeVar("PYDANTIC", bound=BaseModel)
SQL = TypeVar("SQL", bound=BaseSQL)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=get_project_path_settings().BASE_TEMPLATES_PATH)

oauth2_scopes = {
    "USER": "Стандартный пользовательский доступ.",
    "DEVELOPER": "Доступ для разработчиков",
    "ADMIN": "Администраторский доступ с ограничениями.",
    "SYSADMIN": "Администраторский доступ без ограничений.",
    "MANAGER": "Менеджерский доступ",
    "SUPPORT": "Доступ для тех.поддержки",
    "MODERATOR": "Доступ для модераторов"
}

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/login",
    scopes=oauth2_scopes,
    scheme_name="JWT Bearer Token",  # Название схемы безопасности, которое будет видно в OpenAPI
    description="""
    OAuth2 схема аутентификации с использованием JWT токена. Эндпоинт авторизации поддерживает два типа грантов: 
    1. **`password`** - аутентификация с использованием имени пользователя (email или телефон) и пароля.
    2. **`refresh_token`** - обновление токена доступа с помощью предоставленного refresh_token.

    Для получения токенов доступа (access_token) и обновления токенов (refresh_token) используется следующая логика:
    - При `grant_type=password` генерируется новый `access_token` (сроком на 30 минут) и `refresh_token`.
    - При `grant_type=refresh_token` обновляется `access_token` и возвращается новый `refresh_token` в cookies.

    Необходимость в предоставлении токена актуальна для всех защищенных эндпоинтов.
    """
)


class ProtectedSwagger:
    def __init__(self):
        # Все базовые пути, где нужно защитить документацию
        self.protected_paths = [
            "",
            "/"
        ]

    async def is_swagger_path(self, path: str) -> bool:
        """Проверяет, относится ли путь к документации"""
        for base_path in self.protected_paths:
            if path == f"{base_path}/docs" or path == f"{base_path}/redoc":
                return True
            if path == f"{base_path}/openapi.json":
                return True
        return False

    @staticmethod
    async def swagger_login_page(request: Request):
        return templates.TemplateResponse(
            "swagger_login.html",
            {"request": request, "error": request.method == "POST"}
        )

    @staticmethod
    async def check_auth(request: Request):
        # Проверяем куки Swagger
        authorized = request.cookies.get("swagger_authorized")
        if authorized == "true":
            return True

        # Проверяем JWT токен из запроса
        try:
            token = await oauth2_scheme(request)
            payload = jwt.decode(token, access_token_env(), algorithms=[algorithm_env()])
            user_scopes = payload.get("scopes", [])
            # Обновленный список разрешенных ролей
            required_scopes = {"ADMIN", "SYSADMIN", "DEVELOPER"}
            if any(scope in user_scopes for scope in required_scopes):
                return True
        except (ExpiredSignatureError, JWTError, HTTPException):
            return False

    async def process_request(self, request: Request, call_next):
        path = request.url.path

        # Пропускаем все пути, не связанные с документацией
        if not await self.is_swagger_path(path):
            return await call_next(request)

        # Для openapi.json пропускаем без проверки
        if path.endswith("openapi.json"):
            return await call_next(request)

        # Проверяем авторизацию
        if request.method == "POST" and path.endswith(("/docs", "/redoc")):
            form_data = await request.form()
            username = form_data.get("username")
            password = form_data.get("password")


            if await self.authenticate_via_oauth(username, password):
                # Разрешаем доступ после успешной OAuth2 аутентификации
                response = RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)
                response.set_cookie(
                    key="swagger_authorized",
                    value="true",
                    httponly=True,
                    secure=True,
                    samesite='lax',
                    max_age=3600
                )
                return response
            else:
                if "application/json" in request.headers.get("accept", ""):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "Access denied. Insufficient privileges or invalid credentials"}
                    )
                return await self.swagger_login_page(request)

        # Проверяем куки или JWT токен для GET-запросов
        if not await self.check_auth(request):
            return await self.swagger_login_page(request)

        return await call_next(request)

    @staticmethod
    async def authenticate_via_oauth(username: str, password: str) -> bool:
        """Аутентификация через OAuth2 endpoint с проверкой ролей"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_api_user_url()}login",
                    data={
                        "username": username,
                        "password": password,
                        "grant_type": "password",
                        "scope": "USER DEVELOPER"  # Запрашиваемые scope
                    }
                )

                if response.status_code == 200:
                    token_data = response.json()
                    # Декодируем токен для проверки scope
                    payload = jwt.decode(
                        token_data["access_token"],
                        access_token_env(),
                        algorithms=[algorithm_env()]
                    )
                    user_scopes = payload.get("scopes", [])
                    # Проверяем, есть ли у пользователя нужные права
                    required_scopes = {"DEVELOPER"}
                    return any(scope in user_scopes for scope in required_scopes)

            return False
        except Exception as e:
            logger.error(f"OAuth2 authentication error: {str(e)}")
            return False


class AnwillUserAPI(ProtectedSwagger):
    TTL_SECONDS = 1800
    dao_model = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Проверяем, что это прямой наследник BaseDAO, а не внутренний класс SQLAlchemy
        if cls.__bases__[0] == AnwillUserAPI:
            logger.info(f"{cls.__name__} инициализирован")

    def __init__(self):
        super().__init__()
        self.name_model = self.__class__.__name__[:-3]
        self.user_id = None
        self.router = APIRouter()


    async def initialize_routes(self):
        await self.setup_routes()

    async def setup_routes(self):
        """
        Заглушка для переопределения маршрутов в дочерних классах.
        """
        pass


    async def response_tokens_in_cookie(self, access_token: str, refresh_token: str = None,
                                        user_id: int = None) -> JSONResponse:
        response = JSONResponse(
            status_code=200,
            content={
                "access_token": access_token,
                "token_type": "bearer",
            },
        )
        if refresh_token:
            response.set_cookie(
                key="refresh_token",
                value=refresh_token,
                httponly=True,
                secure=True,
                samesite="none",
            )

        csrf_token = secrets.token_hex(32)
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            secure=True,
            samesite="none",
        )
        if user_id:
            try:
                user_id = user_id
                stream_jwt, ttl = self.mint_stream_token(user_id)
                response.set_cookie(
                    key="stream_token",
                    value=stream_jwt,
                    httponly=True,
                    secure=True,
                    samesite="none",
                    max_age=ttl,
                    path="/sse",
                )
            except Exception:
                pass

        return response

    @staticmethod
    async def get_current_user(security_scopes: SecurityScopes, token: str = Security(oauth2_scheme),
                               db: AsyncSession = TransactionSessionDep, refresh_token: str = Cookie(None)) -> User:
        try:
            payload = jwt.decode(token, access_token_env(), algorithms=[algorithm_env()])
            user_id: str = payload.get('sub')
            token_scopes = payload.get('scopes', [])
            expire: str = payload.get('exp')
        except ExpiredSignatureError:
            raise InvalidJwtException
        except JWTError:
            raise InvalidJwtException

        if not user_id:
            raise UserIdNotFoundException

        rig = False
        if not security_scopes.scopes:
            rig = True
        for scope in security_scopes.scopes:
            if scope in token_scopes:
                rig = True
        if not rig:
            raise ForbiddenAccessException

        expire_time = datetime.fromtimestamp(int(expire), tz=timezone.utc)
        if not expire or expire_time < datetime.now(timezone.utc):
            raise TokenExpiredException

        user = await UserDAO.find_one_or_none_by_id_with_tokens(data_id=int(user_id), db=db)
        if not user:
            raise UserNotFoundException
        user.last_login_attempt = datetime.now(tz=timezone.utc)

        if user.is_banned:
            raise UserBannedException
        return user

    @staticmethod
    async def validate_csrf_token(request: Request):
        user_agent = request.headers.get("User-Agent", "")
        if "Postman" in user_agent or "Insomnia" in user_agent or "Swagger" in user_agent:
            return  # Пропустить проверку CSRF
        # Извлекаем CSRF-токен из заголовка и cookie
        csrf_token_header = request.headers.get("X-CSRF-Token")
        csrf_token_cookie = request.cookies.get("csrf_token")

        # Проверяем, совпадают ли токены
        if not csrf_token_header or not csrf_token_cookie or csrf_token_header != csrf_token_cookie:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing or invalid"
            )

    @staticmethod
    async def send_email_to_user(email: EmailStr, verification_link: str, mail_str: str):
        conf = ConnectionConfig(
            MAIL_USERNAME=str(get_mail_sender_config().MAIL_USERNAME),
            MAIL_PASSWORD=get_mail_sender_config().MAIL_PASSWORD,
            MAIL_FROM=get_mail_sender_config().MAIL_USERNAME,
            MAIL_FROM_NAME='Anwill',
            MAIL_PORT=get_mail_sender_config().MAIL_PORT,
            MAIL_SERVER=get_mail_sender_config().MAIL_SERVER,
            MAIL_STARTTLS=False,
            MAIL_SSL_TLS=True,
            USE_CREDENTIALS=True
        )

        # Формируем ссылку для верификации.
        # Создаем сообщение.
        body = f"Нажмите по следующей ссылке, чтобы {mail_str}: {verification_link}"

        message = MessageSchema(
            subject="Anwill. Подтверждение email адреса.",
            recipients=[email],  # Список получателей, столько, сколько вы можете пройти.
            body=body,
            subtype=MessageType.html
        )

        fm = FastMail(conf)
        await fm.send_message(message)

    @classmethod
    async def send_verify_email_to_user(cls, email: EmailStr, db: AsyncSession) -> dict:
        token = EmailVerificationToken(email=str(email))
        try:
            db.add(token)
            await db.flush()
        except SQLAlchemyError as e:
            logger.error(f'Ошибка генерации токена для верификации email: {e}')
            raise HTTPException(status_code=500, detail="Error generate verify token to email")

        verification_link = f"{get_urls_to_services().DOMAIN_URL}profile?verifyMail={token.token}"

        try:
            await cls.send_email_to_user(
                email=email,
                verification_link=verification_link,
                mail_str='подтвердить электронную почту'
            )
            return {"message": "Verification email sent", "code": "2003"}
        except Exception as e:
            logger.error(f'Ошибка при отправке сообщения на email: {str(e)}')
            raise HTTPException(status_code=500, detail="Error sending email")

    @classmethod
    async def send_change_verify_email_to_user(cls, new_email: EmailStr, db: AsyncSession):
        token = ChangeEmailVerificationToken(new_email=new_email)  # type: ignore
        try:
            db.add(token)
            await db.flush()
        except SQLAlchemyError as e:
            logger.error(f'Ошибка генерации токена для верификации email: {e}')
            raise HTTPException(status_code=500, detail=f"Error generate verify token to email")

        verification_link = f"{get_urls_to_services().DOMAIN_URL}profile/change?verifyMail={token.token}"
        try:
            await cls.send_email_to_user(email=new_email,
                                         verification_link=verification_link,
                                         mail_str='подтвердить электронную почту для ее смены')

            return JSONResponse(status_code=200, content={"message": "Verification email sent for change email"})
        except Exception as e:
            logger.error(f'Ошибка при отправке сообщения на email: {str(e)}')
            raise HTTPException(status_code=500, detail=f"Error sending email")

    @classmethod
    async def send_reset_password_to_user(cls, email: EmailStr, db: AsyncSession):
        token = ResetPasswordToken(email=email)  # type: ignore
        try:
            db.add(token)
            await db.flush()
        except SQLAlchemyError as e:
            logger.error(f'Ошибка генерации токена для сброса пароля: {e}')
            raise HTTPException(status_code=500, detail=f"Token generation error for password reset")
        # Формируем ссылку для верификации
        verification_link = f"{get_urls_to_services().DOMAIN_URL}password/reset/{token.token}"

        try:
            await cls.send_email_to_user(email=email,
                                         verification_link=verification_link,
                                         mail_str='сбросить пароль')
            return JSONResponse(status_code=200, content={"message": "Reset password sent"})
        except Exception as e:
            logger.error(f'Ошибка при отправке сообщения на email: {str(e)}')
            raise HTTPException(status_code=500, detail=f"Error sending reset password")

    @classmethod
    async def get_current_sse_user(
            cls,
            stream_cookie: Optional[str] = Cookie(default=None, alias="stream_token"),
            authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> int:
        token = None

        # 1) Cookie (нативный EventSource)
        if stream_cookie:
            token = stream_cookie

        # 2) Fallback: Authorization: Bearer <stream_jwt>
        if not token and authorization:
            scheme, param = get_authorization_scheme_param(authorization)
            if scheme.lower() == "bearer" and param:
                token = param

        if not token:
            raise HTTPException(status_code=401, detail="Missing stream token")

        try:
            payload = cls.decode_stream_token(token)
            if payload.get("typ") != "sse":
                raise HTTPException(status_code=403, detail="Invalid token type")
            # тут же можно проверять scope/blacklist/jti по базе
            user_id = int(payload["sub"])
            return user_id
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired stream token")

    @staticmethod
    def sse_event(data: dict, event: str = "progress") -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def mint_stream_token(user_id: int, ttl: int = TTL_SECONDS) -> Tuple[str, int]:
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=ttl)
        payload = {
            "sub": str(user_id),
            "typ": "sse",
            "scope": ["USER"],
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": str(uuid4()),
        }
        token = jwt.encode(payload, stream_token_env(), algorithm=algorithm_env())
        return token, ttl

    @staticmethod
    def decode_stream_token(token: str) -> dict:
        return jwt.decode(token, stream_token_env(), algorithms=[algorithm_env()])

    async def _auth_ws_user(self, websocket: WebSocket) -> Optional[int]:
        """
        Возвращает user_id, если токен валиден, иначе None.
        Использует тот же ключ/алгоритм, что и в cookie stream_token.
        """
        token = self._get_ws_token(websocket)
        if not token:
            return None
        try:
            payload = jwt.decode(token, stream_token_env(), algorithms=[algorithm_env()])
            # ожидаем, что в токене есть sub=user_id и exp
            exp = int(payload.get("exp", 0))
            now = int(datetime.now(timezone.utc).timestamp())
            if exp <= now:
                return None
            user_id = payload.get("sub")
            if isinstance(user_id, str) and user_id.isdigit():
                user_id = int(user_id)
            return user_id if isinstance(user_id, int) else None
        except JWTError:
            return None

    @staticmethod
    def _get_ws_token(websocket: WebSocket) -> Optional[str]:
        # 1) Cookie stream_token
        token = websocket.cookies.get("stream_token")
        if token:
            return token
        # 2) Authorization: Bearer
        auth = websocket.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return token


