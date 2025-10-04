"""
camera_monitor.py

Простой, но практичный шаблон:
- захват в thread'ах (VideoCapture)
- heavy processing в multiprocessing.Process
- передача кадров через multiprocessing.Queue в виде JPEG bytes
- простая маска/обрезка (ROI) — настраиваешь координаты в config или загрузкой из json
- placeholder для распознавания номера -> detect_plate()
"""
import math

import cv2
import time
import argparse
import sqlite3
import json
import signal
import queue
from typing import Dict, Optional, Tuple, List
from threading import Thread, Event
from multiprocessing import Process, Queue, Event as MPEvent
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests
from datetime import datetime, timedelta, date


from configs.config_loader import load_cameras, load_roi, reload_roi_from

# ---------------------------
# Конфигурация (простая)
# В реальном проекте вынеси в отдельный файл .json/.yaml и редактируй там
# ---------------------------
DB_PATH = "detections.db"

# Можно подставить RTSP из вашего config или напрямую строку/индекс камеры
CAM_SOURCES = load_cameras()        # соберёт с env

# Максимум кадров в очереди (на каждую камеру)
MAX_QUEUE_SIZE = 8

# ROI пример: прямоугольник (x, y, w, h) или polygon (list of points)
# можно загрузить эти значения из json и менять "на лету"

GLOBAL_ROI = load_roi()

def handle_sighup(signum, frame):
    global GLOBAL_ROI
    print("SIGHUP received — reloading ROI config")
    GLOBAL_ROI = reload_roi_from()

if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, handle_sighup)

