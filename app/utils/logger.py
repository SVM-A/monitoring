# app/utils/logger.py [AUTOGEN_PATH]

"""
Конфигурация логирования для FastAPI-приложения с использованием Loguru и стандартного logging-модуля.
Позволяет централизованно управлять логами в режиме разработки и продакшене, создаёт структуру логов по типам,
поддерживает авто-ротацию, архивирование, фильтрацию и сериализацию в JSON для интеграции с системами мониторинга.

Основные возможности:
---------------------
✅ Режимы логирования:
    - developer: DEBUG и INFO выводятся в консоль, WARNING+ пишутся в файлы и дублируются в консоль.
    - production: DEBUG и INFO только в консоль, WARNING+ — в файлы и консоль.

✅ Поддержка разных форматов логов:
    - debug.log       — DEBUG и выше (только developer)
    - info.log        — INFO и выше (только developer)
    - error.log       — WARNING и выше
    - runtime.log     — WARNING и выше (для ошибок исполнения)
    - access.log      — логи HTTP-доступа (из uvicorn.access)
    - audit.log       — только события с пометкой extra={"context": "audit"}
    - sql.log         — SQLAlchemy engine (sqlalchemy.engine)
    - structured.json — INFO+ в JSON формате (подходит для ELK, Datadog, Loki)

✅ Централизованные настройки хранения логов:
    - rotation    — по размеру (например, "10 MB")
    - retention   — срок хранения (например, "30 days")
    - compression — сжатие устаревших логов (zip)

✅ Гибкие фильтры:
    - По имени логгера (например, "uvicorn.access")
    - По содержимому record["extra"]

✅ Кроссплатформенная защита от проблем с правами:
    - Пытается писать в директорию logs (BASE_PATH/logs/YYYY-MM-DD)
    - При ошибке — автоматически переключается на /tmp/logs

✅ Визуальное приветствие при запуске:
    - Структурированный блок с системной информацией (в стиле рамки)

Как использовать:
-----------------
1. Импортируй в приложении:
       from app.app.utils.logger import logger

2. Пиши логи:
       logger.info("Запуск сервиса")
       logger.debug("Входные данные: {}", data)
       logger.bind(context="audit").info("Пользователь вошёл в систему")

3. Если хочешь лог писать в audit.log, обязательно добавь:
       `logger.bind(context="audit").info("...")`

4. Для structured.json ничего не нужно дополнительно — туда попадут все INFO+ логи
   в сериализованном (JSON) виде.
   Чтобы structured-логи имели смысл, в них нужно добавлять поля:
        logger.bind(user_id=42).info("Действие пользователя")

Пример логов в файлах:
----------------------
logs/2025-06-28/debug.log
logs/2025-06-28/error.log
logs/2025-06-28/structured.json

Пример строки structured.json:
{"time": "2025-06-28T15:32:17.524Z", "level": "INFO", "message": "Запуск сервиса"}

Примечания:
-----------
- Можно расширять структуру LOG_CONFIGS для создания новых шаблонов хранения логов.
- Путь логов и режим работы определяется переменными BASE_PATH и TYPE_NETWORK.
- Логи SQLAlchemy активны по умолчанию (sqlalchemy.engine, sqlalchemy.pool).
"""


import logging
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger as _logger

from app.core.config import BASE_PATH, get_app_settings

BASE_LOGS_PATH = os.path.join(BASE_PATH, "logs")

try:
    Path(BASE_LOGS_PATH).mkdir(parents=True, exist_ok=True)
except PermissionError:
    fallback_path = "/tmp"
    print(
        f"[LOGGER INIT] ❌ Нет прав на {BASE_LOGS_PATH}, переключаюсь на {fallback_path}"
    )
    BASE_LOGS_PATH = fallback_path
    Path(BASE_LOGS_PATH).mkdir(parents=True, exist_ok=True)

log_dir = Path(BASE_LOGS_PATH) / datetime.now().strftime("%Y-%m-%d")
try:
    log_dir.mkdir(parents=True, exist_ok=True)
