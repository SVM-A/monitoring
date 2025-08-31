# app/bot/handlers/user_chats.py

from datetime import datetime, timezone, timedelta

from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramRetryAfter, TelegramBadRequest, TelegramNotFound
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.enums import ChatAction
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import public_channel_chat_id, get_projects_path, elya_chat_id, get_admin_ids
from app.db.models.service_notifier import TelegramUser, TGKeys, TelegramChat, ReceivedGift
from app.db.schemas.service_notifier import ChatCreate
from app.db.sessions import async_connect_db
from app.utils.logger import logger
from bot.decorators import bot_error_handler
from bot.keyboards.inline import main_menu_keyboard, go_to_public_channel

GIFT_FILE = FSInputFile(get_projects_path().GIFT_FILE_PATH)

@bot_error_handler
@async_connect_db(commit=True)
async def process_get_gift(message: Message | CallbackQuery, db: AsyncSession):
    if isinstance(message, CallbackQuery):
        user_id = message.from_user.id
        bot = message.bot
        send = message.message.answer
        await message.answer()
    else:
        user_id = message.from_user.id
        bot = message.bot
        send = message.answer

    try:
        chat_member = await bot.get_chat_member(chat_id=public_channel_chat_id(), user_id=user_id)
    except TelegramAPIError:
        await send("Ошибка проверки подписки. Попробуйте позже.")
        return
    del_msg = None
    status = chat_member.status
    if status in ("member", "administrator", "creator"):
        try:
            tg_id = (await db.execute(select(TelegramUser.id).where(TelegramUser.telegram_id == message.from_user.id))).scalar_one_or_none()
            if tg_id:
                rec_gift = ReceivedGift(tg_user_id=tg_id, file_name=str(get_projects_path().GIFT_FILE_PATH).split("/")[-1])
                db.add(rec_gift)
                await db.flush()
            del_msg = await bot.send_message(chat_id=user_id, text='Начинаем отправлять файл, подождите секндочку.')
            await bot.send_chat_action(chat_id=user_id, action=ChatAction.UPLOAD_DOCUMENT)
            await bot.send_document(
                chat_id=user_id,
                document=GIFT_FILE,
                caption="🎁 Ваш подарок!\nСпасибо за интерес к нашему каналу!"
            )
        except TelegramForbiddenError:
            await send("Сначала напишите боту в личку, чтобы получить подарок: @beaheaBot")
        except TelegramRetryAfter as e:
            await send("Сервис перегружен. Попробуйте ещё раз немного позже.")
        except TelegramBadRequest as e:
            await send("Не удалось отправить файл. Сообщили администратору.")
        finally:
            if del_msg:
                await bot.delete_message(chat_id=user_id, message_id=del_msg.message_id)
    else:
        await send(
            "Сначала подпишитесь на канал, чтобы получить подарок!",
            reply_markup=go_to_public_channel
        )

@bot_error_handler
@async_connect_db(commit=True)
async def process_start_private_chat(message: Message | CallbackQuery, db: AsyncSession):
    if isinstance(message, CallbackQuery):
        from_user = message.from_user
        send = message.message.answer
        await message.answer()
    else:
        from_user = message.from_user
        send = message.answer

    logger.info('1. Работаем в приватном чате. Получаем или создаем пользователя.')

    stmt = select(TelegramUser).where(TelegramUser.telegram_id == from_user.id)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user:
        logger.info('   Обновляем данные пользователя')
        user.first_name = from_user.first_name
        user.last_name = from_user.last_name
        user.username = from_user.username
        user.language_code = from_user.language_code
        logger.info(f"  Обновлен пользователь: {user.telegram_id}")
    else:
        logger.info('   Создаем нового пользователя')
        user = TelegramUser(
            telegram_id=from_user.id,
            is_bot=from_user.is_bot,
            first_name=from_user.first_name,
            last_name=from_user.last_name,
            username=from_user.username,
            language_code=from_user.language_code
        )
        db.add(user)
        logger.info(f"   Создан пользователь: {user.telegram_id}")

    logger.info("2. Фиксируем изменения в БД для пользователя")
    await db.flush()

    logger.info("3. Проверяем наличие токена")
    token_stmt = select(TGKeys).where(TGKeys.tg_user_id == user.id)
    existing_token = (await db.execute(token_stmt)).scalar_one_or_none()

    if not existing_token:
        logger.info("   Создаем новый токен")
        verification_key = TGKeys(tg_user_id=user.id, tg_chat_id=None)
        db.add(verification_key)
        await db.flush()
        logger.info(f"   Создан токен для пользователя: {user.telegram_id}")
    else:
        logger.info("   Обновляем срок действия токена")
        existing_token.expires_at = datetime.now(timezone.utc) + timedelta(days=3)
        logger.info(f"   Обновлен токен пользователя: {user.telegram_id}")

    logger.info("4. Получаем полные данные с токеном")
    full_stmt = (
        select(TelegramUser)
        .options(selectinload(TelegramUser.verification_key))
        .where(TelegramUser.telegram_id == from_user.id)
    )
    user_with_token = (await db.execute(full_stmt)).scalar_one()

    # Специфичная обработка
    if not user_with_token.verification_key:
        logger.error("   Токен не был создан")
        await send("Временно не удалось создать доступ. Мы уже решаем вопрос — попробуй через пару минут!")
        return  # дальше не продолжаем

    logger.info("5. Формируем сообщение")

    welcome_msg = (
        "👋 <b>Привет!</b> Это телеграм-бот для получения уведомлений от Эли.\n"
        "Ты успешно подключился ✨\n\n"
        "📣 <b>Публичный канал «Эля, Еда и Гантеля»:</b>\n"
        "<a href=\"https://t.me/beahea_public\">https://t.me/beahea_public</a>\n"
        "Пишу о ЗОЖ без перегибов: питание, спорт и жизнь в балансе.\n"
        "Как сохранить форму и не угробить здоровье – всё здесь.\n\n"
        "⚙️ Бот пока на стадии разработки, но скоро появится много полезных фишек, так что оставайся на связи!\n\n"
    )
    await send(welcome_msg, parse_mode="HTML", reply_markup=main_menu_keyboard)