# ---------------------------
# Утилиты: DB
# ---------------------------
def init_db(path=DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT,
        timestamp TEXT,
        plate TEXT,
        bbox TEXT,
        extra TEXT
    )
    """)
    conn.commit()
    return conn

def save_detection(conn, camera_id, plate, bbox=None, extra=None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO detections (camera_id, timestamp, plate, bbox, extra) VALUES (?, ?, ?, ?, ?)",
        (camera_id, datetime.utcnow().isoformat(), plate, json.dumps(bbox), json.dumps(extra))
    )
    conn.commit()


def pick_grid(n: int) -> tuple[int, int]:
    """Подбираем сетку: 1,2 -> 1x2; 3-4 -> 2x2; 5-9 -> 3x3; 10-16 -> 4x4."""
    if n <= 1: return (1, 1)
    if n <= 2: return (1, 2)
    if n <= 4: return (2, 2)
    if n <= 9: return (3, 3)
    return (4, 4)

def compose_grid(
    frames: Dict[str, Optional[np.ndarray]],
    out_size: Tuple[int, int] = (1920, 1080)
) -> np.ndarray:
    """Собирает сетку из frames по алфавиту ключей (camera_id) в 16:9 холст."""
    out_w, out_h = out_size
    ids = sorted(frames.keys())
    n = len(ids)
    rows, cols = pick_grid(n)
    cell_w, cell_h = out_w // cols, out_h // rows

    canvas = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)

    def annotate(img, ok: bool):
        if not ok:
            cv2.putText(img, "NO SIGNAL", (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)

    for idx, cam_id in enumerate(ids):
        r, c = divmod(idx, cols)
        frame = frames.get(cam_id)
        fitted = fit_into_box(frame, cell_w, cell_h)
        ok = frame is not None
        annotate(fitted, ok)
        y0, y1 = r * cell_h, (r + 1) * cell_h
        x0, x1 = c * cell_w, (c + 1) * cell_w
        canvas[y0:y1, x0:x1] = fitted

    # если кадров меньше, чем ячеек — оставшиеся остаются чёрными
    return canvas

def compose_focus_layout(
    frames: Dict[str, Optional[np.ndarray]],
    focus_id: str | None,
    widget_ids: List[str],
    out_size: Tuple[int, int] = (1920, 1080),
    widget_size: Tuple[int, int] = (640, 360),
) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]]]:
    """
    Возвращает (canvas, rects), где rects[cam_id] = (x0,y0,x1,y1) — для хит-тестов мыши.
    Если focus_id задан, показываем крупно эту камеру слева, а справа — колонка миниатюр и виджета.
    Если фокуса нет — рисуем обычную сетку.
    Виджеты всегда рисуются в фиксированном размере widget_size.
    """
    out_w, out_h = out_size
    rects: dict[str, tuple[int,int,int,int]] = {}

    # если нет фокуса — используем стандартную сетку
    if not focus_id:
        grid = compose_grid(frames, out_size=out_size)
        # Проставим прямоугольники ячеек для кликов по текущей сетке
        ids = sorted(frames.keys())
        rows, cols = pick_grid(len(ids))
        cell_w, cell_h = out_w // cols, out_h // rows
        for idx, cam_id in enumerate(ids):
            r, c = divmod(idx, cols)
            x0, y0 = c * cell_w, r * cell_h
            rects[cam_id] = (x0, y0, x0 + cell_w, y0 + cell_h)
        return grid, rects

    # с фокусом
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # левая часть под фокус: ~ 2/3 ширины
    left_w = (out_w * 2) // 3
    left_h = out_h
    left = fit_into_box(frames.get(focus_id), left_w, left_h)
    canvas[:, :left_w] = left
    rects[focus_id] = (0, 0, left_w, out_h)

    # правая колонка: фиксированная полоса
    right_x = left_w
    right_w = out_w - left_w
    pad = 12
    thumb_h = 240  # высота миниатюр камер
    thumb_w = right_w - pad * 2

    # сначала — виджеты фиксированным размером
    cur_y = pad
    for wid in widget_ids:
        frame = frames.get(wid)
        w_w, w_h = widget_size
        w = fit_into_box(frame, thumb_w, w_h)
        canvas[cur_y:cur_y + w_h, right_x + pad: right_x + pad + thumb_w] = w
        rects[wid] = (right_x + pad, cur_y, right_x + pad + thumb_w, cur_y + w_h)
        cur_y += w_h + pad

    # затем — миниатюры остальных камер (кроме фокуса и виджетов)
    for cam_id, frame in frames.items():
        if cam_id == focus_id or cam_id in widget_ids:
            continue
        h = min(thumb_h, max(120, (out_h - cur_y) // 3))
        thumb = fit_into_box(frame, thumb_w, h)
        y0, x0 = cur_y, right_x + pad
        y1, x1 = y0 + h, x0 + thumb_w
        if y1 > out_h - pad:
            break
        canvas[y0:y1, x0:x1] = thumb
        rects[cam_id] = (x0, y0, x1, y1)
        cur_y += h + pad

    return canvas, rects


# ---- ФУНКЦИИ ДЛЯ ОТРИСОВКИ ----
def fit_into_box(frame: np.ndarray, box_w: int, box_h: int) -> np.ndarray:
    """Масштабирует кадр с сохранением пропорций, дополняя полями (чёрными) до box_w x box_h."""
    if frame is None or frame.size == 0:
        return np.zeros((box_h, box_w, 3), dtype=np.uint8)
    h, w = frame.shape[:2]
    scale = min(box_w / w, box_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((box_h, box_w, 3), dtype=np.uint8)
    x0 = (box_w - new_w) // 2
    y0 = (box_h - new_h) // 2
    canvas[y0:y0+new_h, x0:x0+new_w] = resized
    return canvas

def compose_two_panel(
    left_frame: Optional[np.ndarray],
    right_frame: Optional[np.ndarray],
    out_size: Tuple[int, int] = (1280, 720),
    left_label: str = "cam_1",
    right_label: str = "cam_2",
) -> np.ndarray:
    """Собирает общее окно 16:9, пополам: левая/правая половины."""
    out_w, out_h = out_size
    # каждая половина — out_w//2 x out_h (соотношение 8:9)
    half_w = out_w // 2
    left = fit_into_box(left_frame, half_w, out_h)
    right = fit_into_box(right_frame, half_w, out_h)

    # подписи/плашки
    def annotate(img, text: str, ok: bool):
        if not ok:
            # NO SIGNAL
            cv2.putText(img, "NO SIGNAL", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)
        cv2.putText(img, text, (20, out_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)

    left_ok = left_frame is not None
    right_ok = right_frame is not None
    annotate(left, left_label, left_ok)
    annotate(right, right_label, right_ok)

    return np.hstack([left, right])


def _find_font() -> Optional[ImageFont.FreeTypeFont]:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, 24)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

_FONT24 = _find_font()
try:
    _FONT32 = ImageFont.truetype(getattr(_FONT24, "path", ""), 32) if hasattr(_FONT24, "path") else _FONT24
except Exception:
    _FONT32 = _FONT24

RU_MONTHS = ["", "Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
RU_WD = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

COLOR_BG        = (18, 18, 22)
COLOR_TEXT      = (230, 230, 230)
COLOR_SUB       = (200, 200, 255)
COLOR_GRID      = (70, 70, 78)
COLOR_CELL      = (35, 35, 40)
COLOR_WEEKEND   = (40, 45, 70)     # подложка выходных дней
COLOR_HOLIDAY   = (120, 30, 40)    # подложка праздников (перекрывает выходные)
COLOR_TODAY     = (80, 90, 110)

COLOR_ALERT     = (255, 170, 60)   # яркий «флаги должны висеть»
COLOR_OK        = (140, 210, 120)  # «флаги не нужны»
CLOCK_NORMAL    = (28, 28, 34)     # фон циферблата — обычный день
CLOCK_WEEKEND   = (34, 34, 48)     # фон циферблата — выходной
CLOCK_HOLIDAY   = (60, 22, 28)     # фон циферблата — праздник


def _draw_wrapped_text(draw: ImageDraw.ImageDraw, xy, text: str, max_width: int, line_height: int, font) -> int:
    """Рисует многострочный текст с переносами по ширине max_width. Возвращает нижнюю Y-координату."""
    x, y = xy
    for paragraph in text.split("\n"):
        if not paragraph:
            y += line_height
            continue
        words = paragraph.split(" ")
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            if draw.textlength(test, font=font) <= max_width:
                line = test
            else:
                draw.text((x, y), line, fill=COLOR_TEXT, font=font)
                y += line_height
                line = w
        if line:
            draw.text((x, y), line, fill=COLOR_TEXT, font=font)
            y += line_height
    return y

# ---------------------------
# ROI / Masking
# ---------------------------
def apply_roi(frame, roi_conf):
    """Возвращает кадр после применения ROI (crop или mask)"""
    if not roi_conf:
        return frame
    t = roi_conf.get("type")
    if t == "rect":
        x, y, w, h = roi_conf.get("rect", [0,0,frame.shape[1], frame.shape[0]])
        return frame[y:y+h, x:x+w]
    elif t == "poly":
        poly = np.array(roi_conf.get("poly", [[0,0],[frame.shape[1],0],[frame.shape[1],frame.shape[0]],[0,frame.shape[0]]]))
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [poly], 255)
        masked = cv2.bitwise_and(frame, frame, mask=mask)
        return masked
    else:
        return frame

# ---------------------------
# Захват: Thread -> кладёт JPEG bytes в multiprocessing.Queue
# ---------------------------
class FrameGrabber(Thread):
    def __init__(self, camera_id, src, out_queue: Queue, stop_event: Event,
                 reconnect_delay=5, ui_queue: Optional[queue.Queue]=None, ui_stride: int = 3):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.src = src
        self.out_queue = out_queue          # в процесс-обработчик (JPEG bytes)
        self.stop_event = stop_event
        self.reconnect_delay = reconnect_delay
        self.cap = None
        self.ui_queue = ui_queue            # локальная очередь для отрисовки (numpy кадры)
        self.ui_stride = ui_stride          # каждый N-й кадр кидать в UI (снижаем нагрузку)
        self._frame_idx = 0

    def open_capture(self):
        self.cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        if not self.cap or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.src)

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.cap is None or not self.cap.isOpened():
                    self.open_capture()
                    if not self.cap or not self.cap.isOpened():
                        print(f"[{self.camera_id}] can't open stream, retry in {self.reconnect_delay}s")
                        time.sleep(self.reconnect_delay)
                        continue
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    print(f"[{self.camera_id}] frame read failed, reconnecting...")
                    self.cap.release()
                    self.cap = None
                    time.sleep(self.reconnect_delay)
                    continue

                # 1) в процесс — JPEG
                ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    jpg_bytes = encoded.tobytes()
                    try:
                        self.out_queue.put_nowait((self.camera_id, jpg_bytes))
                    except:
                        pass

                # 2) в UI — сырой кадр (раз в ui_stride кадров)
                self._frame_idx += 1
                if self.ui_queue is not None and (self._frame_idx % self.ui_stride == 0):
                    try:
                        self.ui_queue.put_nowait((self.camera_id, frame))
                    except:
                        # если переполнена — просто пропускаем
                        pass

            except Exception as e:
                print(f"[{self.camera_id}] grabber exception:", e)
                time.sleep(self.reconnect_delay)

        if self.cap:
            self.cap.release()
        print(f"[{self.camera_id}] grabber stopped")


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
        draw.text((30, 20), title, fill=(230,230,230), font=_FONT32 or _FONT24)

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
        draw.text((x, y), f"{RU_MONTHS[first_day.month]} {first_day.year}", fill=(200,200,255), font=_FONT32 or _FONT24)
        y += 36
        # дни недели
        cell_w = w // 7
        cell_h = (h - 36) // 7  # 1 строка заголовка + 6 недель максимум
        for i, wd in enumerate(RU_WD):
            draw.text((x + i*cell_w + 8, y), wd, fill=(180,180,180), font=_FONT24)
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
            draw.text((cursor_x+8, cursor_y), str(i), fill=(240,240,240), font=_FONT24)

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
        draw.text((30, 40), "Часы", fill=(200,200,255), font=_FONT32 or _FONT24)
        draw.text((30, 120), t, fill=(240,240,240), font=_FONT32 or _FONT24)
        draw.text((30, 180), d, fill=(200,200,200), font=_FONT24)
        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


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
        draw.text((30, 20), "Календарь и часы", fill=COLOR_SUB, font=_FONT32 or _FONT24)

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
            draw.text((info_x + 10, info_top), header, fill=COLOR_ALERT, font=_FONT32 or _FONT24)
            lines = [f"{d.strftime('%d.%m')} — {name}" for d, name in upcoming]
            text = "\n".join(lines)
            _draw_wrapped_text(draw, (info_x + 10, info_top + 40), text, max_width=info_w - 20, line_height=28,
                               font=_FONT24)
        else:
            header = "В ближайшие 14 дней флаги вешать не надо."
            draw.text((info_x + 10, info_top), header, fill=COLOR_OK, font=_FONT32 or _FONT24)

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
        t_w = draw.textlength(tstr, font=_FONT32 or _FONT24)
        d_w = draw.textlength(dstr, font=_FONT24)
        tx = right_x + (right_w - t_w) / 2
        dx = right_x + (right_w - d_w) / 2
        draw.text((tx, base_y), tstr, fill=COLOR_TEXT, font=_FONT32 or _FONT24)
        draw.text((dx, base_y + 34), dstr, fill=(200, 200, 200), font=_FONT24)

        return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)

    # ---------- Рисуем один месяц ----------
    def _draw_month(self, draw: ImageDraw.ImageDraw, x, y, w, h, first_day: date, today: date):
        # Заголовок месяца
        draw.text((x, y), f"{RU_MONTHS[first_day.month]} {first_day.year}", fill=COLOR_SUB, font=_FONT32 or _FONT24)
        y += 36

        # Дни недели
        cell_w = w // 7
        # 1 строка заголовка + максимум 6 недель = 7 строк
        cell_h = (h - 36) // 7
        for i, wd in enumerate(RU_WD):
            draw.text((x + i*cell_w + 8, y), wd, fill=(180,180,180), font=_FONT24)
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
            draw.text((cursor_x+8, cursor_y), str(dnum), fill=COLOR_TEXT, font=_FONT24)
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
            tw = d.textlength(text, font=_FONT24)
            th = 24
            d.text((tx - tw / 2, ty - th / 2), text, fill=COLOR_TEXT, font=_FONT24)

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
        draw.text((30, 30), "Праздники (14 дней)", fill=(200,200,255), font=_FONT32 or _FONT24)
        # перенос строк
        y = 90
        for line in text.split("\n"):
            draw.text((30, y), line, fill=(230,230,230), font=_FONT24)
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


# ---------------------------
# Processor: отдельный процесс (по одному на камеру или общий)
# ---------------------------
def processor_proc(in_queue: Queue, stop_event: MPEvent, db_path: str, roi_config: dict):
    """
    Процесс, который читает JPG bytes, декодирует, применяет ROI/маску и выполняет детекцию номера.
    """
    # Открываем DB в процессе
    conn = sqlite3.connect(db_path, check_same_thread=False)

    while not stop_event.is_set():
        try:
            item = in_queue.get(timeout=0.5)  # ждём полсекунды
        except Exception:
            continue
        if item is None:  # sentinel для завершения
            break
        camera_id, jpg_bytes = item
        # декодируем
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # Применяем ROI, если есть
        roi_conf = roi_config.get(camera_id)
        proc_frame = apply_roi(frame, roi_conf)

        # ---- Тут ваша логика распознавания номера ----
        # detect_plate должен возвращать: plate_text, bbox (x,y,w,h) или None
        plate, bbox = detect_plate(proc_frame)
        if plate:
            print(f"[{camera_id}] plate detected: {plate} bbox={bbox}")
            save_detection(conn, camera_id, plate, bbox=bbox, extra={"detected_by": "stub"})
        # ----------------------------------------------

    conn.close()
    print("Processor stopped")


# ---------------------------
# Заглушка детектора (замени своей моделью)
# ---------------------------
def detect_plate(frame):
    """
    Placeholder. В реальном случае:
     - запускаем модель (OCR, NN) на кадре или предварительно детектированном сниппете
     - возвращаем строку номера и bbox относительно кадра (x,y,w,h)
    Здесь просто пример — возвращаем None.
    """
    # NB: чтобы протестировать, можно раскомментировать тестовую заглушку:
    # import random
    # if random.random() < 0.01:
    #     return "A111AA77", [10,10,200,80]
    return None, None


def mask_url(u: str) -> str:
    # rtsp://user:pass@host:port/...
    try:
        head, tail = u.split("://", 1)
        if "@" in tail and ":" in tail.split("@", 1)[0]:
            creds, rest = tail.split("@", 1)
            user, _ = creds.split(":", 1)
            return f"{head}://{user}:***@{rest}"
    except Exception:
        pass
    return u

# ---------------------------
# CLI / Main
# ---------------------------
def main(selected_cams):
    # Инициализация БД
    conn = init_db(DB_PATH)
    conn.close()

    # Очередь для процесса-обработчика (JPEG)
    frame_queue = Queue(maxsize=MAX_QUEUE_SIZE)

    # Очередь для UI (локальная, потокобезопасная)
    ui_queue: "queue.Queue[Tuple[str, np.ndarray]]" = queue.Queue(maxsize=8)

    stop_event_threads = Event()
    stop_event_proc = MPEvent()

    cams = selected_cams or list(CAM_SOURCES.keys())

    # Старт грабберов
    grabbers = []
    widgets = []

    for cam_id, spec in CAM_SOURCES.items():
        if spec.get("type") == "widget":
            wtype = spec.get("widget")
            if wtype == "calclock":
                w = CalClockWidget(cam_id, ui_queue, stop_event_threads)
            else:
                print(f"[{cam_id}] unknown widget '{wtype}', skipping")
                continue
            w.start()
            widgets.append(w)
            print(f"Started widget for {cam_id} -> {wtype}")
        else:
            # обычная RTSP
            src = spec.get("url")
            if not src:
                print(f"Source url for {cam_id} not found, skipping")
                continue
            g = FrameGrabber(cam_id, src, frame_queue, stop_event_threads, ui_queue=ui_queue, ui_stride=2)
            g.start()
            grabbers.append(g)
            print(f"Started grabber for {cam_id} -> {mask_url(src)}")

    # Один процесс-обработчик (как было)
    proc = Process(target=processor_proc, args=(frame_queue, stop_event_proc, DB_PATH, GLOBAL_ROI), daemon=True)

    proc.start()
    print("Started processor process")

    # ---- UI loop ----
    cv2.namedWindow("Monitor", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Monitor", 1920, 1080)  # 16:9
    latest: Dict[str, Optional[np.ndarray]] = {cid: None for cid in CAM_SOURCES.keys()}

    # NEW: состояние фокуса и хит-тест-карта
    focus_id: Optional[str] = None
    last_rects: Dict[str, tuple[int,int,int,int]] = {}
    widget_ids = [cid for cid, spec in CAM_SOURCES.items() if spec.get("type") == "widget"]

    # NEW: callback мыши для клика по ячейке
    def on_mouse(event, x, y, flags, param):
        nonlocal focus_id, last_rects
        if event == cv2.EVENT_LBUTTONDOWN:
            # найти, в какую прямоугольную область попали
            for cid, (x0,y0,x1,y1) in last_rects.items():
                if x0 <= x <= x1 and y0 <= y <= y1:
                    # если повторный клик по уже выбранной камере — снять фокус
                    focus_id = None if focus_id == cid else (cid if CAM_SOURCES[cid].get("type") != "widget" else None)
                    break

    cv2.setMouseCallback("Monitor", on_mouse)

    try:
        while True:
            # собрать свежие кадры без блокировки
            for _ in range(4):
                try:
                    cam_id, frame = ui_queue.get_nowait()
                    latest[cam_id] = frame.copy()
                except queue.Empty:
                    break

            # NEW: используем наш компоновщик с фокусом и фикс-виджетом
            canvas, last_rects = compose_focus_layout(
                latest,
                focus_id=focus_id,
                widget_ids=widget_ids,
                out_size=(1920, 1080),
                widget_size=(640, 360),
            )
            cv2.imshow("Monitor", canvas)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):  # q или ESC
                break
            # NEW: горячие клавиши для круга фокуса / сброса
            elif key == ord('0'):
                focus_id = None
            elif key in (ord('['), ord(']')):
                # переключение по списку только по "rtsp"-камерам
                rtsp_ids = [cid for cid, spec in CAM_SOURCES.items() if spec.get("type") != "widget"]
                if rtsp_ids:
                    if focus_id not in rtsp_ids:
                        focus_id = rtsp_ids[0]
                    else:
                        idx = rtsp_ids.index(focus_id)
                        if key == ord(']'):
                            focus_id = rtsp_ids[(idx + 1) % len(rtsp_ids)]
                        else:
                            focus_id = rtsp_ids[(idx - 1) % len(rtsp_ids)]

            time.sleep(0.01)

    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        stop_event_threads.set()
        stop_event_proc.set()
        try:
            frame_queue.put_nowait(None)
        except:
            pass
        for g in grabbers:
            g.join(timeout=3)
        proc.join(timeout=5)
        print("Stopped. Bye")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cams", nargs="*", help="Камеры для запуска (например: cam_1 cam_2). Если не указаны — запускаются все.")
    args = parser.parse_args()
    main(args.cams)
