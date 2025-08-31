# app/bot/handlers/user_chats.py

import re
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext

from app.core.config import elya_chat_id
from app.utils.logger import logger
from bot.states.send_message import SendMessageStates
from bot.decorators import bot_error_handler
from bot.handlers.massages import process_get_gift, process_start_private_chat, process_start_public_chat
from bot.keyboards.inline import go_to_public_channel, go_to_beahea_bot_for_gift

chat_router = Router()


@chat_router.message(CommandStart())
@bot_error_handler
async def handle_start(message: Message):
    from_user = message.from_user
    chat = message.chat
    logger.info(f"/start от {from_user.id} в чате {chat.id} ({chat.type})")
    if chat.type == "private":
        await process_start_private_chat(message)
    elif chat.type in ["group", "supergroup"]:
        await process_start_public_chat(message)
    else:
        await message.answer("Бот работает только в приватных чатах и группах.")



@chat_router.message(Command("message_gift"))
@bot_error_handler
async def get_gift_cmd(message: Message):
    welcome_msg = (
        "🎁 <b>Получите подарок</b> у нашего <a href=\"https://t.me/beaheaBot\"><b>Телеграм бота</b></a>"
    )
    await message.answer(welcome_msg, parse_mode="HTML", reply_markup=go_to_beahea_bot_for_gift)


@chat_router.message(Command("gift"))
async def get_gift_cmd(message: Message):
    await process_get_gift(message=message)




@chat_router.message(Command("public_channel"))
async def public_channel_cmd(message: Message):
    await message.answer(
        "Канал «Эля, Еда и Гантеля» — подписывайся!",
        reply_markup=go_to_public_channel
    )

@chat_router.message(Command("chat_id"))
@bot_error_handler
async def get_gift_cmd(message: Message):
    chat = message.chat
    await message.answer(text=f"Chat_id {chat.id}", parse_mode="HTML")



@chat_router.message(Command("send"))
async def get_gift_cmd(message: Message, state: FSMContext):
    await message.answer("Напиши сообщение для Эли. Чтобы отменить, отправь /cancel.")
    await state.set_state(SendMessageStates.waiting_for_text)



@chat_router.message(F.reply_to_message, F.chat.id == elya_chat_id())
@bot_error_handler
async def handle_elya_reply(message: Message):
    logger.debug("handle_elya_reply вызван")
    logger.debug(f"from_user.id: {message.from_user.id}")
    logger.debug(f"from_user.first_name: {message.from_user.first_name}")
    logger.debug(f"from_user.last_name: {getattr(message.from_user, 'last_name', None)}")
    logger.debug(f"message.text: {message.text}")
    logger.debug(f"reply_to_message: {message.reply_to_message}")
    logger.debug(f"elya_chat_id(): {elya_chat_id()}")
    logger.debug(f"type(message.from_user.id): {type(message.from_user.id)}")
    logger.debug(f"type(elya_chat_id()): {type(elya_chat_id())}")
    if not message.reply_to_message:
        logger.debug("Нет reply_to_message, выход.")
        await message.answer("Ты не ответила на сообщение, а просто написала новое.")
        return

    original = message.reply_to_message.text or ""
    logger.debug(f"Оригинальный текст reply_to_message: {original}")

    match = re.search(r"\((\d+)\):", original)
    if not match:
        logger.debug("Не найден ID пользователя в reply_to_message.")
        await message.answer("Не могу определить ID пользователя для ответа. Вот что было в reply:\n" + original)
        return

    user_id = int(match.group(1))
    logger.debug(f"Извлечённый user_id: {user_id}")

    # Проверяем, есть ли текст для отправки
    if not message.text:
        logger.debug("Пустое сообщение-ответ.")
        await message.answer("Ответ пустой, нечего отправлять пользователю.")
        return

    # Пробуем отправить сообщение пользователю
    try:
        await message.bot.send_message(
            user_id,
            f"Ответ от Эли:\n{message.text}"
        )
        logger.debug(f"Сообщение успешно отправлено пользователю {user_id}")
        await message.answer("Ответ отправлен!")
    except Exception as e:
        logger.exception(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
        await message.answer("Ошибка при отправке ответа. Проверь логи.")