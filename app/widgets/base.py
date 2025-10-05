# app/widgets/base.py

import math
import queue
from threading import Thread, Event
import cv2
import time
from PIL import Image, ImageDraw
from datetime import date, datetime, timedelta

from app.core.constants import RU_MONTHS, RU_WD, COLOR_BG, COLOR_SUB, COLOR_ALERT, COLOR_OK, CLOCK_NORMAL, \
    CLOCK_WEEKEND, CLOCK_HOLIDAY, COLOR_TEXT, COLOR_CELL, COLOR_WEEKEND, COLOR_HOLIDAY, COLOR_TODAY, COLOR_GRID
from app.ui.text import FONT24, FONT32, draw_wrapped_text
import numpy as np
import requests


class WidgetBase(Thread):
    def __init__(self, camera_id: str, ui_queue: "queue.Queue", stop_event: Event):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.ui_queue = ui_queue
        self.stop_event = stop_event

    def push_frame(self, img: np.ndarray):
        try:
            self.ui_queue.put_nowait((self.camera_id, img))
        except queue.Full:
            pass


class CalClockWidget(Thread):
    API_BASE = "https://calendar.kuzyak.in/api/calendar"

    def __init__(self, camera_id: str, ui_queue: "queue.Queue", stop_event: Event):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.ui_queue = ui_queue
        self.stop_event = stop_event
        self._holidays_cache = {}  # {date: "name"}
        self._last_fetch = 0

    def push(self, frame: np.ndarray):
        try:
            self.ui_queue.put_nowait((self.camera_id, frame))
        except queue.Full:
            pass

    def run(self):
        while not self.stop_event.is_set():
            now = datetime.now()
            # Обновлять праздники раз в 15 минут
            if time.time() - self._last_fetch > 900:
                try:
                    self._refresh_holidays()
                except Exception:
                    # молча пропускаем, оставим кэш
                    pass
            frame = self.render(now, W=1280, H=720)  # 16:9 холст
            self.push(frame)
            time.sleep(1)

    def _upcoming_holidays(self, today: date, horizon_days: int = 14) -> list[tuple[date, str]]:
        horizon = today + timedelta(days=horizon_days)
        items = [(d, name) for d, name in self._holidays_cache.items() if today <= d <= horizon]
        items.sort(key=lambda x: x[0])
        return items

    def _refresh_holidays(self):
        today = date.today()
        months = [(today.year, today.month)]
        if today.month == 12:
            months.append((today.year + 1, 1))
        else:
            months.append((today.year, today.month + 1))

        # Сброс кэша только по целевым месяцам (на случай перехода месяца)
        self._holidays_cache = {}
        years = {y for y, _ in months}
        for y in years:
            url = f"{self.API_BASE}/{y}/holidays"
            r = requests.get(url, timeout=6)
            r.raise_for_status()
            data = r.json()
            for item in data:
                try:
                    d = datetime.strptime(item.get("date"), "%Y-%m-%d").date()
                    self._holidays_cache[d] = item.get("name", "Праздник")
                except Exception:
                    continue
        self._last_fetch = time.time()

    def _today_kind(self, today: date) -> str:
        """Возвращает 'holiday' | 'weekend' | 'normal'."""
        if today in self._holidays_cache:
            return "holiday"
        if today.weekday() in (5, 6):
            return "weekend"
        return "normal"

    # ---------- Рендер общего холста ----------
    def render(self, now: datetime, W=1280, H=720) -> np.ndarray:
        im = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(im)
        # Заголовок
        draw.text((30, 20), "Календарь и часы", fill=COLOR_SUB, font=FONT32 or FONT24)

        # Левая половина: 2 календаря (текущий + следующий)
        left_x, left_y = 30, 70
        left_w, left_h = W * 2 // 3 - 50, H - 90   # 2/3 ширины
        col_w = (left_w - 40) // 2
        today = now.date()
        first1 = today.replace(day=1)
        if first1.month == 12:
            first2 = date(first1.year + 1, 1, 1)
        else:
            first2 = date(first1.year, first1.month + 1, 1)

        self._draw_month(draw, left_x, left_y, col_w, left_h, first1, today)
        self._draw_month(draw, left_x + col_w + 40, left_y, col_w, left_h, first2, today)

        info_x = left_x
        info_top = left_y + left_h - 120  # отступаем вниз; при желании увеличь left_h или уменьшай -120
        info_w = left_w
        draw.rectangle([info_x, info_top - 10, info_x + info_w, info_top + 110], fill=(24,24,28))  # подложка блока

        upcoming = self._upcoming_holidays(today, horizon_days=14)
        if upcoming:
            header = "Флаги должны висеть:"
            draw.text((info_x + 10, info_top), header, fill=COLOR_ALERT, font=FONT32 or FONT24)
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            text = "\n".join(lines)
            draw_wrapped_text(draw, (info_x + 10, info_top + 40), text, max_width=info_w - 20, line_height=28,
                              font=FONT24)
        else:
            header = "В ближайшие 14 дней флаги вешать не надо."
            draw.text((info_x + 10, info_top), header, fill=COLOR_OK, font=FONT32 or FONT24)

        # Правая колонка: аналоговые часы + цифровое время
        # ---- Правая колонка: часы ----
        right_x = left_x + left_w + 20
        right_y = left_y
        right_w = W - right_x - 30
        right_h = left_h

        kind = self._today_kind(today)
        face_fill = CLOCK_NORMAL if kind == "normal" else (CLOCK_WEEKEND if kind == "weekend" else CLOCK_HOLIDAY)

        # рисуем циферблат и ПРИКЛЕИВАЕМ цифровые часы к его НИЗУ
        clock_pil = self._draw_analog_clock(right_w, right_h - 110, now, face_fill=face_fill)
        im.paste(clock_pil, (right_x, right_y))

        # вычислим точку под циферблатом по фактической высоте clock_pil
        clk_h = clock_pil.height
        base_y = right_y + clk_h + 12  # 12px отступ под циферблатом

        tstr = now.strftime("%H:%M:%S")
        dstr = now.strftime("%d.%m.%Y")
        t_w = draw.textlength(tstr, font=FONT32 or FONT24)
        d_w = draw.textlength(dstr, font=FONT24)
        tx = right_x + (right_w - t_w) / 2
        dx = right_x + (right_w - d_w) / 2
        draw.text((tx, base_y), tstr, fill=COLOR_TEXT, font=FONT32 or FONT24)
        draw.text((dx, base_y + 34), dstr, fill=(200, 200, 200), font=FONT24)

        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    # ---------- Рисуем один месяц ----------
    def _draw_month(self, draw: ImageDraw.ImageDraw, x, y, w, h, first_day: date, today: date):
        # Заголовок месяца
        draw.text((x, y), f"{RU_MONTHS[first_day.month]} {first_day.year}", fill=COLOR_SUB, font=FONT32 or FONT24)
        y += 36

        # Дни недели
        cell_w = w // 7
        # 1 строка заголовка + максимум 6 недель = 7 строк
        cell_h = (h - 36) // 7
        for i, wd in enumerate(RU_WD):
            draw.text((x + i*cell_w + 8, y), wd, fill=(180,180,180), font=FONT24)
        y += 26

        # На какой день недели начинается месяц (Mon=0..Sun=6)
        offset = first_day.weekday()
        cursor_x = x + offset * cell_w
        cursor_y = y + 8

        # Кол-во дней в месяце
        if first_day.month == 12:
            next_month = date(first_day.year+1, 1, 1)
        else:
            next_month = date(first_day.year, first_day.month+1, 1)
        days_in_month = (next_month - first_day).days

        for dnum in range(1, days_in_month+1):
            cur = date(first_day.year, first_day.month, dnum)
            wd = cur.weekday()  # 0..6, где 5=Сб, 6=Вс
            # Базовый цвет ячейки
            fill = COLOR_CELL
            # Выходной?
            if wd in (5, 6):
                fill = COLOR_WEEKEND
            # Праздник перекрывает выходной
            if cur in self._holidays_cache:
                fill = COLOR_HOLIDAY
            # Сегодня — поверх подложки
            if cur == today:
                fill = COLOR_TODAY

            # Рисуем клетку
            draw.rectangle([cursor_x+1, cursor_y-6, cursor_x + cell_w - 6, cursor_y + cell_h - 10],
                           outline=COLOR_GRID, width=1, fill=fill)
            # Число + если праздник — маленькая точка/иконка
            draw.text((cursor_x+8, cursor_y), str(dnum), fill=COLOR_TEXT, font=FONT24)
            if cur in self._holidays_cache:
                draw.ellipse([cursor_x + cell_w - 24, cursor_y + 4, cursor_x + cell_w - 10, cursor_y + 18],
                             fill=(220, 80, 80))

            # перенос
            offset += 1
            if offset >= 7:
                offset = 0
                cursor_x = x
                cursor_y += cell_h
            else:
                cursor_x += cell_w

    # ---------- Аналоговые часы ----------
    def _draw_analog_clock(self, W, H, now: datetime, face_fill=CLOCK_NORMAL) -> Image.Image:
        # квадрат под циферблат
        S = min(W, H)
        cx, cy = S // 2, S // 2
        r = int(S * 0.42)

        im = Image.new("RGB", (W, H), COLOR_BG)
        d = ImageDraw.Draw(im)

        # фон циферблата
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=(100, 100, 110), width=4, fill=face_fill)

        # риски (минутные/часовые)
        for i in range(60):
            angle = (i / 60.0) * 2.0 * math.pi
            outer = (cx + int(r * math.sin(angle)),
                     cy - int(r * math.cos(angle)))
            inner_len = 12 if i % 5 else 20
            inner = (cx + int((r - inner_len) * math.sin(angle)),
                     cy - int((r - inner_len) * math.cos(angle)))
            d.line([inner, outer],
                   fill=(170, 170, 180) if i % 5 == 0 else (110, 110, 120),
                   width=2 if i % 5 == 0 else 1)

        # цифры 1..12
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

        # центр
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(200, 60, 60))
        return im
