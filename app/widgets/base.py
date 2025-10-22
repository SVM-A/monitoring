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
            except Exception as e:
                # мягко переживаем исключения внутри рендера
                print("render error:", repr(e))
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

    def draw_analog_clock(self, W: int, H: int, now: datetime,
                          sky_icon_key: str | None = None) -> Image.Image:
        kind = self.today_kind(now.date())
        face_fill = CLOCK_NORMAL if kind == "normal" else (CLOCK_WEEKEND if kind == "weekend" else CLOCK_HOLIDAY)
        S = min(W, H)
        cx, cy = S // 2, S // 2
        r = int(S * 0.42)

        im = Image.new("RGB", (W, H), COLOR_BG)
        d = ImageDraw.Draw(im)

        # фон круга
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(100, 100, 110), width=4, fill=face_fill)

        # ----- ФОН-НЕБО (по желанию) -----
        if sky_icon_key:
            # «диаметр между цифрами»: цифры стоят на радиусе r-30 => диаметр = 2*(r-30)
            inner_d = max(10, 2 * (r - 30))
            sky_icon = get_icon(sky_icon_key, size=inner_d)
            sky_icon = self._circle_clip(sky_icon, inner_d)
            if sky_icon is not None:
                # чуть приглушим, чтобы не спорила с метками
                sky_icon = sky_icon.copy()
                try:
                    alpha = sky_icon.getchannel('A')
                    sky_icon.putalpha(alpha.point(lambda a: min(a, 170)))
                except Exception:
                    pass
                self._paste_icon(im, sky_icon, cx - inner_d // 2, cy - inner_d // 2)

        # риски
        for i in range(60):
            angle = (i / 60.0) * 2.0 * math.pi
            outer = (cx + int(r * math.sin(angle)), cy - int(r * math.cos(angle)))
            inner_len = 12 if i % 5 else 20
            inner = (cx + int((r - inner_len) * math.sin(angle)), cy - int((r - inner_len) * math.cos(angle)))
            d.line([inner, outer], fill=(170, 170, 180) if i % 5 == 0 else (110, 110, 120),
                   width=2 if i % 5 == 0 else 1)

        # цифры — уже были крупнее и со stroke, оставляем
        for n in range(1, 13):
            angle = (n / 12.0) * 2.0 * math.pi
            tx = cx + int((r - 30) * math.sin(angle))
            ty = cy - int((r - 30) * math.cos(angle))
            text = str(n)
            tw = d.textlength(text, font=FONT32)
            th = 32
            d.text((tx - tw / 2, ty - th / 2), text, fill=COLOR_TEXT, font=FONT32,
                   stroke_width=2, stroke_fill=(0, 0, 0))

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
    def _clock_text_color_for_day(self, day: date) -> tuple[int, int, int]:
        kind = self.today_kind(day)
        if kind == "holiday":
            return (255, 160, 150)  # светло-красный
        if kind == "weekend":
            return (160, 160, 170)  # тёмно-серый
        return (255, 215, 100)  # жёлтый для будней

    @staticmethod
    def _paste_icon(im: Image.Image, icon: Image.Image, x: int, y: int):
        # canvas может быть RGB — это нормально: paste с mask воспримет альфу из канала A
        if icon.mode != 'RGBA':
            icon = icon.convert('RGBA')
        im.paste(icon, (x, y), icon)

    @staticmethod
    def _circle_clip(im: Image.Image, diameter: int) -> Image.Image:
        im = im.convert('RGBA')
        mask = Image.new('L', (diameter, diameter), 0)
        d = ImageDraw.Draw(mask)
        d.ellipse([0, 0, diameter - 1, diameter - 1], fill=255)
        out = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
        out.paste(im.resize((diameter, diameter), Image.LANCZOS), (0, 0), mask)
        return out

    @staticmethod
    def _temp_to_color(t: float | None) -> tuple[int, int, int]:
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

    @staticmethod
    def four_week_window(today: date) -> tuple[date, date]:
        """
        Старт: (today - 7 дней), но выровненный на ПОНЕДЕЛЬНИК.
        Продолжительность: ровно 28 дней (4 недели, Пн-Вс).
        """
        raw_start = today - timedelta(days=7)
        monday_offset = raw_start.weekday()  # Mon=0...Sun=6
        start = raw_start - timedelta(days=monday_offset)
        end = start + timedelta(days=27)
        return start, end

    @staticmethod
    def _measure_icon_chip(draw, icon_name: str, text: str | None, font) -> int:
        """Оценка ширины чипа без отрисовки (иконка + отступ + текст)."""
        icon_sz = DS.calendar.weather_icon
        w = icon_sz  # сама иконка
        if text:
            w += 6 + int(draw.textlength(text, font=font))
        return int(w)

    @staticmethod
    def _collect_anomalies(day_info: dict) -> list[tuple[str, str, tuple[int, int, int]]]:
        """
        Возвращает список [(icon_key, label, color)] для правой полуячейки «Погода сегодня».
        Логика простая и объяснимая, без внешних зависимостей.
        """
        items: list[tuple[str, str, tuple[int, int, int]]] = []
        tmax = day_info.get("tmax")
        tmin = day_info.get("tmin")
        rain = day_info.get("rain_mm")
        wind = day_info.get("wind_ms")

        # 1) Сильный ветер
        if wind is not None and float(wind) >= WIND_ALERT_MS:
            items.append(("wind", "Сильный ветер", BADGE_WIND))

        # 2) Много осадков
        if rain is not None and float(rain) >= RAIN_ALERT_MM:
            items.append(("rain_heavy", "Много осадков", BADGE_RAIN_HIGH))

        # 3) Снегопад (есть осадки и максимум ≤ 0°C)
        if (rain is not None and float(rain) > 0) and (tmax is not None and float(tmax) <= 0.0):
            items.append(("snow", "Снегопад", BADGE_TEXT))

        # 4) Жара (tmax ≥ 30°C)
        if tmax is not None and float(tmax) >= 30.0:
            items.append(("temperature-sun", "Жара", (255, 170, 80)))

        # 5) Мороз (tmin ≤ −15°C)
        if tmin is not None and float(tmin) <= -15.0:
            items.append(("temperature-snow", "Мороз", (170, 200, 255)))

        # 6) Гололёд возможен (осадки при отрицательных температурах)
        if (rain is not None and float(rain) > 0) and (
                (tmin is not None and float(tmin) <= 0.0) or (tmax is not None and float(tmax) <= 0.0)
        ):
            items.append(("cloud-sleet", "Гололёд возможно", (200, 200, 230)))

        # dedup по подписи: оставим самые «жёсткие» первые
        seen = set()
        out = []
        for ic, txt, col in items:
            if txt in seen:
                continue
            seen.add(txt)
            out.append((ic, txt, col))
        return out

    @staticmethod
    def _pick_sky_icon(day_info: dict, now_dt: datetime) -> str | None:
        """
        Возвращает ключ иконки 'sky_sun' или 'sky_night' для СУХОЙ погоды.
        Для дождя/снега — None (фон не ставим, чтобы не перегружать).
        """
        rain = day_info.get("rain_mm")
        if rain is not None:
            try:
                rv = float(rain)
            except Exception:
                rv = None
            # если есть осадки — фоновую «небо»-иконку не рисуем
            if rv is not None and rv > 0.0:
                return None

        sr_s = day_info.get("sunrise")
        ss_s = day_info.get("sunset")
        if not sr_s or not ss_s:
            # нет данных — по умолчанию день
            return "sky_sun"

        try:
            # строки от Open-Meteo уже в локальном tz, просто парсим
            sr = datetime.strptime(sr_s, "%Y-%m-%dT%H:%M")
            ss = datetime.strptime(ss_s, "%Y-%m-%dT%H:%M")
        except Exception:
            return "sky_sun"

        # ночь: до восхода или после заката
        is_night = (now_dt < sr) or (now_dt > ss)
        return "sky_night" if is_night else "sky_sun"

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
        wx_today = weather.get(today) or {}

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


        sky_icon_key = self._pick_sky_icon(wx_today, now)

        # 1) квадратный циферблат
        clock_size = min(right_w, right_h - 260)
        clock_pil = self.draw_analog_clock(clock_size, clock_size, now, sky_icon_key=sky_icon_key)
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

        pad = 16
        inner_x = right_x + pad
        inner_y = box_y + pad
        inner_w = right_w - pad * 2
        inner_h = box_h - pad * 2

        # Заголовок (по центру)
        title = "Погода сегодня"
        tw = draw.textlength(title, font=FONT32)
        draw.text((inner_x + (inner_w - tw) / 2, inner_y), title, fill=COLOR_SUB, font=FONT32)
        inner_y += FONT32.size + 10

        # === Вертикально делим пополам: слева погода, справа аномалии ===
        gap = 12
        left_w = (inner_w - gap) // 2
        right_w_half = inner_w - left_w - gap
        left_x = inner_x
        right_x_half = inner_x + left_w + gap
        content_top = inner_y

        # ---------- ЛЕВАЯ: температура + (иконка неба — тонкая черта — ветер) + флаги ----------
        lx, ly, lw = left_x, content_top, left_w

        # Температура
        tmax = wx_today.get("tmax")
        tmin = wx_today.get("tmin")
        if (tmax is not None) or (tmin is not None):
            t_str_parts = []
            if tmax is not None: t_str_parts.append(f"↑{int(round(tmax))}°C")
            if tmin is not None: t_str_parts.append(f"↓{int(round(tmin))}°C")
            t_str = " / ".join(t_str_parts) if t_str_parts else "—"
            tfont_big = FONT40
            t_col = self._temp_to_color(((tmax or 0) + (tmin or 0)) / 2 if (tmax is not None and tmin is not None)
                                        else (tmax if tmax is not None else tmin))
            draw.text((lx, ly), t_str, fill=t_col, font=tfont_big, stroke_width=3, stroke_fill=(0, 0, 0))
            ly += tfont_big.size + 10

        # Единая строка: [иконка неба] — [тонкая черта] — [ветер]
        wfont = FONT40
        wind = wx_today.get("wind_ms")
        rain = wx_today.get("rain_mm")

        # иконка неба
        ix = lx
        iy = ly

        # сила ветра
        if wind is not None:
            wval = f"{int(round(wind))} м/с"
            w_col = BADGE_WIND if float(wind) >= WIND_ALERT_MS else BADGE_TEXT
            draw.text((ix, iy), wval, fill=w_col, font=wfont, stroke_width=3, stroke_fill=(0, 0, 0))
        ly += wfont.size + 12



        # Полноширинный разделитель по всей ячейке «Погода сегодня» (исправлено: 90 вместо 'ninety')
        draw.line([inner_x, ly, inner_x + inner_w, ly], fill=(80, 80, 90), width=1)
        ly += 10

        # Флаги под чертой (без отдельной подложки, в цвет ячейки)
        upcoming = self.upcoming_holidays(today, horizon_days=14)
        if upcoming:
            draw.text((lx, ly), "Флаги должны висеть:", fill=COLOR_ALERT, font=FONT24)
            ly += FONT24.size + 6
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            y_ptr = ly
            y_ptr = draw_wrapped_text(draw, (lx, y_ptr), "   ".join(lines),
                                      max_width=lw, line_height=26, font=FONT18)
            left_bottom_y = y_ptr
        else:
            draw.text((lx, ly), "В ближайшие 14 дней флаги вешать не надо", fill=COLOR_OK, font=FONT24)
            left_bottom_y = ly + FONT24.size

        # ---------- ПРАВАЯ: аномалии (с отступами, крупнее, центр и перенос по словам) ----------
        rx, ry, rw = right_x_half, content_top, right_w_half
        anoms = self._collect_anomalies(wx_today)

        # Паддинги внутри правой полу-ячейки
        a_pad_x = 16
        a_pad_top = 10
        a_pad_between = 14  # зазор между карточками аномалий

        # Увеличенные размеры (FONT48 и FONT28 уже есть в проекте)
        a_icon_sz = FONT48.size
        lab_font = FONT28

        # Вспомогательная функция: перенос по словам и центр каждой строки
        def _draw_center_wrapped(text: str, top_y: int, color: tuple[int, int, int]) -> int:
            max_w = rw - 2 * a_pad_x
            words = text.split()
            lines, cur = [], ""
            for w_ in words:
                test = (cur + " " + w_).strip()
                if draw.textlength(test, font=lab_font) <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w_
            if cur:
                lines.append(cur)
            y_ptr_local = top_y
            for ln in lines:
                tw = draw.textlength(ln, font=lab_font)
                lx_c = rx + (rw - tw) / 2
                draw.text((lx_c, y_ptr_local), ln, fill=color, font=lab_font,
                          stroke_width=2, stroke_fill=(0, 0, 0))
                y_ptr_local += lab_font.size + 4
            return y_ptr_local

        if anoms:
            y_ptr = ry + a_pad_top
            for (icon_key, label, col) in anoms:
                icon = get_icon(icon_key, size=a_icon_sz)
                if icon is not None:
                    im.paste(icon, (rx + (rw - a_icon_sz) // 2, y_ptr), mask=icon)
                y_ptr += a_icon_sz + 6
                y_ptr = _draw_center_wrapped(label, y_ptr, col)
                y_ptr += a_pad_between
        else:
            _ = _draw_center_wrapped("Погодных аномалий нет", ry + a_pad_top, (180, 180, 190))

        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)





    # ---------------------- Погода (Open-Meteo) ----------------------
    def fetch_weather_daily_cached(
            self,
            lat: float = WEATHER_LAT,
            lon: float = WEATHER_LON,
            tz: str = WEATHER_TZ,
            ttl: float = 1800.0,
            timeout: float = 6.0
    ) -> dict:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max,sunrise,sunset"
            "&windspeed_unit=ms"
            "&past_days=7&forecast_days=16"
            f"&timezone={tz}"
        )
        data = self.fetch_json_cached(url, ttl=ttl, timeout=timeout) or {}
        daily = data.get("daily") or {}
        dates = daily.get("time") or []
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        rain = daily.get("precipitation_sum") or []
        wind = daily.get("windspeed_10m_max") or []
        sunrise = daily.get("sunrise") or []
        sunset = daily.get("sunset") or []

        by_date: dict[date, dict] = {}
        for i, ds in enumerate(dates):
            try:
                d = datetime.strptime(ds, "%Y-%m-%d").date()
                by_date[d] = {
                    "tmax": tmax[i] if i < len(tmax) else None,
                    "tmin": tmin[i] if i < len(tmin) else None,
                    "rain_mm": rain[i] if i < len(rain) else None,
                    "wind_ms": wind[i] if i < len(wind) else None,
                    # сохраняем ISO-строки локального времени (уже в tz)
                    "sunrise": sunrise[i] if i < len(sunrise) else None,
                    "sunset": sunset[i] if i < len(sunset) else None,
                }
            except Exception:
                continue
        return by_date


