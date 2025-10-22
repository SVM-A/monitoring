# app/widgets/base.py

import os
import math
import queue
import time
from datetime import date, datetime, timedelta
from threading import Thread, Event
from typing import Any, Optional

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

from app.core.constants import (
    RU_MONTHS,
    RU_MONTHS_SHORT,
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
    CLOCK_HOLIDAY, BADGE_TEXT, BADGE_BG, COLOR_TEMP, WX_ICON_RAIN_HEAVY, BADGE_RAIN_HIGH, WX_ICON_RAIN_LIGHT,
    BADGE_RAIN, WX_ICON_DRY, WX_ICON_WIND, BADGE_WIND,
)
from app.ui.design_system import DS
from app.ui.icons import get_icon
from app.ui.text import (
    FONT12, FONT14, FONT16, FONT18, FONT20, FONT22, FONT24, FONT28, FONT32,
    draw_wrapped_text, FONT40, FONT48
)


# ---- Погода: настройки по умолчанию ----
WEATHER_LAT = float(os.environ.get("WEATHER_LAT", 55.728462))   # Москва по умолчанию
WEATHER_LON = float(os.environ.get("WEATHER_LON", 37.647653))
WEATHER_TZ  = os.environ.get("WEATHER_TZ", "Europe/Moscow")