except PermissionError:
    print(f"[LOGGER INIT] ❌ Нет прав на {log_dir}, переключаюсь на /tmp/logs")
    log_dir = Path("/tmp/logs") / datetime.now().strftime("%Y-%m-%d")
    log_dir.mkdir(parents=True, exist_ok=True)

# Единая конфигурация логов
LOG_CONFIGS = {
    "average_retention": dict(rotation="10 MB", retention="5 days", compression="zip"),
    "short_retention": dict(rotation="5 MB", retention="2 days", compression="zip"),
    "long_retention": dict(rotation="10 MB", retention="10 days", compression="zip"),
}


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = _logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        _logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

for name in ("sqlalchemy.engine", "sqlalchemy.pool"):
    logging.getLogger(name).setLevel(logging.DEBUG)


def _safe_add_log(path, level, **kwargs):
    try:
        _logger.add(path, level=level, **kwargs)
    except PermissionError:
        _logger.warning(f"❌ Нет доступа к {path}, лог будет писаться только в stdout")


def setup_logger():
    _logger.remove()

    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} | "
        "{extra} | "
        "{message}"
    )

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<magenta>{extra}</magenta> | "
        "<level>{message}</level>"
    )

    is_dev = get_app_settings().TYPE_NETWORK == "dev"

    _logger.add(
        sys.stdout,
        format=console_format,
        level="DEBUG",
        colorize=True,
        backtrace=True,
        diagnose=True,
        filter=lambda r: True,
    )

    if is_dev:
        _safe_add_log(
            os.path.join(log_dir, "debug.log"),
            level="DEBUG",
            format=file_format,
            **LOG_CONFIGS["average_retention"],
        )
        _safe_add_log(
            os.path.join(log_dir, "info.log"),
            level="INFO",
            format=file_format,
            **LOG_CONFIGS["average_retention"],
        )

    _safe_add_log(
        os.path.join(log_dir, "error.log"),
        level="WARNING",
        format=file_format,
        **LOG_CONFIGS["long_retention"],
    )

    _safe_add_log(
        os.path.join(log_dir, "access.log"),
        level="INFO",
        filter=lambda record: record["name"].startswith("uvicorn.access"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        **LOG_CONFIGS["short_retention"],
    )

    _safe_add_log(
        os.path.join(log_dir, "audit.log"),
        level="INFO",
        filter=lambda record: record["extra"].get("context") == "audit",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {extra} | {message}",
        **LOG_CONFIGS["average_retention"],
    )

    _safe_add_log(
        os.path.join(log_dir, "sql.log"),
        level="DEBUG",
        filter=lambda record: "sqlalchemy.engine" in record["name"],
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        **LOG_CONFIGS["short_retention"],
    )

    _safe_add_log(
        os.path.join(log_dir, "runtime.log"),
        level="WARNING",
        format=file_format,
        **LOG_CONFIGS["short_retention"],
    )

    _safe_add_log(
        os.path.join(log_dir, "structured.json"),
        level="INFO",
        format="{time} {level} {message}",
        serialize=True,
        **LOG_CONFIGS["short_retention"],
    )

    # Стартовая рамка
    system_info = f"System: {platform.system()} {platform.release()}"
    python_info = f"Python: {platform.python_version()}"
    time_info = f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    title = "FASTAPI APP INITIALIZATION"

    lines = [title, system_info, python_info, time_info]
    content_width = max(len(line) for line in lines)
    total_width = content_width + 4

    def format_line(content: str) -> str:
        return f"║ {content.ljust(content_width)} ║"

    _logger.info("")
    _logger.info("╔" + "═" * (total_width - 2) + "╗")
    _logger.info(format_line(title.center(content_width)))
    _logger.info("╠" + "═" * (total_width - 2) + "╣")
    _logger.info(format_line(system_info))
    _logger.info(format_line(python_info))
    _logger.info(format_line(time_info))
    _logger.info("╚" + "═" * (total_width - 2) + "╝")
    _logger.info("")

    return _logger


logger = setup_logger()
