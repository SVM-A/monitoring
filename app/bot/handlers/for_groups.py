# bot/handlers/for_groups.py
import hashlib
import re
import html
import unicodedata
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio.session import AsyncSession

from app.core.config import public_channel_comment_chat_id, elya_chat_id, public_channel_chat_id
from app.db.models.service_notifier import BanMessageText, norm_hash, normalize_message_text
from app.db.sessions import async_connect_db
from bot.utils.tools import normalize_message

groups_monitor_router = Router()

# ─────────────────────[ БЕЛЫЙ СПИСОК СВОИХ БОТОВ ]─────────────────────
ALLOWLIST_BOTS = {"beaheabot"}  # все в нижнем регистре

# ─────────────────────[ РЕГУЛЯРКИ ДЛЯ ЛОВЛИ @handle / ссылок ]────────
MENTION_RE = re.compile(r"(?<!\w)@(?P<u>[A-Za-z0-9_]{5,32})(?!\w)")

LINK_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:t(?:elegram)?\.me|telegram\.me)/(?:s/)?(?P<u>[A-Za-z0-9_]{5,32})(?:\b|/|\?|#)"
)
TG_RESOLVE_RE = re.compile(r"(?i)\btg://resolve\?domain=(?P<u>[A-Za-z0-9_]{5,32})\b")

def _extract_usernames(text: str) -> set[str]:
    """Достаём кандидатов на username из упоминаний и ссылок."""
    if not text:
        return set()
    usernames = set()
    for rx in (MENTION_RE, LINK_RE, TG_RESOLVE_RE):
        for m in rx.finditer(text):
            usernames.add(m.group("u"))
    return usernames

def _is_foreign_bot(username: str) -> bool:
    """Считаем username ботом, если оканчивается на 'bot' (регистронезависимо) и не в allowlist."""
    u = username.lower()
    return u.endswith("bot") and u not in ALLOWLIST_BOTS


# Защита от спама

SPAM_MARKERS_RAW = [
    "онлайн обучение", "курс", "обучение по трейдингу", "трейдинг",
    "кому нужно пишите", "перешлю", "за спасибо", "символическую плату",
    "слив", "сбросил мне", "давай посмотрю", "материал не представляет ценности"
]
SPAM_MARKERS = { normalize_message_text(x) for x in SPAM_MARKERS_RAW }

def keyword_score(norm: str) -> int:
    return sum(1 for k in SPAM_MARKERS if k in norm)

def looks_like_course_leak(norm: str) -> bool:
    # Обычно 3–4 маркера дают хорошую точность.
    return keyword_score(norm) >= 3


