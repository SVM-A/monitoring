# bot/handlers/callbacks.py
import re
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from app.core.config import elya_chat_id
from app.utils.logger import logger
from bot.states.send_message import SendMessageStates
from bot.handlers.massages import process_get_gift, process_start_private_chat, process_start_public_chat

call_router = Router()

@call_router.callback_query(F.data == "gift")
async def get_gift_callback(call: CallbackQuery):
    await process_get_gift(message=call)

@call_router.callback_query(F.data == "main_menu")
async def get_gift_callback(call: CallbackQuery):
    from_user = call.from_user
    chat = call.message.chat
    logger.info(f"/start от {from_user.id} в чате {chat.id} ({chat.type})")
    if chat.type == "private":
        await process_start_private_chat(call)
    elif chat.type in ["group", "supergroup"]:
        await process_start_public_chat(call)
    else:
        await call.message.answer("Бот работает только в приватных чатах и группах.")

@call_router.callback_query(F.data == "send")
async def start_send_message(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Напиши сообщение для Эли. Чтобы отменить, отправь /cancel.")
    await state.set_state(SendMessageStates.waiting_for_text)
