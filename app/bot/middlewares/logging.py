# app/bot/middlewares/logging.py
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
from typing import Union, Any

from app.utils.logger import logger

EventType = Union[Message, CallbackQuery, Update]


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: callable,
            event: EventType,
            data: dict
    ) -> Any:
        user = data.get("event_from_user")

        # Безопасное получение chat_id для разных типов событий
        chat_id = None
        if hasattr(event, 'chat') and event.chat:
            chat_id = event.chat.id
        elif hasattr(event, 'message') and event.message:
            chat_id = event.message.chat.id
        elif hasattr(event, 'callback_query') and event.callback_query:
            chat_id = event.callback_query.message.chat.id

        logger.debug(
            f"⇢ {event.__class__.__name__} | "
            f"User: {user.id if user else 'system':<10} | "
            f"Chat: {chat_id if chat_id else 'N/A':<15} | "
            f"Data: {str(event)[:50]}..."
        )

        try:
            result = await handler(event, data)
            logger.debug(
                f"⇠ {event.__class__.__name__} | "
                f"User: {user.id if user else 'system':<10} | "
                f"Status: PROCESSED"
            )
            return result
        except Exception as e:
            logger.error(
                f"⇠ {event.__class__.__name__} | "
                f"User: {user.id if user else 'system':<10} | "
                f"Status: ERROR | "
                f"Exception: {type(e).__name__}: {str(e)}"
            )
            raise