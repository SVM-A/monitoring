# bot/keyboards/inline.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

gift_button = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎁 Получить подарок", callback_data="gift")]
])

go_to_beahea_bot_for_gift = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎁 Получить подарок", url="https://t.me/beaheaBot")]
])

go_to_public_channel = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Перейти в канал", url="https://t.me/beahea_public")]
])

main_menu_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="🎁 Получить подарок", callback_data="gift"),
            InlineKeyboardButton(text="📣 Эля, Еда и Гантеля.", url="https://t.me/beahea_public"),
        ],
        [
            InlineKeyboardButton(text="💬 Написать Эле.", callback_data="send"),
            # InlineKeyboardButton(text="🌐 Веб страница.", url="https://beahea.ru"),
        ],
    ]
)


