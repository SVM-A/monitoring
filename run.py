# app/run.py
from pathlib import Path
from typing import AsyncGenerator
import uvicorn

from app.api.v1.endpoints.stream import StreemAPI
from app.core.config import get_project_path_settings
from app.utils.logger import logger
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.middlewares import LogRouteMiddleware, DynamicCORSMiddleware
from app.db.dao.user import UserDAO
from app.api.v1.base_api import ProtectedSwagger
from app.api.v1.endpoints.user import AuthAPI, ProfileAPI, UserAPI, AdminAPI, BackgroundAPI, SecurityAPI
from app.docs.load_docs import terms_of_service, contact, main_description
from app.utils.reg_exceptions import register_exception_handlers
from scripts.version import get_app_version

logger.info('Генерируем Readme')
# gen_readme()

# Асинхронный контекстный менеджер для жизненного цикла приложения
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator:
    logger.info("Регистрируем исключения...")
    register_exception_handlers(application)
    await configure_routers()
    logger.info("Проверка ролей в БД при старте приложения...")
    await UserDAO.check_roles_in_db()
    logger.info("Запускаем API...")
    yield  # После этого приложение запустится
    logger.info("Завершаем работу...")

app = FastAPI(
    lifespan=lifespan,
    title="Anwill Back User",
    description=main_description,
    terms_of_service=terms_of_service,
    version=get_app_version(),
    contact=contact,
    openapi_url="/openapi.json",
    docs_url="/docs",
    license_info={"name": "Proprietary", "url": "https://api.anwill.fun"},
    swagger_ui_parameters={"persistAuthorization": True, "faviconUrl": "app/docs/favicon/favicon-96x96.png"},
    root_path_in_servers=False,
    swagger_ui_init_oauth={
        "clientId": "swagger-client",
        "appName": "Swagger UI Anwill Back User",
        "scopes": "USER DEVELOPER MODERATOR SUPPORT SYSADMIN ADMIN MANAGER",  # Используем явно заданные роли
        "usePkceWithAuthorizationCodeGrant": True,
    }
)
#
# # ====== Защита Swagger UI ======
# protected_swagger = ProtectedSwagger()
#
# # Основное приложение
# @app.middleware("http")
# async def main_app_swagger_auth(request: Request, call_next):
#     return await protected_swagger.process_request(request, call_next)


# ====== Остальная конфигурация ======
# app.add_middleware(FingerPrintMiddleware)       # 1. Проверка ботов
app.add_middleware(LogRouteMiddleware)         # 2. Логирование
app.add_middleware(DynamicCORSMiddleware)      # 3. Динамический CORS
# app.add_middleware(AutoRefreshMiddleware)      # 4. Авто-проверка токена авто-обновлением.


for route, path in get_project_path_settings().static_mounts.items():
    app.mount(f"/{route}", StaticFiles(directory=path), name=route)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

@app.get("/user/README.md", include_in_schema=False)
async def readme():
    full_path = Path(__file__).parent / "README.md"
    return FileResponse(full_path)


@app.get("/user/README/readme_logo.png", include_in_schema=False)
async def readme_logo():
    full_path = Path(__file__).parent / "app/docs/readme_logo.png"
    return FileResponse(full_path)


logger.info("Cоздаём приложение...")

# Подключаем роутеры
async def configure_routers():
    logger.info("Создаем экземпляры API...")

    auth_api = AuthAPI()
    security_api = SecurityAPI()
    profile_api = ProfileAPI()
    user_api = UserAPI()
    admin_api = AdminAPI()
    background_api = BackgroundAPI()
    sse_api = StreemAPI()


    logger.info("Инициализируем маршруты...")
    await auth_api.initialize_routes()
    await security_api.initialize_routes()
    await profile_api.initialize_routes()
    await user_api.initialize_routes()
    await admin_api.initialize_routes()
    await background_api.initialize_routes()
    await sse_api.initialize_routes()


    logger.info("Добавляем маршруты в приложение...")
    app.include_router(auth_api.router)
    app.include_router(security_api.router)
    app.include_router(profile_api.router)
    app.include_router(user_api.router)
    app.include_router(admin_api.router)
    app.include_router(background_api.router)
    app.include_router(sse_api.router)


if __name__ == "__main__":
    import asyncio
    import sys

    try:
        uvicorn.run(
            "run:app",
            host="0.0.0.0",
            port=55666,
            reload=True,
            proxy_headers=True,
            factory=False,
        )
    except asyncio.CancelledError:
        print("🛑 Сервер остановлен (CancelledError)")
        sys.exit(0)
    except KeyboardInterrupt:
        print("🛑 Сервер остановлен пользователем (CTRL+C)")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Неизвестная ошибка: {e}")
        sys.exit(1)
