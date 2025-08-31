# app/run.py
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager
import os
import sys
import asyncio
from multiprocessing import Process

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.v1.endpoints.site import web_router
from app.api.v1.endpoints.stream import StreemAPI
from app.bot.webhooks.handlers import bot_router
from app.core.config import get_project_path_settings
from app.utils.logger import logger  # loguru
from app.core.middlewares import LogRouteMiddleware, DynamicCORSMiddleware
from app.db.dao.user import UserDAO
from app.api.v1.base_api import ProtectedSwagger
from app.api.v1.endpoints.stream_mjpeg import stream_video_router
from app.api.v1.endpoints.user import (
    AuthAPI,
    ProfileAPI,
    UserAPI,
    AdminAPI,
    BackgroundAPI,
    SecurityAPI,
)
from app.docs.load_docs import terms_of_service, contact, main_description
from app.utils.reg_exceptions import register_exception_handlers
from scripts.version import get_app_version

# ──────────────────────────────────────────────────────────────────────
# Мониторинг LPR: запускается как отдельный процесс из lifespan FastAPI
# ──────────────────────────────────────────────────────────────────────
# Управление через ENV:
#   LPR_ENABLED=1|0
#   LPR_CAMERAS_YAML="config/cameras.yaml"
#   LPR_CAMERA_KEY="falcone_receiver_cam2"
#   LPR_DET_MODEL="models/plate_yolov5s.onnx"

LPR_ENABLED = os.getenv("LPR_ENABLED", "1") == "1"
LPR_CAMERAS_YAML = os.getenv("LPR_CAMERAS_YAML", "config/cameras.yaml")
LPR_CAMERA_KEY = os.getenv("LPR_CAMERA_KEY", "falcone_receiver_cam2")
LPR_DET_MODEL = os.getenv("LPR_DET_MODEL", "models/plate_yolov5s.onnx")

# Логгеры с контекстом
log_api = logger.bind(context="api")
log_mon = logger.bind(context="monitor")

# Функция-энтрипоинт для дочернего процесса мониторинга
def _monitor_entrypoint(cameras_yaml: str, camera_key: str, det_model: str):
    try:
        # Инициализация логгера в дочернем процессе
        from app.utils.logger import logger as _lg
        _log = _lg.bind(context="monitor")

        # Импорты внутри процесса, чтобы основной процесс стартовал даже если мониторинг не настроен
        from app.monitoring.run_monitor import LPRPipeline, CameraConfig
        from app.monitoring.roi.masks import MaskStore
        from app.monitoring.config_runtime import RuntimeOptions
        from app.monitoring.config_resolver import resolve_rtsp

        with open(cameras_yaml, "r", encoding="utf-8") as f:
            cams = yaml.safe_load(f)

        cam_cfg = cams["cameras"][camera_key]
        rtsp_url = resolve_rtsp(cam_cfg["rtsp"])

        masks = MaskStore(cameras_yaml)
        rt = RuntimeOptions.from_env()

        cam = CameraConfig(
            name=camera_key,
            rtsp_url=rtsp_url,
            mask_name=camera_key,
            show_window=bool(cam_cfg.get("debug_window", False)),
        )

        _log.info(
            "Старт LPR-пайплайна | camera='{}' model='{}' yaml='{}'",
            camera_key,
            det_model,
            cameras_yaml,
        )

        pipe = LPRPipeline(cam=cam, masks=masks, rt=rt, detector_model=det_model)
        pipe.run_forever()

    except Exception as e:
        # Логируем и выходим — API живёт отдельно
        try:
            _log.exception("Критическая ошибка процесса мониторинга: {}", e)
        except Exception:
            print(f"[MONITOR] Fatal error: {e}", file=sys.stderr)


# Подключаем роутеры
async def configure_routers():
    log_api.info("Создаем экземпляры API...")

    auth_api = AuthAPI()
    security_api = SecurityAPI()
    profile_api = ProfileAPI()
    user_api = UserAPI()
    admin_api = AdminAPI()
    background_api = BackgroundAPI()
    sse_api = StreemAPI()

    log_api.info("Инициализируем маршруты...")
    await auth_api.initialize_routes()
    await security_api.initialize_routes()
    await profile_api.initialize_routes()
    await user_api.initialize_routes()
    await admin_api.initialize_routes()
    await background_api.initialize_routes()
    await sse_api.initialize_routes()

    log_api.info("Добавляем маршруты в приложение...")
    app_account.include_router(auth_api.router)
    app_account.include_router(security_api.router)
    app_account.include_router(profile_api.router)
    app_account.include_router(user_api.router)
    app_account.include_router(admin_api.router)
    app_account.include_router(background_api.router)
    app_account.include_router(sse_api.router)

    app_monitoring.include_router(stream_video_router, tags=["Video stream"])

    app_bot.include_router(bot_router, tags=["Bot"])

    app.include_router(web_router, tags=["Web"])



