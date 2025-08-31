from http.client import HTTPException
from typing import Callable, Coroutine, Any, TypeVar
from functools import wraps
from datetime import datetime

from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.service_notifier import TelegramUser, TelegramChat
from app.utils.logger import logger

T = TypeVar('T', TelegramUser, TelegramChat)


def bot_error_handler(func):
    @wraps(func)
    async def wrapper(message: Message | CallbackQuery, *args, **kwargs):
        # Определяем user_id и chat_id
        if isinstance(message, CallbackQuery):
            user_id = getattr(message.from_user, "id", None)
            chat_id = getattr(getattr(message.message, "chat", None), "id", None)
            send = message.message.answer
        else:
            user_id = getattr(message.from_user, "id", None)
            chat_id = getattr(message.chat, "id", None)
            send = message.answer
        timestamp = datetime.now().isoformat(timespec='seconds')
        try:
            return await func(message, *args, **kwargs)
        except HTTPException as http_exp:
            return http_exp
        except TelegramAPIError as e:
            logger.error(f"[{timestamp}] Telegram API error: {e} | user_id={user_id} | chat_id={chat_id}", exc_info=True)
            await send("⚠️ Произошла ошибка при обработке запроса. Попробуйте позже.")
        except SQLAlchemyError as e:
            logger.critical(f"[{timestamp}] Database error: {e} | user_id={user_id} | chat_id={chat_id}", exc_info=True)
            await send("🔧 Технические неполадки. Мы уже работаем над решением.")
        except Exception as e:
            logger.error(f"[{timestamp}] Unexpected error: {e} | user_id={user_id} | chat_id={chat_id}", exc_info=True)
            await send("❌ Произошла непредвиденная ошибка. Администратор уведомлен.")
    return wrapper


