# app/utils/logger.py [AUTOGEN_PATH]

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
