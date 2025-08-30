import re
import time
from typing import Optional
from urllib.parse import urlparse

from app.utils.logger import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

import httpx
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import access_token_env, algorithm_env, get_cors_settings

# Инициализация rate limiter
limiter = Limiter(key_func=get_remote_address)
REFRESH_RATE_LIMIT = "5/minute"  # 5 запросов в минуту

class FingerPrintMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        logger.info('Проверка на уникальные заголовки браузера. Защита от ботов')
        user_agent = request.headers.get("User-Agent", "")

        # Разрешаем популярные тестовые инструменты
        testing_tools = {
            "PostmanRuntime",
            "insomnia",
            "newman",
            "python-requests"
        }

        if any(tool in user_agent for tool in testing_tools):
            logger.info('Тестовый запрос.')
            logger.info('Проверка пройдена')
            return await call_next(request)

        logger.info('Реальный запрос.')

        # Остальная проверка для реальных запросов
        required_headers = {
            "User-Agent": r"^(Mozilla|Chrome|Safari|Firefox)",
            "Accept-Language": r".+",
            "Sec-Ch-Ua": r".+"
        }

        for header, pattern in required_headers.items():
            value = request.headers.get(header)
            if not value or not re.search(pattern, value, re.IGNORECASE):
                logger.warning(f"Blocked bot: Missing/invalid {header}")
                raise HTTPException(status_code=403, detail=f"Forbidden: Invalid {header}")
        logger.info('Проверка пройдена')
        return await call_next(request)

class LogRouteMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/redoc", "/docs", "/openapi.json", "/health"]:
            return await call_next(request)
        logger.info("________________________________ START LogRouteMiddleware _________________________________")
        logger.info(f"{request.method} {request.url.path}")
        start_time = time.time()  # Засекаем время выполнения
        response = await call_next(request)  # Вызываем эндпоинт
        process_time = time.time() - start_time  # Считаем время выполнения
        user_id = None
        access_token = request.headers.get("Authorization")
        if access_token and access_token.startswith("Bearer "):
            token = access_token.split(" ")[1]
            try:
                # Проверяем, не истек ли токен
                payload = jwt.decode(token, access_token_env(), algorithms=[algorithm_env()])
                user_id = payload.get("sub")  # Обычно user_id хранится в "sub"
            except JWTError:
                user_id = None
        if not request.url.path.endswith('/openapi.json') and not request.url.path.endswith('/docs'):
            logger.bind(log_type="route_log").debug(f"Запрос обработан: user_id={user_id}, метод={request.method}, адрес={request.url.path}, статус={response.status_code}, время={process_time:.2f}s")
        # Здесь выполняем код ПОСЛЕ вызова эндпоинта
        logger.info("_________________________________ END LogRouteMiddleware __________________________________")

        return response

