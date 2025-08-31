from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class AdminCallback(CallbackData, prefix="adm"):
    section: str                 # "menu" | "stats" | ...
    action: str | None = None    # "open" | "pick_file" | "period" | "files_page" | "back"
    period: str | None = None    # "today" | "7d" | "30d"
    file: str | None = None      # md5(file_name) hex
    page: int | None = None      # pagination for files
    ban_id: str | None = None    # UUID текста (для удаления/подтверждения)



def admin_main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📥 Отчет по подаркам",
        callback_data=AdminCallback(section="stats", action="open").pack(),
    )
    kb.button(text="🚫 Чёрный список сообщений",
              callback_data=AdminCallback(section="ban", action="open").pack())
    kb.adjust(1)
    # kb.button(text="👤 Пользователи", callback_data=AdminCallback(section="users", action="open").pack())
    return kb.as_markup()

######## Бан лист текстов сообщений

def ban_root_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить текст в бан",
              callback_data=AdminCallback(section="ban", action="add").pack())
    kb.button(text="📜 Посмотреть список бана",
              callback_data=AdminCallback(section="ban", action="list", page=1).pack())
    kb.button(text="🗑️ Удалить из бана",
              callback_data=AdminCallback(section="ban", action="del_list", page=1).pack())
    kb.button(text="🏠 В меню",
              callback_data=AdminCallback(section="menu", action="open").pack())
    kb.adjust(1)
    return kb.as_markup()

def build_ban_list(items: list[tuple[str, str]], page: int, has_prev: bool, has_next: bool, mode: str) -> InlineKeyboardMarkup:
    """
    items: [(ban_id, label)]
    mode: "view" | "delete"
    """
    kb = InlineKeyboardBuilder()
    for _id, label in items:
        if mode == "view":
            # просто неактивный просмотр — делаем кнопку без действия
            kb.button(text=f"• {label}", callback_data=AdminCallback(section="ban", action="noop").pack())
        else:
            kb.button(text=f"🗑️ {label}",
                      callback_data=AdminCallback(section="ban", action="del_pick", ban_id=_id, page=page).pack())

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(
            text="« Назад",
            callback_data=AdminCallback(section="ban", action=("del_list" if mode == "delete" else "list"), page=page-1).pack()
        ))
    if has_next:
        nav_row.append(InlineKeyboardButton(
            text="Вперёд »",
            callback_data=AdminCallback(section="ban", action=("del_list" if mode == "delete" else "list"), page=page+1).pack()
        ))
    if nav_row:
        kb.row(*nav_row)

    kb.button(text="⬅️ Назад", callback_data=AdminCallback(section="ban", action="open").pack())
    kb.button(text="🏠 В меню", callback_data=AdminCallback(section="menu", action="open").pack())
    kb.adjust(1)
    return kb.as_markup()

def confirm_delete_menu(ban_id: str, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Удалить", callback_data=AdminCallback(section="ban", action="del_confirm", ban_id=ban_id, page=page).pack())
    kb.button(text="❌ Отмена", callback_data=AdminCallback(section="ban", action="del_list", page=page).pack())
    kb.adjust(2)
    return kb.as_markup()



######## Подарки

def stats_period_menu(selected: str, file_token: str) -> InlineKeyboardMarkup:
    # three period buttons + back to files + back to root
    def _mark(lbl: str, val: str) -> str:
        return f"• {lbl}" if val == selected else lbl

    kb = InlineKeyboardBuilder()
    kb.button(text=_mark("Сегодня", "today"),
              callback_data=AdminCallback(section="stats", action="period", period="today", file=file_token).pack())
    kb.button(text=_mark("Последние 7 дней", "7d"),
              callback_data=AdminCallback(section="stats", action="period", period="7d", file=file_token).pack())
    kb.button(text=_mark("Последние 30 дней", "30d"),
              callback_data=AdminCallback(section="stats", action="period", period="30d", file=file_token).pack())
    kb.button(text="⬅️ Выбрать другой файл",
              callback_data=AdminCallback(section="stats", action="back", file=file_token).pack())
    kb.button(text="🏠 В меню",
              callback_data=AdminCallback(section="menu", action="open").pack())
    kb.adjust(1)
    return kb.as_markup()


def build_files_menu(items: list[tuple[str, str]], page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """
    items: list of (file_token_md5, display_text)
    """
    kb = InlineKeyboardBuilder()
    for token, label in items:
        kb.button(
            text=label,
            callback_data=AdminCallback(section="stats", action="pick_file", file=token).pack(),
        )

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="« Назад",
                callback_data=AdminCallback(section="stats", action="files_page", page=page - 1).pack(),
            )
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="Вперёд »",
                callback_data=AdminCallback(section="stats", action="files_page", page=page + 1).pack(),
            )
        )
    if nav_row:
        kb.row(*nav_row)

    kb.button(text="🏠 В меню",
              callback_data=AdminCallback(section="menu", action="open").pack())
    kb.adjust(1)
    return kb.as_markup()