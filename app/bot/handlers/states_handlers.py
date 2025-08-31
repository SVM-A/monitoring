# bot/handlers/states_handlers.py
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.utils.logger import logger
from bot.states.send_message import SendMessageStates
from app.core.config import elya_chat_id

state_router = Router()


@state_router.message(SendMessageStates.waiting_for_text)
async def handle_user_message(message: Message, state: FSMContext):
    logger.info("handle_user_message вызван")
    text = message.text
    await message.bot.send_message(
        elya_chat_id(),
        f"Новое сообщение от @{message.from_user.username or message.from_user.first_name} ({message.from_user.id}):\n\n{text}"
    )
    await message.answer("Сообщение отправлено Эле!")
    await state.clear()


@state_router.message(Command("cancel"), SendMessageStates.waiting_for_text)
async def cancel_send_message(message: Message, state: FSMContext):
    await message.answer("Отменено.")
    await state.clear()

@state_router.message(SendMessageStates.waiting_for_text, F.text.in_(["cancel", "отмена"]))
async def cancel_text_message(message: Message, state: FSMContext):
    await message.answer("Отменено.")
    await state.clear()