class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/redoc", "/docs", "/openapi.json", "/health"]:
            return await call_next(request)
        logger.info("________________________________ START DynamicCORSMiddleware _________________________________")
        logger.info(f"Incoming request: {request.method} {request.url.path}")
        logger.info(f"Request headers: {dict(request.headers)}")

        # Обрабатываем OPTIONS запросы
        if request.method == "OPTIONS":
            response = await self.processing_options_request(request=request)
            return response

        # Обрабатываем основной запрос
        response = await call_next(request)

        origin = request.headers.get("origin")
        logger.info(f"Processing request with origin: {origin}")

        if not origin:
            logger.warning("No origin header in request")
            logger.info("_________________________________ END DynamicCORSMiddleware __________________________________")
            return response

        response = await self.processing_requests_for_other_methods(response=response, origin=origin)
        logger.info(f"Final response headers: {dict(response.headers)}")
        logger.info("_________________________________ END DynamicCORSMiddleware __________________________________")
        return response

    @staticmethod
    async def processing_options_request(request: Request):
        logger.info("Processing OPTIONS request")
        requested_headers = request.headers.get("access-control-request-headers", "")
        logger.info(f"Requested headers: {requested_headers}")

        response = Response(
            content="OK",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS, PUT, DELETE, PATCH",
                "Access-Control-Allow-Headers": requested_headers if requested_headers else "content-type, authorization",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "86400",
                "Vary": "Origin"
            }
        )
        logger.info(f"OPTIONS response headers: {dict(response.headers)}")
        return response

    @classmethod
    async def processing_requests_for_other_methods(cls, response: Response, origin: str):
        logger.info("Checking against STATIC_ORIGINS and development tools")
        try:
            # Разрешаем запросы из Swagger UI, Postman и Insomnia
            if (origin in get_cors_settings().CORS_ALLOWED_ORIGINS or
                    origin == "http://localhost" or
                    origin == "http://127.0.0.1" or
                    origin.endswith("//localhost") or
                    origin.endswith("//127.0.0.1") or
                    origin is None):  # Для запросов из Postman/Insomnia (без Origin header)

                allowed_origin = origin if origin else "*"
                logger.info(f"Origin {allowed_origin} allowed (development tool)")
                response.headers.update({
                    "Access-Control-Allow-Origin": allowed_origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Vary": "Origin"
                })
            elif cls.is_allowed_subdomain(origin, set()):
                logger.info(f"Origin {origin} is allowed subdomain")
                response.headers.update({
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Vary": "Origin"
                })
            else:
                logger.warning(f"Origin {origin} not allowed by CORS policy")
                logger.remove()
                raise HTTPException(
                    status_code=403,
                    detail="The domain is not registered",
                    headers={
                        "Access-Control-Allow-Origin": "",
                        "Vary": "Origin"
                    }
                )
        except Exception as e:
            logger.error(f"Error checking static origins: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=404,
                detail="Internal server error during CORS validation",
                headers={
                    "Access-Control-Allow-Origin": "",
                    "Vary": "Origin"
                }
            )
        return response

    @staticmethod
    def is_allowed_subdomain(origin: str, db_domains: set) -> bool:
        """
        Проверяет, является ли origin:
        - точным совпадением с доменом из static_origins или db_domains
        - поддоменом разрешенных доменов (кроме localhost/IP)
        """
        if not origin:
            return False

        try:
            parsed = urlparse(origin)
            netloc = parsed.netloc.lower()

            # Нормализуем домены для сравнения (удаляем порт)
            def normalize_domain(domain_url: str) -> str:
                parsed_domain = urlparse(domain_url.lower())
                return parsed_domain.netloc.split(":")[0]  # Удаляем порт

            # Проверяем точное совпадение (с учетом нормализации)
            normalized_origin = normalize_domain(origin)
            static_and_db_domains = {
                normalize_domain(url) for url in get_cors_settings().CORS_ALLOWED_ORIGINS | db_domains
            }

            if normalized_origin in static_and_db_domains:
                return True

            # Исключаем localhost и IP-адреса (они не могут иметь поддоменов)
            if (
                netloc.startswith("localhost")  # localhost или localhost:port
                or re.match(r"^(\d+\.){3}\d+(:\d+)?$", netloc)  # IPv4
                or re.match(r"^\[([0-9a-fA-F:]+)](:\d+)?$", netloc)  # IPv6
            ):
                return False

            # Разбиваем домен на части (sub.example.com -> ['sub', 'example', 'com'])
            domain_parts = netloc.split(".")
            if len(domain_parts) < 2:
                return False  # Невалидный домен

            # Проверяем поддомены для каждого разрешенного домена
            for allowed_domain in static_and_db_domains:
                allowed_parts = allowed_domain.split(".")
                if len(allowed_parts) < 2:
                    continue  # Пропускаем домены верхнего уровня (например, 'com')

                # Проверяем, что origin является поддоменом allowed_domain
                # Например: origin=sub.example.com, allowed_domain=example.com
                if (
                    len(domain_parts) > len(allowed_parts)
                    and domain_parts[-len(allowed_parts):] == allowed_parts
                ):
                    return True

            return False

        except Exception as e:
            logger.error(f"Error parsing origin '{origin}': {e}", exc_info=True)
            return False