# Пороги для "аномалий"
WIND_ALERT_MS = float(os.environ.get("WIND_ALERT_MS", 12.0))     # ≥12 м/с — сильный ветер
RAIN_ALERT_MM = float(os.environ.get("RAIN_ALERT_MM", 8.0))      # ≥8 мм/сутки — заметные осадки


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
            tw = d.textlength(text, font=FONT32)  # было FONT24
            th = 32
            d.text(
                (tx - tw / 2, ty - th / 2),
                text,
                fill=COLOR_TEXT,
                font=FONT32,  # ↑ крупнее
                stroke_width=2, stroke_fill=(0, 0, 0)  # чёткая обводка
            )
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

    # === ОСНОВНОЙ РЕНДЕР 4 НЕДЕЛЬ ==========================================
    def draw_4weeks_with_weather(
            self,
            im: Image.Image,
            draw: ImageDraw.ImageDraw,
            x: int, y: int, w: int, h: int,
            start: date, today: date,
            wx: dict[date, dict]
    ) -> None:
        # Заголовок
        draw.text((x, y), "Ближайшие 4 недели (Пн–Вс)", fill=COLOR_SUB, font=FONT28)
        y += 38

        cell_w = w // 7
        head_h = 26
        for i, wd in enumerate(RU_WD):
            draw.text((x + i * cell_w + 8, y), wd, fill=(180, 180, 190), font=FONT16)
        y += head_h + 8

        rows = 4
        cell_h = (h - (38 + head_h + 8)) // rows
        pad = 10
        gap = 6

        cur = start
        for r in range(rows):
            for c in range(7):
                cx = x + c * cell_w
                cy = y + r * cell_h

                # фон
                kind = self.today_kind(cur)  # "weekday"|"weekend"|"holiday"
                fill = COLOR_CELL
                if kind == "weekend": fill = COLOR_WEEKEND
                if kind == "holiday": fill = COLOR_HOLIDAY
                if cur == today:      fill = COLOR_TODAY
                draw.rectangle([cx + 1, cy + 1, cx + cell_w - 6, cy + cell_h - 6],
                               outline=COLOR_GRID, width=1, fill=fill)

                # внутренности
                ix, iy = cx + pad, cy + pad
                iw, ih = cell_w - pad*2 - 6, cell_h - pad*2 - 6

                # === ВЕРХ ЯЧЕЙКИ: деликатная плашка под дату/месяц
                header_h = min(ih // 2, FONT40.size + 12)  # не более половины внутренней высоты
                # делаем плашку на тон светлее фона ячейки
                hf = fill
                hdr = (min(255, hf[0] + 8), min(255, hf[1] + 8), min(255, hf[2] + 10))
                draw.rounded_rectangle(
                    [ix - 4, iy - 2, ix + iw, iy - 2 + header_h],
                    radius=DS.radii.sm, fill=hdr
                )

                # === ДАТА: крупно, с чёрной обводкой (для читаемости)
                day_font = FONT40
                day_str = str(cur.day)
                draw.text(
                    (ix, iy), day_str, fill=COLOR_TEXT, font=day_font,
                    stroke_width=2, stroke_fill=(0, 0, 0)  # чёрная обводка
                )
                dw = draw.textlength(day_str, font=day_font)

                # Месяц сразу после числа — ВСЕГДА (короткий или полный вариант)
                mtxt = RU_MONTHS_SHORT[cur.month] if DS.calendar.month_label_case == "short" else RU_MONTHS[cur.month]
                mfont = FONT16
                mx = ix + dw + 8
                my = iy + max(0, (day_font.size - mfont.size) // 2)

                tw = draw.textlength(mtxt, font=mfont)
                cap_pad = 5
                cap_h = mfont.size + 6
                draw.rounded_rectangle(
                    [mx - cap_pad, my - 3, mx + tw + cap_pad, my + cap_h - 3],
                    radius=DS.radii.sm, fill=BADGE_BG
                )
                draw.text((mx, my), mtxt, fill=BADGE_TEXT, font=mfont)

                # Месяц сразу после числа, только если это 1-е
                if cur.day == 1:
                    mtxt = RU_MONTHS_SHORT[cur.month] if DS.calendar.month_label_case == "short" else RU_MONTHS[cur.month]
                    mfont = FONT16
                    mx = ix + dw + 8
                    my = iy + (day_font.size - mfont.size) // 2 + 1
                    # аккуратная “капсула”
                    tw = draw.textlength(mtxt, font=mfont)
                    cap_pad = 5
                    cap_h = mfont.size + 6
                    draw.rounded_rectangle(
                        [mx - cap_pad, my - 3, mx + tw + cap_pad, my + cap_h - 3],
                        radius=DS.radii.sm, fill=BADGE_BG
                    )
                    draw.text((mx, my), mtxt, fill=BADGE_TEXT, font=mfont)

                # === ТЕМПЕРАТУРА (КРУПНО, ПО ЦЕНТРУ ЯЧЕЙКИ)
                info = wx.get(cur) or {}
                tmax, tmin = info.get("tmax"), info.get("tmin")
                if (tmax is not None) or (tmin is not None):
                    # базовый кегль (потом можем сузить, если не влезает по ширине/высоте)
                    tfont = FONT32 if cell_h >= 140 else FONT28

                    if (tmax is not None) and (tmin is not None):
                        t_str = f"↑{int(round(tmax))}° / ↓{int(round(tmin))}°"
                    elif tmax is not None:
                        t_str = f"↑{int(round(tmax))}°"
                    else:
                        t_str = f"↓{int(round(tmin))}°"

                    # область, в которой можно центрировать (исключаем нижнюю полосу под иконки)
                    bottom_pad = 10
                    icon_sz = DS.calendar.weather_icon
                    center_top = iy
                    center_bottom = (cy + cell_h) - bottom_pad - icon_sz  # верх границы чипов
                    center_h = max(0, center_bottom - center_top)

                    # если ширина не влазит — более компактная строка
                    if draw.textlength(t_str, font=tfont) > iw:
                        if (tmax is not None) and (tmin is not None):
                            t_str = f"{int(round(tmax)):+d}°/{int(round(tmin)):+d}°"

                    # подгон кегля по ширине/высоте центра
                    def fit_font(s, font_primary):
                        # пробуем 32 → 28 → 24
                        for f in (font_primary, FONT28, FONT24):
                            tw = draw.textlength(s, font=f)
                            th = f.size
                            if tw <= iw and th <= center_h:
                                return f, tw, th
                        # совсем тесно — ужимаем до одной температуры
                        s2 = f"{int(round((tmax if tmax is not None else tmin))):+d}°"
                        for f in (FONT28, FONT24, FONT20):
                            tw = draw.textlength(s2, font=f)
                            th = f.size
                            if tw <= iw and th <= center_h:
                                return f, tw, th, s2
                        return font_primary, draw.textlength(s), font_primary.size

                    fit = fit_font(t_str, tfont)
                    if len(fit) == 4:
                        tfont, tw, th, t_str = fit
                    else:
                        tfont, tw, th = fit

                    tx = ix + (iw - tw) / 2
                    ty = center_top + (center_h - th) / 2
                    # выбор температуры для цвета: берём среднюю, если обе есть
                    t_for_color = None
                    if (tmax is not None) and (tmin is not None):
                        t_for_color = (float(tmax) + float(tmin)) / 2.0
                    else:
                        t_for_color = float(tmax) if (tmax is not None) else (
                            float(tmin) if (tmin is not None) else None)

                    fill_col = self._temp_to_color(t_for_color)

                    draw.text(
                        (tx, ty), t_str, fill=fill_col, font=tfont,
                        stroke_width=2, stroke_fill=(0, 0, 0)  # чёткая чёрная обводка
                    )
                # === ПОГОДНЫЕ “ЧИПЫ” СНИЗУ (перенос по строкам, снизу-вверх)
                bottom_pad = 16  # было 10 — теперь не прилипает
                icon_sz = DS.calendar.weather_icon + 4  # иконки крупнее
                row_gap = 8  # межстрочный зазор
                by = cy + cell_h - bottom_pad - icon_sz
                ix0 = ix
                maxw = iw

                # шрифт чипов — крупнее
                chip_font = FONT22 if hasattr(__builtins__, "True") else FONT20  # просто гарантируем FONT22

                # соберём список чипов: [(icon_key, text_or_None, color), ...]
                chips: list[tuple[str, str | None, tuple[int, int, int]]] = []
                rain = info.get("rain_mm")
                if rain is not None:
                    rv = float(rain)
                    if rv >= RAIN_ALERT_MM:
                        chips.append(("rain_heavy", f"{int(round(rv))} мм", BADGE_RAIN_HIGH))
                    elif rv > 0.0:
                        chips.append(("rain", f"{int(round(rv))} мм", BADGE_RAIN))
                    else:
                        chips.append(("dry", None, BADGE_TEXT))

                wind = info.get("wind_ms")
                if wind is not None:
                    # показываем ветер всегда; цвет усилим, если порог превышен
                    wcol = BADGE_WIND if float(wind) >= WIND_ALERT_MS else BADGE_TEXT
                    chips.append(("wind", f"{int(round(wind))} м/с", wcol))

                # разложим по строкам с переносом
                rows: list[list[tuple[str, str | None, tuple[int, int, int]]]] = [[]]
                cur_w = 0
                for chip in chips:
                    need = self._measure_icon_chip(draw, chip[0], chip[1], chip_font)
                    if rows[-1] and (cur_w + need > maxw):
                        rows.append([chip])
                        cur_w = need + DS.calendar.weather_gap
                    else:
                        rows[-1].append(chip)
                        cur_w += need + DS.calendar.weather_gap

                # отрисуем снизу-вверх
                for r_idx, row in enumerate(reversed(rows)):
                    y_row = by - r_idx * (icon_sz + row_gap)
                    x_row = ix0
                    for (icon_key, txt, col) in row:
                        used = self._draw_icon_chip(im, draw, x_row, y_row, icon_key, txt, chip_font, col)
                        x_row += used + DS.calendar.weather_gap
                # следующий день
                cur += timedelta(days=1)

    def _clock_text_color_for_day(self, day: date) -> tuple[int, int, int]:
        kind = self.today_kind(day)
        if kind == "holiday":
            return (255, 160, 150)  # светло-красный
        if kind == "weekend":
            return (160, 160, 170)  # тёмно-серый
        return (255, 215, 100)  # жёлтый для будней

    def _paste_icon(self, im, icon, x, y):
        """Аккуратно накладывает RGBA-иконку поверх RGB-карты."""
        if icon is None:
            return (0, 0)
        w, h = icon.size
        im.paste(icon, (int(x), int(y)), mask=icon)
        return (w, h)


    def _temp_to_color(self, t: float | None) -> tuple[int, int, int]:
        """
        Подбор цвета температуры: холод — холодные тона, тепло — тёплые.
        Диапазоны можно подстроить по вкусу.
        """
        if t is None:
            return COLOR_TEMP  # дефолт
        v = float(t)
        # пороги (°C): < -15, -15..0, 0..10, 10..20, 20..30, >=30
        if v < -15:   return (140, 180, 255)  # ледяной голубой
        if v < 0:     return (160, 200, 255)  # холодный голубой
        if v < 10:    return (210, 230, 255)  # прохладный
        if v < 20:    return (255, 230, 170)  # тёплый мягкий
        if v < 30:    return (255, 200, 120)  # тёплый
        return (255, 160, 90)  # жарко

    def four_week_window(self, today: date) -> tuple[date, date]:
        """
        Старт: (today - 7 дней), но выровненный на ПОНЕДЕЛЬНИК.
        Продолжительность: ровно 28 дней (4 недели, Пн-Вс).
        """
        raw_start = today - timedelta(days=7)
        monday_offset = raw_start.weekday()  # Mon=0...Sun=6
        start = raw_start - timedelta(days=monday_offset)
        end = start + timedelta(days=27)
        return start, end

    def _measure_icon_chip(self, draw, icon_name: str, text: str | None, font) -> int:
        """Оценка ширины чипа без отрисовки (иконка + отступ + текст)."""
        icon_sz = DS.calendar.weather_icon
        w = icon_sz  # сама иконка
        if text:
            w += 6 + int(draw.textlength(text, font=font))
        return int(w)

    def _draw_badge(self, draw: ImageDraw.ImageDraw, im: Image.Image,
                    x: int, y: int, text: str, font: ImageFont.FreeTypeFont,
                    color_text: tuple[int,int,int], pad_h: int = 2, pad_w: int = 6,
                    icon_name: str | None = None, icon_size: int = 16) -> int:
        """
        Рисует бейдж (фон + [иконка] + текст). Возвращает ширину бейджа (для следующего).
        """
        tw = int(draw.textlength(text, font=font))
        icon = get_icon(icon_name, icon_size) if icon_name else None
        icon_w = (icon.width + 6) if icon else 0
        w = pad_w + icon_w + tw + pad_w
        h = (font.size if hasattr(font, "size") else 16) + pad_h * 2

        # фон бейджа со скруглением
        rx = DS.radii.sm
        draw.rounded_rectangle([x, y, x + w, y + h], radius=rx, fill=DS.color.badge_bg)

        # иконка
        if icon is not None:
            self._paste_icon(im, icon, x + pad_w, y + (h - icon.height)//2)
            tx = x + pad_w + icon_w
        else:
            tx = x + pad_w

        # текст
        draw.text((tx, y + pad_h), text, fill=color_text, font=font)
        return w


    def _draw_icon_chip(self, im, draw, x, y, icon_name: str,
                        text: str | None, font, fill_rgb):
        """
        Иконка + (опционально) цифры/единицы справа. Без слов «дождь/ветер».
        Возвращает ширину чипа (для последовательной выкладки).
        """
        pad_x = 6
        icon_sz = DS.calendar.weather_icon
        icon = get_icon(icon_name, size=icon_sz)
        ix, iy = x, y
        if icon is not None:
            self._paste_icon(im, icon, ix, iy)
            ix += icon_sz + 6  # отступ после иконки

        w = icon_sz
        if text:
            # выравниваем по базовой линии, текст крупнее
            ty = y + max(0, (icon_sz - font.size) // 2)
            draw.text((ix, ty), text, fill=fill_rgb, font=font)
            w = (ix - x) + draw.textlength(text, font=font)
        return int(w)

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

    def render_calendar_clock_weather_4w(self, now: Optional[datetime] = None,
                                         W: int = 1280, H: int = 720) -> np.ndarray:
        """
        Левая часть: 4-недельный календарь с погодой.
        Правая часть: аналоговые часы + цифровое время/дата; под ними — подробная погода на сегодня.
        """
        now = now or datetime.now()
        today = now.date()
        self.refresh_holidays_if_needed()
        try:
            weather = self.fetch_weather_daily_cached()
        except Exception:
            weather = {}

        # Подготовим окно дат
        start, end = self.four_week_window(today)

        im = Image.new("RGB", (W, H), COLOR_BG)
        draw = ImageDraw.Draw(im)

        # ЛЕВО: календарь (примерно 2/3 ширины)
        left_x, left_y = 30, 30
        left_w = (W * 2) // 3 - 40
        left_h = H - 60
        self.draw_4weeks_with_weather(
            im, draw,               # 👈 передаём base image
            left_x, left_y, left_w, left_h,
            start, today, weather
        )
        # ПРАВО: часы + цифровые
        right_x = left_x + left_w + 20
        right_w = W - right_x - 30
        right_y = 30
        right_h = H - 60

        # 1) квадратный циферблат, центрируем по ширине
        clock_size = min(right_w, right_h - 260)  # оставляем запас под время/дату и "Погода сегодня"
        clock_pil = self.draw_analog_clock(clock_size, clock_size, now)
        clock_x = right_x + (right_w - clock_size) // 2
        clock_y = right_y
        im.paste(clock_pil, (clock_x, clock_y))

        # 2) цифровые — СРАЗУ под кругом, с небольшим отступом
        base_y = clock_y + clock_size + 10

        t_color = self._clock_text_color_for_day(now.date())
        tstr = now.strftime("%H:%M:%S")
        dstr = now.strftime("%d.%m.%Y")

        tfont = FONT48
        t_w = draw.textlength(tstr, font=tfont)
        tx = right_x + (right_w - t_w) / 2
        ty = base_y
        draw.text((tx, ty), tstr, fill=t_color, font=tfont, stroke_width=3, stroke_fill=(0, 0, 0))

        dfont = FONT28
        d_w = draw.textlength(dstr, font=dfont)
        dx = right_x + (right_w - d_w) / 2
        draw.text((dx, ty + tfont.size + 6), dstr, fill=t_color, font=dfont, stroke_width=2, stroke_fill=(0, 0, 0))

        # 3) "Погода сегодня" — бокс начинается сразу после даты
        box_y = ty + tfont.size + 10 + dfont.size + 14
        box_h = right_y + right_h - box_y
        draw.rounded_rectangle([right_x, box_y, right_x + right_w, box_y + box_h],
                               radius=DS.radii.md, fill=DS.color.panel)

        wx_today = weather.get(today) or {}
        line_x = right_x + 14
        line_y = box_y + 12
        maxw = right_w - 28

        # Заголовок
        draw.text((line_x, line_y), "Погода сегодня", fill=COLOR_SUB, font=FONT32)
        line_y += FONT32.size + 8

        # Температура — как строка, крупно, с обводкой и «тепло/холод» цветом
        tmax = wx_today.get("tmax");
        tmin = wx_today.get("tmin")
        if (tmax is not None) or (tmin is not None):
            t_str = []
            if tmax is not None: t_str.append(f"↑{int(round(tmax))}°C")
            if tmin is not None: t_str.append(f"↓{int(round(tmin))}°C")
            t_str = " / ".join(t_str) if t_str else "—"
            tfont = FONT32
            fill_col = self._temp_to_color(((tmax or 0) + (tmin or 0)) / 2 if (tmax is not None and tmin is not None)
                                           else (tmax if tmax is not None else tmin))
            tw = draw.textlength(t_str, font=tfont)
            tx = line_x
            draw.text((tx, line_y), t_str, fill=fill_col, font=tfont, stroke_width=2, stroke_fill=(0, 0, 0))
            line_y += tfont.size + 10

        # Чипы: осадки и ветер — SVG-иконки, перенос по строкам при нехватке ширины
        chips = []
        rain = wx_today.get("rain_mm")
        if rain is not None:
            rv = float(rain)
            if rv >= RAIN_ALERT_MM:
                chips.append(("rain_heavy", f"{int(round(rv))} мм", BADGE_RAIN_HIGH))
            elif rv > 0.0:
                chips.append(("rain", f"{int(round(rv))} мм", BADGE_RAIN))
            else:
                chips.append(("dry", None, BADGE_TEXT))

        wind = wx_today.get("wind_ms")
        if wind is not None:
            chips.append(("wind", f"{int(round(wind))} м/с", BADGE_WIND))

        chip_font = FONT22
        icon_sz = DS.calendar.weather_icon + 6  # чуть крупнее, чем в ячейках
        row_gap = 10
        x_cursor = line_x
        y_cursor = line_y
        cur_w = 0

        # перенос по строкам
        rows = [[]]
        for icon_key, txt, col in chips:
            need = self._measure_icon_chip(draw, icon_key, txt, chip_font)
            if rows[-1] and (cur_w + need > maxw):
                rows.append([(icon_key, txt, col)])
                cur_w = need + DS.calendar.weather_gap
            else:
                rows[-1].append((icon_key, txt, col))
                cur_w += need + DS.calendar.weather_gap

        # отрисовка строк
        for row in rows:
            x_cursor = line_x
            for (icon_key, txt, col) in row:
                used = self._draw_icon_chip(im, draw, x_cursor, y_cursor, icon_key, txt, chip_font, col)
                x_cursor += used + DS.calendar.weather_gap
            y_cursor += icon_sz + row_gap

        # Аномальные условия — внизу блока
        if rain is not None and float(rain) >= RAIN_ALERT_MM:
            draw.text((line_x, y_cursor + 4), "⚠ Много осадков", fill=BADGE_RAIN_HIGH, font=FONT18)
            y_cursor += FONT18.size + 4
        if wind is not None and float(wind) >= WIND_ALERT_MS:
            draw.text((line_x, y_cursor + 2), "⚠ Сильный ветер", fill=BADGE_WIND, font=FONT18)

        # ----- Баннер "Флаги" под календарём (левая колонка, низ) -----
        today = now.date()
        upcoming = self.upcoming_holidays(today, horizon_days=14)
        banner_h = 92
        banner_x = left_x
        banner_y = left_y + left_h - banner_h
        banner_w = left_w
        draw.rectangle([banner_x, banner_y, banner_x + banner_w, banner_y + banner_h],
                       fill=(24, 24, 28))

        if upcoming:
            draw.text((banner_x + 10, banner_y + 8), "Флаги должны висеть:", fill=COLOR_ALERT, font=FONT24)
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            # выведем в две строки максимум, остальное не влезет — ок
            y_line = banner_y + 40
            maxw = banner_w - 20
            text = "   ".join(lines)
            draw_wrapped_text(draw, (banner_x + 10, y_line), text, max_width=maxw, line_height=26, font=FONT18)
        else:
            draw.text((banner_x + 10, banner_y + 8),
                      "В ближайшие 14 дней флаги вешать не надо.",
                      fill=COLOR_OK, font=FONT24)

        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)





    # ---------------------- Погода (Open-Meteo) ----------------------
    def fetch_weather_daily_cached(
        self,
        lat: float = WEATHER_LAT,
        lon: float = WEATHER_LON,
        tz: str = WEATHER_TZ,
        ttl: float = 1800.0,   # 30 минут
        timeout: float = 6.0
    ) -> dict:
        """
        Возвращает словарь с дневными данными:
        date -> {tmax, tmin, rain_mm, wind_max_ms}
        Диапазон: прошлые 7 дней + ближайшие 16 дней (ограничение API).
        Этого достаточно, чтобы закрыть окно ~4 недель (Пн-Вс).
        """
        # Open-Meteo: daily + past_days + forecast_days
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max"
            "&past_days=7&forecast_days=16"
            f"&timezone={tz}"
        )
        data = self.fetch_json_cached(url, ttl=ttl, timeout=timeout) or {}
        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        tmax  = daily.get("temperature_2m_max") or []
        tmin  = daily.get("temperature_2m_min") or []
        rain  = daily.get("precipitation_sum") or []
        wind  = daily.get("windspeed_10m_max") or []

        by_date: dict[date, dict] = {}
        for i, ds in enumerate(dates):
            try:
                d = datetime.strptime(ds, "%Y-%m-%d").date()
                by_date[d] = {
                    "tmax": tmax[i] if i < len(tmax) else None,
                    "tmin": tmin[i] if i < len(tmin) else None,
                    "rain_mm": rain[i] if i < len(rain) else None,
                    "wind_ms": wind[i] if i < len(wind) else None,
                }
            except Exception:
                continue
        return by_date