def normalize_for_regex(raw: str) -> str:
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # заменяем всё, что не буквы/цифры, на пробел и схлопываем пробелы
    s = re.sub(r"[^0-9a-zA-Zа-яёА-ЯЁ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

REGEXES = [
    re.compile(r"(онлайн|какой[-\s]?ни(будь|ка)|лучше)\s+(курс|обучени[ея])"),
    re.compile(r"(перешл[ью]|дам\s+доступ|поделюсь)\b"),
    re.compile(r"\b(за|ради)\s+(спасибо|донат|символическ\w*\s+плат\w*)"),
    re.compile(r"(кому|если)\s+(нужно|интересно)\s+(пишите|в\s+лс|в\s+личк\w*)"),
]

def rules_hit(raw: str) -> bool:
    s = normalize_for_regex(raw)
    return sum(1 for rx in REGEXES if rx.search(s)) >= 2


async def is_similar_banned(db, norm: str, threshold: float = 0.68) -> bool:
    await db.execute(text("SET pg_trgm.similarity_threshold = :t"), {"t": threshold})
    row = (await db.execute(
        text("""SELECT id FROM ban_messages
                WHERE normalized_text % :norm
                ORDER BY similarity(normalized_text, :norm) DESC
                LIMIT 1"""),
        {"norm": norm}
    )).first()
    return row is not None


def simhash64(norm: str) -> int:
    from collections import Counter
    v = [0]*64
    shingles = [norm[i:i+3] for i in range(max(1,len(norm)-2))]
    for sh, w in Counter(shingles).items():
        h = hashlib.md5(sh.encode()).digest()  # ок, тут md5 как источник бит
        x = int.from_bytes(h[:8], "big")
        for i in range(64):
            v[i] += w if (x >> i) & 1 else -w
    out = 0
    for i in range(64):
        if v[i] > 0: out |= (1 << i)
    return out

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def markers_in_text(norm: str) -> list[str]:
    """Какие маркеры реально встретились в тексте (по нормализованной версии)."""
    return [k for k in SPAM_MARKERS if k in norm]

def regex_hits_list(raw: str) -> list[str]:
    """Какие регэкспы сработали (по «нижнему регистру + пробелам» версии)."""
    s = normalize_for_regex(raw)
    return [rx.pattern for rx in REGEXES if rx.search(s)]

@groups_monitor_router.message(F.chat.id == public_channel_comment_chat_id())
@async_connect_db(commit=False)
async def monitor_comments_for_ban(message: Message, bot: Bot, *, db: AsyncSession):
    user = message.from_user
    src_text = (message.text or message.caption or "").strip()

    # 0) Достаём упоминания/ссылки на ботов
    usernames = _extract_usernames(src_text)
    foreign_bots = {u for u in usernames if _is_foreign_bot(u)}
    has_foreign_bot = bool(foreign_bots)

    # 1) Точная проверка по нормализации/хэшу
    norm = normalize_message_text(src_text)
    is_banned_text = False
    if norm:
        h = norm_hash(norm)
        res = await db.execute(
            select(BanMessageText.id).where(BanMessageText.normalized_hash == h).limit(1)
        )
        is_banned_text = res.scalar_one_or_none() is not None

    # 2) Правила (маркеры/регэкспы)
    markers = markers_in_text(norm) if norm else []
    rx_hits = regex_hits_list(src_text) if src_text else []
    rules_flag = (len(markers) >= 3) or (len(rx_hits) >= 2)

    # 3) Похожесть (pg_trgm) — только если не сработали пункты (1) и (2),
    #    и текст достаточно длинный (чтобы не «стреляло» на коротких фразах)
    similar_hit = False
    trigram_threshold = 0.66
    if norm and not is_banned_text and not rules_flag and len(norm) >= 60:
        similar_hit = await is_similar_banned(db, norm, threshold=trigram_threshold)

    # Итоговое решение
    should_ban = has_foreign_bot or is_banned_text or rules_flag or similar_hit

    if not should_ban:
        return  # ничего не делаем

    # Пытаемся удалить сообщение и забанить пользователя и в комментах, и в канале
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    try:
        await bot.ban_chat_member(chat_id=public_channel_comment_chat_id(), user_id=user.id)
    except TelegramBadRequest:
        pass
    try:
        await bot.ban_chat_member(chat_id=public_channel_chat_id(), user_id=user.id)
    except TelegramBadRequest:
        pass

    # Готовим объяснимое уведомление (почему забанили)
    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    reason_lines = []
    if foreign_bots:
        reason_lines.append(
            "Причина: ссылка/упоминание бота(ов): " + ", ".join(f"@{u}" for u in sorted(foreign_bots))
        )
    if is_banned_text:
        reason_lines.append("Причина: точное совпадение с запрещённой фразой (normalized_hash).")
    if rules_flag:
        reason_lines.append(
            f"Причина: маркеры/регэкспы (маркеров: {len(markers)}, регэкспов: {len(rx_hits)})."
        )
        if markers:
            # Покажем до 6 маркеров, чтобы не раздувать уведомление
            reason_lines.append("Маркеры: " + ", ".join(sorted(markers)[:6]) + ("…" if len(markers) > 6 else ""))
        if rx_hits:
            # Покажем до 3 паттернов
            reason_lines.append("Regex: " + " | ".join(rx_hits[:3]) + ("…" if len(rx_hits) > 3 else ""))
    if similar_hit:
        reason_lines.append(f"Причина: похожесть с базой (pg_trgm ≥ {trigram_threshold}).")

    safe_text = html.escape(src_text) or "—"
    full_name = html.escape(getattr(user, "full_name", "") or "—")
    username = ("@" + user.username) if getattr(user, "username", None) else "—"
    lang = getattr(user, "language_code", None) or "—"
    is_premium = "да" if getattr(user, "is_premium", False) else "нет"

    notify = (
        "<b>🚨 Бан в комментариях</b>\n"
        f"<b>Когда:</b> {when}\n"
        f"<b>Кто:</b> {full_name}\n"
        f"<b>Username:</b> {html.escape(username)}\n"
        f"<b>ID:</b> <code>{user.id}</code>\n"
        f"<b>Premium:</b> {is_premium}\n"
        f"<b>Язык:</b> {lang}\n"
        f"<b>Текст:</b>\n<pre>{safe_text}</pre>\n"
        + ("\n".join(reason_lines) if reason_lines else "")
    )
    await bot.send_message(chat_id=elya_chat_id(), text=notify, parse_mode="HTML")