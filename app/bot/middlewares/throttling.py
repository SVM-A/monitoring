from aiogram import BaseMiddleware
from aiogram.types import Message
from cachetools import TTLCache

from app.utils.logger import logger


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: int = 1):
        self.cache = TTLCache(maxsize=10_000, ttl=rate_limit)

    async def __call__(self, handler, event: Message, data):
        if event.from_user.id in self.cache:
            logger.warning(f"Throttling user: {event.from_user.id}")
            return None
        self.cache[event.from_user.id] = True
        return await handler(event, data)