# Асинхронный контекстный менеджер для жизненного цикла приложения
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator:
    monitor_proc: Process | None = None
    try:
        log_api.info("Регистрируем исключения...")
        register_exception_handlers(application)

        log_api.info("Инициализируем маршруты и API...")
        await configure_routers()

        log_api.info("Проверка ролей в БД при старте приложения...")
        await UserDAO.check_roles_in_db()

        # Запуск мониторинга (отдельный процесс)
        if LPR_ENABLED:
            try:
                monitor_proc = Process(
                    target=_monitor_entrypoint,
                    args=(LPR_CAMERAS_YAML, LPR_CAMERA_KEY, LPR_DET_MODEL),
                    name="lpr-monitor",
                    daemon=True,
                )
                monitor_proc.start()
                log_mon.info(
                    "Процесс мониторинга запущен | pid={} camera_key='{}'",
                    monitor_proc.pid,
                    LPR_CAMERA_KEY,
                )
            except Exception as e:
                log_mon.exception("Ошибка запуска мониторинга: {}", e)
        else:
            log_mon.info("Мониторинг отключён (LPR_ENABLED=0)")

        log_api.info("Запускаем API...")
        yield  # Приложение запущено

    finally:
        log_api.info("Завершаем работу приложения...")
        if monitor_proc and monitor_proc.is_alive():
            log_mon.info("Останавливаю процесс мониторинга…")
            try:
                monitor_proc.terminate()
                monitor_proc.join(timeout=5)
                if monitor_proc.is_alive():
                    log_mon.warning("Процесс мониторинга не завершился вовремя")
            except Exception as e:
                log_mon.exception("Ошибка при остановке мониторинга: {}", e)


app_account = FastAPI(
    lifespan=lifespan,
    title="🧩 SVM-A Account API",
    root_path="/api/account",
)

app_monitoring = FastAPI(
    lifespan=lifespan,
    title="🧩 SVM-A Monitoring API",
    root_path="/api/monitoring",
)

app_bot = FastAPI(
    lifespan=lifespan,
    title="🔐 Телеграм-бот SVM-A",
    root_path="/api/tg-bot",
)


app = FastAPI(
    lifespan=lifespan,
    title="SVM-A Web Application",
    root_path='/account',
    description=main_description,
    terms_of_service=terms_of_service,
    version=get_app_version(),
    contact=contact,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    license_info={"name": "Proprietary"},
    swagger_ui_parameters={"persistAuthorization": True, "faviconUrl": "app/docs/favicon/favicon-96x96.png"},
    swagger_ui_init_oauth={
        "clientId": "swagger-client",
        "appName": "Swagger SVM-A Account",
        "scopes": "USER DEVELOPER",
        "usePkceWithAuthorizationCodeGrant": True,
    }
)

# ====== Защита Swagger UI (оставлено как в исходнике, закомменчено) ======
# protected_swagger = ProtectedSwagger()
# @app.middleware("http")
# async def main_app_swagger_auth(request: Request, call_next):
#     return await protected_swagger.process_request(request, call_next)

# ====== Остальная конфигурация ======
# app.add_middleware(FingerPrintMiddleware)       # 1. Проверка ботов
app.add_middleware(LogRouteMiddleware)         # 2. Логирование
app.add_middleware(DynamicCORSMiddleware)      # 3. Динамический CORS
# app.add_middleware(AutoRefreshMiddleware)     # 4. Авто-проверка токена авто-обновлением.


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

log_api.info("Cоздаём приложение...")

for route, path in get_project_path_settings().static_mounts.items():
    app.mount(f"/{route}", StaticFiles(directory=path), name=route)

app.mount("/api/tg-bot", app_bot)

app.mount("/api/monitoring", app_monitoring)

app.mount("/api/account", app_account)


if __name__ == "__main__":
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
        # Здесь будет ясно, что ошибка — именно у API-части (процесс мониторинга логируется отдельно)
        print(f"❌ Неизвестная ошибка API: {e}")
        sys.exit(1)
