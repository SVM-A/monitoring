from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from app.utils.logger import logger


all_http_exceptions = tuple(
    exc for exc in globals().values() if isinstance(exc, type) and issubclass(exc, HTTPException)
)

# Функция регистрации обработчиков ошибок
def register_exception_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def custom_exception_handler(exc: HTTPException):
        if isinstance(exc, all_http_exceptions):
            # Для этого исключения выводим только сообщение без трассировки
            logger.error(f"Ошибка аутентификации: {exc.detail}")
        else:
            # Для остальных ошибок выводим обычную трассировку
            logger.exception(f"Необработанное исключение: {exc.detail}")
        return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})
