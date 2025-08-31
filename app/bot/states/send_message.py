# bot/states/send_message.py

from aiogram.fsm.state import StatesGroup, State

class SendMessageStates(StatesGroup):
    waiting_for_text = State()


class BanStates(StatesGroup):
    waiting_text = State()