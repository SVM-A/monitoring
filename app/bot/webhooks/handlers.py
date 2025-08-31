# bot/webhooks/handlers.py

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update

from bot import dp, bot
from app.core.config import webhook_path, webhook_token_env
from app.utils.logger import logger
from app.db.models.service_notifier import TelegramUser
from app.db.schemas.service_notifier import NotificationsRequest, NotificationRequest
from app.db.sessions import SessionDep


bot_router = APIRouter()


async def verify_webhook_key(x_api_key: str = Header(...)):
    if x_api_key != webhook_token_env():
        raise HTTPException(status_code=403, detail="Forbidden")



@bot_router.post(webhook_path())
async def handle_webhook(request: Request):
    try:
        # 1. Парсинг входящего JSON
        try:
            json_data = await request.json()
            update = Update.model_validate(json_data)
        except ValidationError as ve:
            logger.error(f"Validation error: {ve}")
            raise HTTPException(status_code=422, detail="Invalid update format")
        except Exception as e:
            logger.error(f"JSON parsing error: {e}")
            raise HTTPException(status_code=400, detail="Malformed JSON data")

        # 2. Обработка обновления
        try:
            await dp.feed_update(bot, update)
        except TelegramAPIError as te:
            logger.error(f"Telegram API error: {te}")
            raise HTTPException(
                status_code=502,
                detail=f"Telegram API error: {te.message}"
            )
        except SQLAlchemyError as se:
            logger.critical(f"Database error: {se}")
            await request.app.state.db_session.rollback()
            raise HTTPException(
                status_code=503,
                detail="Database operation failed"
            )
        except Exception as e:
            logger.error(f"Unexpected processing error: {e}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            )

        return JSONResponse(
            status_code=200,
            content={"status": "ok"},
            headers={"X-Webhook-Processed": "true"}
        )

    except HTTPException as he:
        # Уже обработанные ошибки
        raise
    except Exception as e:
        # Неожиданные ошибки верхнего уровня
        logger.critical(f"Critical webhook failure: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )



@bot_router.post("/sends")
async def notify_users(
        request: NotificationsRequest,
        verify_key = Depends(verify_webhook_key),
        session = SessionDep
):
    try:
        stmt = select(TelegramUser).where(TelegramUser.telegram_id.in_(request.telegram_id))
        result = await session.execute(stmt)
        tg_contacts = result.scalars().all()

        if not tg_contacts:
            raise HTTPException(status_code=404, detail="Контакты Telegram не найдены")

        for contact in tg_contacts:
            await bot.send_message(
                chat_id=contact.telegram_id,
                text=request.message,
                parse_mode="HTML"  # если нужно
            )

        logger.info(f'Сообщения отправлены пользователям: {", ".join(str(u.telegram_id) for u in tg_contacts)}')
        return {"detail": "Все сообщения успешно отправлены"}

    except Exception as e:
        logger.exception("Ошибка при отправке сообщений в Telegram", exc_info=e)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера при отправке уведомлений")

@bot_router.post("/send")
async def notify_user(
        request: NotificationRequest,
        verify_key=Depends(verify_webhook_key),
        session = SessionDep
):
    try:
        stmt = select(TelegramUser).where(TelegramUser.telegram_id == request.telegram_id)
        result = await session.execute(stmt)
        tg_contacts = result.scalars().all()

        if not tg_contacts:
            raise HTTPException(status_code=404, detail="Контакты Telegram не найдены")

        for contact in tg_contacts:
            await bot.send_message(
                chat_id=contact.telegram_id,
                text=request.message,
                parse_mode="HTML"  # если нужно
            )

        logger.info(f'Сообщение отправлено пользователю: {request.telegram_id}')
        return {"detail": "Сообщение успешно отправлено"}

    except Exception as e:
        logger.exception("Ошибка при отправке сообщения в Telegram", exc_info=e)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера при отправке уведомления")