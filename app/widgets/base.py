# app/widgets/base.py

import math
import queue
import time
from datetime import date, datetime, timedelta
from threading import Thread, Event
from typing import Any, Optional

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw

from app.core.constants import (
    RU_MONTHS,
    RU_WD,
    COLOR_BG,
    COLOR_SUB,
    COLOR_ALERT,
    COLOR_OK,
    COLOR_TEXT,
    COLOR_CELL,
    COLOR_WEEKEND,
    COLOR_HOLIDAY,
    COLOR_TODAY,
    COLOR_GRID,
    CLOCK_NORMAL,
    CLOCK_WEEKEND,
    CLOCK_HOLIDAY,
)
from app.ui.text import FONT24, FONT32, draw_wrapped_text


class WidgetBase(Thread):
    """
    Базовый класс для всех виджетов.

    Даёт:
      - потоковую обёртку и безопасную отправку кадров в UI-очередь;
      - компактный цикл `run_loop()` для периодического рендера;
      - HTTP-загрузку с простым кэшированием по TTL (для календаря/праздников);
      - общие хелперы рендера (месяц, аналоговые часы, тип дня, список ближайших праздников).
    """

    # Единая база API для всех календарных виджетов
    API_BASE = "https://calendar.kuzyak.in/api/calendar"

    def __init__(self, camera_id: str, ui_queue: "queue.Queue", stop_event: Event):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.ui_queue = ui_queue
        self.stop_event = stop_event

        # Кэши для сетевых данных
        self._json_cache: dict[str, Any] = {}
        self._json_cache_ttl: dict[str, float] = {}

        # Кэш по праздникам в разрезе дат
        self._holidays_by_date: dict[date, str] = {}
        self._holidays_last_fetch: float = 0.0

    # ---------------------- Поток/очередь ----------------------
    def push_frame(self, img: np.ndarray) -> None:
        """Неблокирующая отправка кадра в UI-очередь."""
        try:
            self.ui_queue.put_nowait((self.camera_id, img))
        except queue.Full:
            pass

    def run_loop(self, render_fn, tick_seconds: float = 1.0) -> None:
        """
        Унифицированный цикл выполнения:
        `render_fn()` должен вернуть готовый кадр (np.ndarray), который будет отправлен в UI.
        """
        while not self.stop_event.is_set():
            try:
                frame = render_fn()
                if frame is not None:
                    self.push_frame(frame)
            except Exception:
                # мягко переживаем исключения внутри рендера
                pass
            finally:
                time.sleep(max(0.0, float(tick_seconds)))

    # ---------------------- HTTP / JSON с TTL ----------------------
    def fetch_json_cached(self, url: str, ttl: float = 900.0, timeout: float = 6.0) -> Any:
        """Загружает JSON с кэшированием на TTL секунд."""
        now = time.time()
        if (exp := self._json_cache_ttl.get(url)) and exp > now:
            return self._json_cache.get(url)
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        self._json_cache[url] = data
        self._json_cache_ttl[url] = now + ttl
        return data

    # ---------------------- Праздники ----------------------
    def refresh_holidays_if_needed(self, ttl: float = 900.0) -> None:
        now = time.time()
        if now - self._holidays_last_fetch < ttl:
            return
        today = date.today()
        horizon = today + timedelta(days=60)  # запасом на 2 месяца
        years = sorted({today.year, horizon.year})
        by_date: dict[date, str] = {}
        for y in years:
            url = f"{self.API_BASE}/{y}/holidays"
            try:
                data = self.fetch_json_cached(url, ttl=ttl)
            except Exception:
                continue
            for item in data or []:
                try:
                    d = datetime.strptime(item.get("date"), "%Y-%m-%d").date()
                    by_date[d] = item.get("name", "Праздник")
                except Exception:
                    continue
        self._holidays_by_date = by_date
        self._holidays_last_fetch = now

    def today_kind(self, day: date) -> str:
        if day in self._holidays_by_date:
            return "holiday"
        if day.weekday() in (5, 6):
            return "weekend"
        return "normal"

    def upcoming_holidays(self, start: date, horizon_days: int = 14) -> list[tuple[date, str]]:
        end = start + timedelta(days=horizon_days)
        items = [(d, name) for d, name in self._holidays_by_date.items() if start <= d <= end]
        items.sort(key=lambda x: x[0])
        return items

    # ---------------------- Рендер-хелперы ----------------------
    def draw_month(self, draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                   first_day: date, today: date) -> None:
        draw.text((x, y), f"{RU_MONTHS[first_day.month]} {first_day.year}", fill=COLOR_SUB, font=FONT32 or FONT24)
        y += 36
        cell_w = w // 7
        cell_h = (h - 36) // 7  # 1 строка заголовка + до 6 недель
        for i, wd in enumerate(RU_WD):
            draw.text((x + i * cell_w + 8, y), wd, fill=(180, 180, 180), font=FONT24)
        y += 26
        offset = first_day.weekday()  # Mon=0..Sun=6
        cursor_x = x + offset * cell_w
        cursor_y = y + 8
        if first_day.month == 12:
            next_month = date(first_day.year + 1, 1, 1)
        else:
            next_month = date(first_day.year, first_day.month + 1, 1)
        days_in_month = (next_month - first_day).days
        for dnum in range(1, days_in_month + 1):
            cur = date(first_day.year, first_day.month, dnum)
            wd = cur.weekday()
            fill = COLOR_CELL
            if wd in (5, 6):
                fill = COLOR_WEEKEND
            if cur in self._holidays_by_date:
                fill = COLOR_HOLIDAY
            if cur == today:
                fill = COLOR_TODAY
            draw.rectangle([cursor_x + 1, cursor_y - 6, cursor_x + cell_w - 6, cursor_y + cell_h - 10],
                           outline=COLOR_GRID, width=1, fill=fill)
            draw.text((cursor_x + 8, cursor_y), str(dnum), fill=COLOR_TEXT, font=FONT24)
            if cur in self._holidays_by_date:
                draw.ellipse([cursor_x + cell_w - 24, cursor_y + 4, cursor_x + cell_w - 10, cursor_y + 18],
                             fill=(220, 80, 80))
            offset += 1
            if offset >= 7:
                offset = 0
                cursor_x = x
                cursor_y += cell_h
            else:
                cursor_x += cell_w

    def draw_analog_clock(self, W: int, H: int, now: datetime) -> Image.Image:
        """Рисует квадратный циферблат в прямоугольнике WxH и возвращает PIL.Image."""
        kind = self.today_kind(now.date())
        face_fill = CLOCK_NORMAL if kind == "normal" else (CLOCK_WEEKEND if kind == "weekend" else CLOCK_HOLIDAY)
        S = min(W, H)
        cx, cy = S // 2, S // 2
        r = int(S * 0.42)
        im = Image.new("RGB", (W, H), COLOR_BG)
        d = ImageDraw.Draw(im)
        # фон
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(100, 100, 110), width=4, fill=face_fill)
        # риски
        for i in range(60):
            angle = (i / 60.0) * 2.0 * math.pi
            outer = (cx + int(r * math.sin(angle)), cy - int(r * math.cos(angle)))
            inner_len = 12 if i % 5 else 20
            inner = (cx + int((r - inner_len) * math.sin(angle)), cy - int((r - inner_len) * math.cos(angle)))
            d.line([inner, outer], fill=(170, 170, 180) if i % 5 == 0 else (110, 110, 120),
                   width=2 if i % 5 == 0 else 1)
        # цифры
        for n in range(1, 13):
            angle = (n / 12.0) * 2.0 * math.pi
            tx = cx + int((r - 30) * math.sin(angle))
            ty = cy - int((r - 30) * math.cos(angle))
            text = str(n)
            tw = d.textlength(text, font=FONT24)
            th = 24
            d.text((tx - tw / 2, ty - th / 2), text, fill=COLOR_TEXT, font=FONT24)
        # стрелки
        sec = now.second + now.microsecond / 1e6
        minu = now.minute + sec / 60.0
        hour = (now.hour % 12) + minu / 60.0

        def hand(angle_ratio, length, width, color):
            ang = angle_ratio * 2.0 * math.pi
            x2 = cx + int(length * math.sin(ang))
            y2 = cy - int(length * math.cos(ang))
            d.line([(cx, cy), (x2, y2)], fill=color, width=width)

        hand(hour / 12.0, int(r * 0.55), 6, (230, 230, 235))
        hand(minu / 60.0, int(r * 0.75), 4, (220, 220, 230))
        hand(sec / 60.0, int(r * 0.85), 2, (200, 60, 60))
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(200, 60, 60))
        return im

    # ---------------------- Композиции-панели ----------------------
    def render_calendar_two_months(self, now: Optional[datetime] = None,
                                   W: int = 1280, H: int = 720) -> np.ndarray:
        now = now or datetime.now()
        self.refresh_holidays_if_needed()
        im = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(im)
        today = now.date()
        # заголовок
        draw.text((30, 20), "Календарь", fill=COLOR_SUB, font=FONT32 or FONT24)
        # сетки 2 колонки
        left_x, top_y = 40, 80
        col_w = (W - left_x * 2 - 40) // 2
        left_h = H - top_y - 40
        first1 = today.replace(day=1)
        first2 = (date(first1.year + 1, 1, 1) if first1.month == 12 else
                  date(first1.year, first1.month + 1, 1))
        self.draw_month(draw, left_x, top_y, col_w, left_h, first1, today)
        self.draw_month(draw, left_x + col_w + 40, top_y, col_w, left_h, first2, today)
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    def render_holidays_box(self, now: Optional[datetime] = None,
                            W: int = 640, H: int = 360) -> np.ndarray:
        now = now or datetime.now()
        self.refresh_holidays_if_needed()
        im = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(im)
        draw.text((30, 30), "Праздники (14 дней)", fill=COLOR_SUB, font=FONT32 or FONT24)
        upcoming = self.upcoming_holidays(now.date(), horizon_days=14)
        if upcoming:
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            text = "В ближайшие дни флаги вывешиваются:\n" + "\n".join(lines)
        else:
            text = "В ближайшие 14 дней флаги вешать не надо."
        y = 90
        for line in text.split("\n"):
            draw.text((30, y), line, fill=COLOR_TEXT, font=FONT24)
            y += 32
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    def render_calendar_plus_clock(self, now: Optional[datetime] = None,
                                   W: int = 1280, H: int = 720) -> np.ndarray:
        now = now or datetime.now()
        self.refresh_holidays_if_needed()
        im = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(im)
        draw.text((30, 20), "Календарь и часы", fill=COLOR_SUB, font=FONT32 or FONT24)
        # Левая часть: 2 месяца + информер по флагам
        left_x, left_y = 30, 70
        left_w, left_h = W * 2 // 3 - 50, H - 90
        col_w = (left_w - 40) // 2
        today = now.date()
        first1 = today.replace(day=1)
        first2 = (date(first1.year + 1, 1, 1) if first1.month == 12 else
                  date(first1.year, first1.month + 1, 1))
        self.draw_month(draw, left_x, left_y, col_w, left_h, first1, today)
        self.draw_month(draw, left_x + col_w + 40, left_y, col_w, left_h, first2, today)
        # Информер по флагам
        info_x = left_x
        info_top = left_y + left_h - 120
        info_w = left_w
        draw.rectangle([info_x, info_top - 10, info_x + info_w, info_top + 110], fill=(24, 24, 28))
        upcoming = self.upcoming_holidays(today, horizon_days=14)
        if upcoming:
            header = "Флаги должны висеть:"
            draw.text((info_x + 10, info_top), header, fill=COLOR_ALERT, font=FONT32 or FONT24)
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            text = "\n".join(lines)
            draw_wrapped_text(draw, (info_x + 10, info_top + 40), text, max_width=info_w - 20,
                              line_height=28, font=FONT24)
        else:
            header = "В ближайшие 14 дней флаги вешать не надо."
            draw.text((info_x + 10, info_top), header, fill=COLOR_OK, font=FONT32 or FONT24)
        # Правая колонка: аналоговые часы + цифровые, ПРИКЛЕЕНЫЕ к циферблату
        right_x = left_x + left_w + 20
        right_y = left_y
        right_w = W - right_x - 30
        right_h = left_h
        clock_pil = self.draw_analog_clock(right_w, right_h - 110, now)
        im.paste(clock_pil, (right_x, right_y))
        clk_h = clock_pil.height
        base_y = right_y + clk_h + 12
        tstr = now.strftime("%H:%M:%S")
        dstr = now.strftime("%d.%m.%Y")
        t_w = draw.textlength(tstr, font=FONT32 or FONT24)
        d_w = draw.textlength(dstr, font=FONT24)
        tx = right_x + (right_w - t_w) / 2
        dx = right_x + (right_w - d_w) / 2
        draw.text((tx, base_y), tstr, fill=COLOR_TEXT, font=FONT32 or FONT24)
        draw.text((dx, base_y + 34), dstr, fill=(200, 200, 200), font=FONT24)
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    @staticmethod
    def render_digital_clock( now: Optional[datetime] = None,
                             W: int = 640, H: int = 360) -> np.ndarray:
        now = now or datetime.now()
        im = Image.new("RGB", (W, H), (15, 15, 18))
        draw = ImageDraw.Draw(im)
        t = now.strftime("%H:%M:%S")
        d = now.strftime("%d.%m.%Y")
        draw.text((30, 40), "Часы", fill=(200, 200, 255), font=FONT32 or FONT24)
        draw.text((30, 120), t, fill=(240, 240, 240), font=FONT32 or FONT24)
        draw.text((30, 180), d, fill=(200, 200, 200), font=FONT24)
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