class AutoRefreshMiddleware(BaseHTTPMiddleware):
    """
    Middleware для автоматического обновления access_token через refresh_token.

    ### Логика работы:
    1. Проверяет валидность access_token из заголовка Authorization
    2. При истечении/не-валидности access_token:
       - Извлекает refresh_token из cookies
       - Отправляет запрос на `/refresh` эндпоинт
       - Обновляет access_token в заголовках запроса
    3. Добавляет user_id в request.state для последующих обработчиков

    ### Особенности:
    - Не взаимодействует с БД напрямую
    - Полагается на внешний сервис аутентификации
    - Автоматически обновляет заголовки при успешном обновлении
    - Поддерживает rate-limiting для /refresh
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Основной обработчик middleware.

        Args:
            request: Входящий запрос
            call_next: Следующий обработчик в цепочке

        Returns:
            Response: Ответ сервера

        Raises:
            HTTPException 401: При невалидном refresh_token
            HTTPException 429: При превышении лимита запросов
            HTTPException 503: При недоступности сервиса аутентификации
        """
        logger.info("AutoRefreshMiddleware: начата обработка запроса")

        try:
            user_id = await self._process_auth(request)
            if user_id:
                request.state.user_id = user_id

            return await call_next(request)

        except HTTPException as http_exc:
            logger.warning(f"Auth error: {http_exc.status_code} {http_exc.detail}")
            raise
        except Exception as exc:
            logger.error("Unexpected auth error", exc_info=True)
            raise HTTPException(500, "Internal auth error") from exc

    async def _process_auth(self, request: Request) -> Optional[int]:
        """
        Проверка и обновление токена при необходимости.

        Args:
            request: Входящий запрос

        Returns:
            Optional[int]: user_id если аутентификация успешна

        Raises:
            HTTPException: При критических ошибках аутентификации
        """
        access_token = request.headers.get("Authorization")
        if not access_token or not access_token.startswith("Bearer "):
            return None

        token = access_token[7:]  # Убираем 'Bearer '
        try:
            payload = jwt.decode(token, access_token_env(), algorithms=[algorithm_env()])
            if user_id := payload.get("sub"):
                return int(user_id)

        except ExpiredSignatureError:
            logger.info("Access token expired, attempting refresh")
            return await self._refresh_access_token(request)
        except JWTError as e:
            logger.warning(f"Invalid access token: {str(e)}")
            return None

    @limiter.limit(REFRESH_RATE_LIMIT)
    async def _refresh_access_token(self, request: Request) -> Optional[int]:
        """
        Обновление access_token через refresh_token.

        Args:
            request: Входящий запрос с refresh_token в cookies

        Returns:
            Optional[int]: user_id из нового токена

        Raises:
            HTTPException 401: При невалидном/просроченном refresh_token
            HTTPException 503: При ошибке соединения с сервисом аутентификации
        """
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            logger.warning("No refresh_token in cookies")
            return None

        try:
            # Быстрая проверка refresh_token перед использованием
            payload = jwt.decode(refresh_token, access_token_env(), algorithms=[algorithm_env()])
            int(payload.get("sub"))

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(
                    f"/refresh",
                    json={"token": refresh_token},
                    headers={"Content-Type": "application/json"}
                )

                if response.status_code == 200:
                    data = response.json()
                    if new_access := data.get("access_token"):
                        # Обновляем заголовок Authorization
                        request.headers.__dict__["_list"].append(
                            ("Authorization", f"Bearer {new_access}")
                        )
                        # Возвращаем новый user_id
                        new_payload = jwt.decode(new_access, access_token_env(), algorithms=[algorithm_env()])
                        return int(new_payload.get("sub"))

        except ExpiredSignatureError:
            logger.warning("Refresh token expired")
            raise HTTPException(401, "Refresh token expired")
        except JWTError as e:
            logger.warning(f"Invalid refresh token: {str(e)}")
            raise HTTPException(401, "Invalid refresh token")
        except httpx.RequestError as e:
            logger.error(f"Auth service unreachable: {str(e)}")
            raise HTTPException(503, "Authentication service unavailable") from e

        return None



