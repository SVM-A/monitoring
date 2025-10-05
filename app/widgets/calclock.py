# app/widgets/calclock.py

import cv2
import time
import numpy as np
import requests
from PIL import Image, ImageDraw
from datetime import date, datetime, timedelta

from app.core.constants import RU_MONTHS, RU_WD
from app.widgets.base import WidgetBase
from app.ui.text import FONT24, FONT32


class CalendarWidget(WidgetBase):
    def run(self):
        while not self.stop_event.is_set():
            img = self.render_calendar_panel()
            self.push_frame(img)
            # обновляем раз в 30 сек
            for _ in range(30):
                if self.stop_event.is_set(): break
                time.sleep(1)

    def render_calendar_panel(self, W=1280, H=720) -> np.ndarray:
        # холст PIL
        im = Image.new("RGB", (W, H), (20, 20, 20))
        draw = ImageDraw.Draw(im)
        today = date.today()
        # текущий и следующий месяцы
        months = [today.replace(day=1)]
        y, m = months[0].year, months[0].month
        if m == 12:
            months.append(date(y+1, 1, 1))
        else:
            months.append(date(y, m+1, 1))

        # заголовок
        title = f"Календарь: {RU_MONTHS[months[0].month]} {months[0].year}  •  {RU_MONTHS[months[1].month]} {months[1].year}"
        draw.text((30, 20), title, fill=(230,230,230), font=FONT32 or FONT24)

        # сетки 2 колонки
        grid_top = 80
        grid_left = 40
        col_w = (W - grid_left*2 - 40) // 2
        col_gap = 40
        for col, first in enumerate(months):
            x0 = grid_left + col * (col_w + col_gap)
            self._draw_month(draw, x0, grid_top, col_w, H - grid_top - 40, first, today)

        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    def _draw_month(self, draw: ImageDraw.ImageDraw, x, y, w, h, first_day: date, today: date):
        # шапка месяца
        draw.text((x, y), f"{RU_MONTHS[first_day.month]} {first_day.year}", fill=(200,200,255), font=FONT32 or FONT24)
        y += 36
        # дни недели
        cell_w = w // 7
        cell_h = (h - 36) // 7  # 1 строка заголовка + 6 недель максимум
        for i, wd in enumerate(RU_WD):
            draw.text((x + i*cell_w + 8, y), wd, fill=(180,180,180), font=FONT24)
        y += 26

        # первая неделя: определить смещение (понедельник=0)
        start_wd = (first_day.weekday())  # Mon=0
        d = first_day
        # дни предыдущего месяца не рисуем
        cursor_x = x + start_wd * cell_w
        cursor_y = y + 8
        # сколько дней в месяце
        if first_day.month == 12:
            next_month = date(first_day.year+1, 1, 1)
        else:
            next_month = date(first_day.year, first_day.month+1, 1)
        days_in_month = (next_month - first_day).days

        for i in range(1, days_in_month+1):
            is_today = (today.year == first_day.year and today.month == first_day.month and today.day == i)
            box_color = (60,60,60) if not is_today else (80,90,110)
            # прямоугольник дня
            draw.rectangle([cursor_x+1, cursor_y-6, cursor_x + cell_w - 6, cursor_y + cell_h - 10], outline=(80,80,80), width=1, fill=box_color)
            draw.text((cursor_x+8, cursor_y), str(i), fill=(240,240,240), font=FONT24)

            # перенос
            start_wd += 1
            if start_wd >= 7:
                start_wd = 0
                cursor_x = x
                cursor_y += cell_h
            else:
                cursor_x += cell_w


class ClockWidget(WidgetBase):
    def run(self):
        while not self.stop_event.is_set():
            now = datetime.now()
            img = self.render_clock(now)
            self.push_frame(img)
            # обновляем каждую секунду
            time.sleep(1)

    def render_clock(self, now: datetime, W=640, H=360) -> np.ndarray:
        im = Image.new("RGB", (W, H), (15, 15, 18))
        draw = ImageDraw.Draw(im)
        t = now.strftime("%H:%M:%S")
        d = now.strftime("%d.%m.%Y")
        draw.text((30, 40), "Часы", fill=(200,200,255), font=FONT32 or FONT24)
        draw.text((30, 120), t, fill=(240,240,240), font=FONT32 or FONT24)
        draw.text((30, 180), d, fill=(200,200,200), font=FONT24)
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


class HolidaysWidget(WidgetBase):
    API_BASE = "https://calendar.kuzyak.in/api/calendar"  # эндпоинты описаны в доке: год/месяц/праздники :contentReference[oaicite:2]{index=2}

    def run(self):
        last_fetch = 0
        cache_img = None
        while not self.stop_event.is_set():
            now = time.time()
            if now - last_fetch > 900:  # раз в 15 минут обновляем список праздников
                try:
                    cache_img = self.render_holidays_panel()
                    last_fetch = now
                except Exception as e:
                    # в случае ошибки — мягкий фолбэк
                    cache_img = self.render_text("Ошибка загрузки календаря.\nПроверю позже.")
                    last_fetch = now
            if cache_img is not None:
                self.push_frame(cache_img)
            time.sleep(1)

    def render_text(self, text: str, W=640, H=360) -> np.ndarray:
        im = Image.new("RGB", (W, H), (18, 18, 22))
        draw = ImageDraw.Draw(im)
        draw.text((30, 30), "Праздники (14 дней)", fill=(200,200,255), font=FONT32 or FONT24)
        # перенос строк
        y = 90
        for line in text.split("\n"):
            draw.text((30, y), line, fill=(230,230,230), font=FONT24)
            y += 32
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    def render_holidays_panel(self) -> np.ndarray:
        today = date.today()
        horizon = today + timedelta(days=14)

        # Берём праздники года. Эндпоинт: GET /api/calendar/{year}/holidays (см. доку) :contentReference[oaicite:3]{index=3}
        years = sorted({today.year, horizon.year})
        holidays = []  # (date, name)
        for y in years:
            url = f"{self.API_BASE}/{y}/holidays"
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            # Ожидаем, что в списке будут объекты с полями 'date' и 'name' (у API есть год/месяц/день/праздники) :contentReference[oaicite:4]{index=4}
            for item in data:
                try:
                    d = datetime.strptime(item.get("date"), "%Y-%m-%d").date()
                    if today <= d <= horizon:
                        holidays.append((d, item.get("name", "Праздничный день")))
                except Exception:
                    continue

        holidays.sort(key=lambda x: x[0])
        if holidays:
            lines = []
            for d, name in holidays:
                lines.append(f"{d.strftime('%d.%m')} — {name}")
            text = "В ближайшие дни флаги вывешиваются:\n" + "\n".join(lines)
        else:
            text = "В ближайшие 14 дней флаги вешать не надо."
        return self.render_text(text)


