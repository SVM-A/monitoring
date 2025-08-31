# app/api/v1/endpoints/site.py [AUTOGEN_PATH]

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.templates import templates

web_router = APIRouter()

@web_router.get("/health")
async def health():
    """
    **Проверка работоспособности сервиса**

    ```
    Endpoint: GET /health
    Response: {"status": "ok"}
    Status Codes:
      - 200: Сервис работает нормально
    ```

    Простейший эндпоинт для проверки доступности сервиса.
    Всегда возвращает HTTP 200 с JSON-объектом {"status": "ok"}.
    """
    return {"status": "ok"}


# ГЛАВНАЯ
@web_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Главная",
            "static_version": datetime.now().strftime("%Y%m%d%H%M"),
        },
    )

# Личный кабинет
@web_router.get("/login", response_class=HTMLResponse)
async def profile(request: Request):
    return templates.TemplateResponse(
        "landing/login.html",
        {
            "request": request,
            "title": "Авторизация",
            "static_version": datetime.now().strftime("%Y%m%d%H%M"),
        },
    )


@web_router.get("/register", response_class=HTMLResponse)
async def profile(request: Request):
    return templates.TemplateResponse(
        "landing/register.html",
        {
            "request": request,
            "title": "Регистрация",
            "static_version": datetime.now().strftime("%Y%m%d%H%M"),
        },
    )


# Личный кабинет
@web_router.get("/account", response_class=HTMLResponse)
async def profile(request: Request):
    return templates.TemplateResponse(
        "landing/profile.html",
        {
            "request": request,
            "title": "Личный кабинет",
            "static_version": datetime.now().strftime("%Y%m%d%H%M"),
        },
    )
