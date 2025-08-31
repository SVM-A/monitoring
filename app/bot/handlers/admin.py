from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal

from aiogram import Router, F
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy import func, select, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_admin_ids
from app.db.sessions import async_connect_db
from app.db.models.service_notifier import ReceivedGift, BanMessageText, normalize_message_text, norm_hash
from app.utils.logger import logger
from bot.keyboards.admin_inline import AdminCallback, admin_main_menu, stats_period_menu, build_files_menu, \
    confirm_delete_menu, build_ban_list, ban_root_menu
from bot.states.send_message import BanStates

admin_router = Router(name="admin")


# === Filter ===
class AdminFilter(BaseFilter):
    async def __call__(self, message: Message | CallbackQuery) -> bool:
        user_id = (message.from_user if isinstance(message, Message) else message.from_user).id
        return user_id in set(get_admin_ids())


# apply filter
admin_router.message.filter(AdminFilter())
admin_router.callback_query.filter(AdminFilter())


# === Types & helpers ===
Period = Literal["today", "7d", "30d"]

FILES_PAGE_SIZE = 8
BAN_PAGE_SIZE = 10


def _period_bounds(period: Period) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == "7d":
        start = now - timedelta(days=7)
        end = now
    else:  # "30d"
        start = now - timedelta(days=30)
        end = now
    return start, end


