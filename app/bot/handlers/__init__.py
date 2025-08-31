# app/bot/handlers/__init__.py

from aiogram import Dispatcher

from app.utils.logger import logger
from .commands import chat_router
from .callbacks import call_router
from .states_handlers import state_router
from .for_groups import groups_monitor_router
from .admin import admin_router


def register_routers(dp: Dispatcher):
    logger.info("Регистрация всех роутеров")
    dp.include_router(chat_router)
    dp.include_router(call_router)
    dp.include_router(state_router)
    dp.include_router(groups_monitor_router)
    dp.include_router(admin_router)