@bot_error_handler
@async_connect_db(commit=True)
async def process_start_public_chat(message: Message | CallbackQuery, db: AsyncSession):
    if isinstance(message, CallbackQuery):
        chat = message.message.chat
        send = message.message.answer
        await message.answer()
    else:
        chat = message.chat
        send = message.answer
    logger.info("1. Работаем в группе. Регистрируем чат, если не зарегистрирован.")

    stmt = select(TelegramChat).where(TelegramChat.telegram_id == chat.id)
    chat_db = (await db.execute(stmt)).scalar_one_or_none()

    if chat_db:
        logger.info(f'   Обновляем данные {chat_db.type}')
        chat_db.type = chat_db.type
        chat_db.title = chat_db.title
        chat_db.username = chat_db.username
        chat_db.first_name = chat_db.first_name
        chat_db.last_name = chat_db.last_name
        chat_db.is_forum = chat_db.is_forum
        chat_db.invite_link = chat_db.invite_link
        chat_db.photo_id = chat_db.photo_id
        chat_db.is_active = True
        logger.info(f"  Обновлен {chat_db.type}: {chat_db.telegram_id}")

    else:
        chat_data = ChatCreate.from_telegram(chat)
        logger.info(f'   Создаем новый {chat_data.type}')
        chat_db = TelegramChat(
            telegram_id=chat_data.telegram_id,
            type=chat_data.type,
            title=chat_data.title,
            username=chat_data.username,
            first_name=chat_data.first_name,
            last_name=chat_data.last_name,
            is_forum=chat_data.is_forum,
            invite_link=chat_data.invite_link,
            photo_id=chat_data.photo_id,
        )
        db.add(chat_db)
        logger.info(f"   Создан {chat_db.type}: {chat_db.telegram_id}")

    logger.info(f"2. Фиксируем изменения в БД для {chat_db.type}")
    await db.flush()

    logger.info("3. Проверяем наличие токена")
    token_stmt = select(TGKeys).where(TGKeys.tg_chat_id == chat_db.id)
    existing_token = (await db.execute(token_stmt)).scalar_one_or_none()

    if not existing_token:
        logger.info("   Создаем новый токен")
        verification_key = TGKeys(tg_chat_id=chat_db.id)
        db.add(verification_key)
        await db.flush()
        logger.info(f"   Создан токен для {chat_db.type}: {chat_db.telegram_id}")
    else:
        logger.info("   Обновляем срок действия токена")
        existing_token.expires_at = datetime.now(timezone.utc) + timedelta(days=36000)
        logger.info(f"   Обновлен токен пользователя: {chat_db.telegram_id}")

    logger.info("4. Получаем полные данные с токеном")
    full_stmt = (
        select(TelegramChat)
        .options(selectinload(TelegramChat.verification_key))
        .where(TelegramChat.telegram_id == chat.id)
    )
    chat_with_token = (await db.execute(full_stmt)).scalar_one()

    if not chat_with_token.verification_key:
        logger.error("   Токен не был создан")
        await send(
            "Временно не удалось создать доступ для группы. Мы уже решаем вопрос — попробуйте через пару минут!")
        return

    logger.info("5. Формируем сообщение")

    welcome_msg = (
        "👋 <b>Бот для уведомлений от Эли успешно добавлен в группу!</b>\n\n"
        "📣 <b>Публичный канал «Эля, Еда и Гантеля»:</b>\n"
        "<a href=\"https://t.me/beahea_public\">https://t.me/beahea_public</a>\n"
        "ЗОЖ без перегибов: питание, спорт и жизнь в балансе.\n\n"
        "⚙️ Бот сейчас в разработке. Скоро здесь появятся полезные функции для взаимодействия, обучения и поддержки.\n\n"
    )

    await send(welcome_msg, parse_mode="HTML", reply_markup=main_menu_keyboard)