def _normalize_for_naive_ts(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


async def _stats_for_period(
    db: AsyncSession,
    start: datetime | None = None,
    end: datetime | None = None,
    file_token: str | None = None,  # md5(file_name) hex
) -> tuple[int, int]:
    """
    Return (total_downloads, unique_users) for given window.
    If start/end is None => count for *all time*.
    If file_token is provided => filter by that file only.
    """
    start_n = _normalize_for_naive_ts(start)
    end_n = _normalize_for_naive_ts(end)

    stmt = select(
        func.count(ReceivedGift.id),
        func.count(func.distinct(ReceivedGift.tg_user_id)),
    )

    conditions = []
    if start_n and end_n:
        conditions.append(ReceivedGift.created_at.between(start_n, end_n))
    if file_token:
        # PostgreSQL md5(text) -> hex string
        conditions.append(func.md5(ReceivedGift.file_name) == file_token)

    if conditions:
        stmt = stmt.where(*conditions)

    res = await db.execute(stmt)
    total, unique_users = res.one()
    return int(total or 0), int(unique_users or 0)


def _format_stats_text(period_label: str, total: int, unique_users: int, all_total: int, all_unique: int, file_label: str) -> str:
    lines = [
        "📥 <b>Статистика скачиваний</b>",
        f"Файл: <b>{file_label}</b>",
        f"Период: <b>{period_label}</b>",
        "",
        f"— Всего скачиваний: <b>{total}</b>",
        f"— Уникальных пользователей: <b>{unique_users}</b>",
        "",
        f"За всё время по этому файлу: <b>{all_total}</b> скачиваний / <b>{all_unique}</b> пользователей",
    ]
    return "\n".join(lines)


def _shorten(s: str, n: int = 40) -> str:
    s = s.replace("\n", " ")
    return (s[:n] + "…") if len(s) > n else s

async def _fetch_ban_page(db: AsyncSession, page: int) -> tuple[list[tuple[str, str]], bool, bool]:
    offset = max(page - 1, 0) * BAN_PAGE_SIZE
    q = (
        select(BanMessageText.id, BanMessageText.text_message)
        .order_by(desc(BanMessageText.created_at), BanMessageText.id)
        .limit(BAN_PAGE_SIZE + 1)
        .offset(offset)
    )
    rows = (await db.execute(q)).all()
    has_next = len(rows) > BAN_PAGE_SIZE
    rows = rows[:BAN_PAGE_SIZE]
    has_prev = page > 1
    items = [(str(r[0]), _shorten(r[1], 60)) for r in rows]
    return items, has_prev, has_next


# === /admin ===
@admin_router.message(Command("admin"))
async def admin_entry(message: Message):
    await message.answer("Админ‑панель:", reply_markup=admin_main_menu())



# === Files list helpers ===
async def _fetch_files_page(db: AsyncSession, page: int) -> tuple[list[tuple[str, str]], bool, bool]:
    """
    Возвращает:
      - items: list[(file_token_md5, label_text)]
      - has_prev
      - has_next
    Порядок — по убыванию количества скачиваний.
    """
    offset = max(page - 1, 0) * FILES_PAGE_SIZE

    # distinct file_name with counts
    sub = (
        select(
            ReceivedGift.file_name.label("fn"),
            func.count().label("cnt"),
        )
        .group_by(ReceivedGift.file_name)
        .order_by(desc("cnt"), "fn")
        .limit(FILES_PAGE_SIZE + 1)  # на один больше, чтобы понять has_next
        .offset(offset)
        .subquery()
    )

    rows = (await db.execute(select(sub.c.fn, sub.c.cnt).order_by(desc(sub.c.cnt), sub.c.fn))).all()

    has_next = len(rows) > FILES_PAGE_SIZE
    rows = rows[:FILES_PAGE_SIZE]
    has_prev = page > 1

    items: list[tuple[str, str]] = []
    for fn, cnt in rows:
        token = hashlib.md5(fn.encode("utf-8")).hexdigest()
        # короткая подпись кнопки, чтобы не разъезжалась
        short = (fn[:40] + "…") if len(fn) > 41 else fn
        label = f"📄 {short}"
        items.append((token, label))
    return items, has_prev, has_next


# === Callbacks ===
#
# @admin_router.callback_query(F.data.startswith("adm:"))
# async def cb_any_admin(call: CallbackQuery):
#     print("DBG adm-callback:", call.data)
#     await call.answer()

@admin_router.callback_query(AdminCallback.filter(F.section == "menu"))
async def cb_menu_root(call: CallbackQuery, callback_data: AdminCallback):
    await call.message.edit_text("Админ‑панель:", reply_markup=admin_main_menu())
    await call.answer()


# Открытие списка файлов из главного меню (всегда страница 1)
@admin_router.callback_query(AdminCallback.filter((F.section == "stats") & (F.action == "open")))
@async_connect_db(commit=False)
async def cb_stats_open(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    page = 1
    items, has_prev, has_next = await _fetch_files_page(db, page)
    kb = build_files_menu(items, page, has_prev, has_next)
    await call.message.edit_text("📥 Выбери файл для просмотра статистики:", reply_markup=kb)
    await call.answer()


# Пагинация по списку файлов
@admin_router.callback_query(AdminCallback.filter((F.section == "stats") & (F.action == "files_page")))
@async_connect_db(commit=False)
async def cb_stats_files_page(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    page = max(callback_data.page or 1, 1)
    items, has_prev, has_next = await _fetch_files_page(db, page)
    kb = build_files_menu(items, page, has_prev, has_next)
    await call.message.edit_text("📥 Выбери файл для просмотра статистики:", reply_markup=kb)
    await call.answer()


@admin_router.callback_query(AdminCallback.filter((F.section == "stats") & (F.action == "pick_file")))
@async_connect_db(commit=False)
async def cb_stats_pick_file(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    logger.debug("pick_file hit: file=%s", callback_data.file)
    file_token = callback_data.file
    if not file_token:
        await call.answer("Не получилось определить файл", show_alert=True)
        return

    # Получим человекочитаемое имя файла (по токену)
    row = await db.execute(
        select(ReceivedGift.file_name)
        .where(func.md5(ReceivedGift.file_name) == file_token)
        .limit(1)
    )
    found = row.scalar_one_or_none()
    if not found:
        await call.answer("Файл не найден", show_alert=True)
        return

    # Стартовый период — 7 дней
    period: Period = "7d"
    start, end = _period_bounds(period)

    all_total, all_unique = await _stats_for_period(db, file_token=file_token)
    total, unique_users = await _stats_for_period(db, start, end, file_token=file_token)

    labels = {"today": "Сегодня", "7d": "Последние 7 дней", "30d": "Последние 30 дней"}
    text = _format_stats_text(labels[period], total, unique_users, all_total, all_unique, found)

    await call.message.edit_text(text, reply_markup=stats_period_menu(selected=period, file_token=file_token))
    await call.answer()


@admin_router.callback_query(AdminCallback.filter((F.section == "stats") & (F.action == "period")))
@async_connect_db(commit=False)
async def cb_stats_period(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    logger.debug("pick_file hit: file=%s", callback_data.file)
    file_token = callback_data.file
    if not file_token:
        await call.answer("Не выбран файл", show_alert=True)
        return

    # Человекочитаемое имя
    row = await db.execute(
        select(ReceivedGift.file_name)
        .where(func.md5(ReceivedGift.file_name) == file_token)
        .limit(1)
    )
    file_name = row.scalar_one_or_none() or "?"

    period: Period = callback_data.period if callback_data.period in ("today", "7d", "30d") else "7d"
    start, end = _period_bounds(period)

    all_total, all_unique = await _stats_for_period(db, file_token=file_token)
    total, unique_users = await _stats_for_period(db, start, end, file_token=file_token)

    labels = {"today": "Сегодня", "7d": "Последние 7 дней", "30d": "Последние 30 дней"}

    text = _format_stats_text(labels[period], total, unique_users, all_total, all_unique, file_name)
    await call.message.edit_text(text, reply_markup=stats_period_menu(selected=period, file_token=file_token))
    await call.answer()


@admin_router.callback_query(AdminCallback.filter((F.section == "stats") & (F.action == "back")))
@async_connect_db(commit=False)
async def cb_stats_back_to_files(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    # вернуть список файлов на 1-й странице
    items, has_prev, has_next = await _fetch_files_page(db, page=1)
    kb = build_files_menu(items, 1, has_prev, has_next)
    await call.message.edit_text("📥 Выбери файл для просмотра статистики:", reply_markup=kb)
    await call.answer()


# --- Открытие корневого меню бана ---

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "open")))
async def cb_ban_open(call: CallbackQuery):
    await call.message.edit_text("🚫 <b>Чёрный список сообщений</b>\nВыбери действие:", reply_markup=ban_root_menu())
    await call.answer()

# --- Добавление ---

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "add")))
async def cb_ban_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(BanStates.waiting_text)
    await call.message.edit_text(
        "Введи (или перешли) текст, который нужно занести в бан.\n\n"
        "Нормализация: без регистра, без пунктуации/пробелов/диакритики.\n"
        "Чтобы отменить — вернись в меню.",
        reply_markup=ban_root_menu()
    )
    await call.answer()

