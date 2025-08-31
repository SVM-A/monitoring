# bot/__init__.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest
from aiogram_sqlite_storage.sqlitestore import SQLStorage

from app.core.config import bot_token_env, get_projects_path, webhooks_full_path, webhook_token_env, debug_mode
from app.utils.logger import logger
from bot.handlers import register_routers
from bot.middlewares import setup_middlewares

# Инициализация бота и диспетчера
bot = Bot(token=bot_token_env(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=SQLStorage(str(get_projects_path().FSM_STORAGE_PATH / 'storage.db')))

# Инициализация middleware и роутеров один раз
setup_middlewares(dp)
register_routers(dp)

async def setup_webhook():
    """Настройка вебхука (для prod)"""
    if not debug_mode():
        try:
            logger.info(f"Webhook URL: {webhooks_full_path()}")
            info = await bot.get_webhook_info()
            if info.url != webhooks_full_path():
                await bot.set_webhook(
                    url=webhooks_full_path(),
                    secret_token=webhook_token_env(),
                    drop_pending_updates=True,
                    allowed_updates=[
                        "message",
                        "edited_message",
                        "callback_query",
                        "inline_query",
                        "chat_member",
                        "my_chat_member",
                    ]
                )
            logger.success("✅ Webhook установлен успешно")
        except TelegramRetryAfter as e:
            logger.warning(f"⏳ Превышен лимит запросов Telegram, повторить через {e.retry_after} сек.")
        except TelegramBadRequest as e:
            logger.error(f"❌ Ошибка установки вебхука: {e.message}")
        except Exception as e:
            logger.critical(f"💥 Неизвестная ошибка при установке webhook: {e}")

async def remove_webhook():
    """Удаление вебхука"""
    if not debug_mode():
        await bot.delete_webhook()
        logger.info("Webhook removed")
    await bot.session.close()
    await dp.storage.close()
    logger.success("✅ Завершили webhook режим")


async def run_polling_mode():
    """Запуск бота в polling режиме (для разработки)"""
    logger.warning("Running in DEBUG mode (polling)")
    await bot.delete_webhook()
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Polling failed: {e}")
        raise
    finally:
        logger.info("🧹 Завершаем polling: закрываем session и storage")
        await bot.session.close()
        await dp.storage.close()
        pending = asyncio.all_tasks()
        for task in pending:
            if task is not asyncio.current_task():
                task.cancel()
        logger.success("✅ Завершили polling режим")