@admin_router.message(BanStates.waiting_text)
@async_connect_db(commit=True)
async def msg_ban_add(message: Message, state: FSMContext, db: AsyncSession):
    raw = (message.text or message.caption or "").strip()
    if not raw:
        await message.answer("Пустой текст не принимаю. Введи текст или вернись в меню.")
        return

    n = normalize_message_text(raw)
    h = norm_hash(n)

    # проверка на дубликат
    exists = await db.execute(select(BanMessageText.id).where(BanMessageText.normalized_hash == h))
    if exists.scalar_one_or_none():
        await message.answer("Такой (по смыслу) текст уже в бане ✅", reply_markup=ban_root_menu())
        await state.clear()
        return

    db.add(BanMessageText(text_message=raw, normalized_text=n, normalized_hash=h))
    try:
        # commit=True из декоратора
        await message.answer("Готово! Текст добавлен в бан ✅", reply_markup=ban_root_menu())
    except IntegrityError:
        await message.answer("Похоже, этот текст уже есть в бане (конкурентная проверка).", reply_markup=ban_root_menu())
    finally:
        await state.clear()

# --- Просмотр списка ---

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "list")))
@async_connect_db(commit=False)
async def cb_ban_list(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    page = max(callback_data.page or 1, 1)
    items, has_prev, has_next = await _fetch_ban_page(db, page)
    kb = build_ban_list(items, page, has_prev, has_next, mode="view")
    await call.message.edit_text("📜 <b>Список забаненных текстов</b>:", reply_markup=kb)
    await call.answer()

# --- Удаление: список ---

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "del_list")))
@async_connect_db(commit=False)
async def cb_ban_del_list(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    page = max(callback_data.page or 1, 1)
    items, has_prev, has_next = await _fetch_ban_page(db, page)
    if not items:
        await call.message.edit_text("Список пуст. Нечего удалять.", reply_markup=ban_root_menu())
        await call.answer()
        return
    kb = build_ban_list(items, page, has_prev, has_next, mode="delete")
    await call.message.edit_text("🗑️ Выбери текст для удаления:", reply_markup=kb)
    await call.answer()

# --- Удаление: подтверждение ---

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "del_pick")))
@async_connect_db(commit=False)
async def cb_ban_del_pick(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    ban_id = callback_data.ban_id
    if not ban_id:
        await call.answer("Не удалось определить запись", show_alert=True)
        return
    row = await db.execute(select(BanMessageText.text_message).where(BanMessageText.id == ban_id))
    text = row.scalar_one_or_none()
    if text is None:
        await call.answer("Запись уже удалена.", show_alert=True)
        return
    await call.message.edit_text(f"Удалить запись?\n\n<i>{_shorten(text, 200)}</i>",
                                 reply_markup=confirm_delete_menu(ban_id, page=callback_data.page or 1))
    await call.answer()

@admin_router.callback_query(AdminCallback.filter((F.section == "ban") & (F.action == "del_confirm")))
@async_connect_db(commit=True)
async def cb_ban_del_confirm(call: CallbackQuery, callback_data: AdminCallback, db: AsyncSession):
    ban_id = callback_data.ban_id
    if not ban_id:
        await call.answer("Не удалось определить запись", show_alert=True)
        return
    await db.execute(
        # удаляем по id
        BanMessageText.__table__.delete().where(BanMessageText.id == ban_id)
    )
    await call.answer("Удалено ✅", show_alert=False)
    # Вернёмся к списку той же страницы
    page = callback_data.page or 1
    items, has_prev, has_next = await _fetch_ban_page(db, page)
    kb = build_ban_list(items, page, has_prev, has_next, mode="delete")
    await call.message.edit_text("🗑️ Выбери текст для удаления:", reply_markup=kb)
