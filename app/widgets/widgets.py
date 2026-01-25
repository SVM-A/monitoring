# app/widgets/widgets.py
import threading
import time as _time
from typing import Optional, Dict, List

import numpy as np
from PyQt6 import QtCore, QtWidgets, QtGui
from PIL import Image, ImageDraw, ImageFont

from app.ui.designs import DS, FONT18, FONT16, FONT24, FONT20, FONT28
from app.video.recording import all_recordings
from app.widgets.base import WidgetBase
from app.core.config_cams import CAM_SOURCES, GLOBAL_ROI
from app.db.camera_registry import load_plategate_settings, save_plategate_settings

WIDGET_CONTROLLERS: Dict[str, object] = {}



class CalendarWidget(WidgetBase):
    """Только 2 календаря (текущий + следующий). Обновляется раз в 30 сек."""

    def run(self) -> None:
        def _render():
            return self.render_calendar_two_months()

        # Тихая частота: перерисовываем раз в 30 сек, чтобы часы в заголовке не мельтешили
        while not self.stop_event.is_set():
            self.push_frame(_render())
            for _ in range(30):
                if self.stop_event.is_set():
                    break
                _time.sleep(1)


class ClockWidget(WidgetBase):
    """Компактные цифровые часы."""

    def run(self) -> None:
        self.run_loop(lambda: self.render_digital_clock(), tick_seconds=1.0)


class HolidaysWidget(WidgetBase):
    """Блок «Праздники (14 дней)», кэш обновляется раз в 15 минут."""

    def run(self) -> None:
        last = 0.0
        cache_img: Optional[np.ndarray] = None
        while not self.stop_event.is_set():
            now = _time.time()
            if now - last > 900:  # 15 минут
                try:
                    cache_img = self.render_holidays_box()
                except Exception:
                    cache_img = self.render_holidays_box()  # фолбэк всё равно отрисует «нет праздников»
                last = now
            if cache_img is not None:
                self.push_frame(cache_img)
            _time.sleep(1)


class CalClockWidget(WidgetBase):
    """Комбинированная панель: 2 календаря + информер по флагам + аналоговые часы с цифровыми."""

    def run(self) -> None:
        self.run_loop(lambda: self.render_calendar_plus_clock(), tick_seconds=1.0)


class CaClockWeatherWidget(WidgetBase):
    """Комбинированная панель: 4 недели календаря (Пн-Вс) с погодой + часы + подробная погода на сегодня."""
    def run(self) -> None:
        self.run_loop(lambda: self.render_calendar_clock_weather_4w(W=1920, H=1080), tick_seconds=1.0)

# -----------------------------------------------------------------------------
# Панель "Шлагбаум / номера" как widget-source (как calclockweather)
# -----------------------------------------------------------------------------

class PlateGateWidget(WidgetBase):
    """Панель сценария въезда (пока только въезд).

    Рендерится как картинка (как камера), но с кликабельными зонами:
      - "Подтвердить" (auto)
      - "Принять ввод" (manual)
      - "Открыть" (ручное)
      - "Mute" (звук)

    Ввод номера — через QInputDialog при клике по зоне ввода.
    """

    _BTN_CONFIRM = (0.06, 0.58, 0.46, 0.66)
    _BTN_APPLY   = (0.54, 0.58, 0.94, 0.66)
    _BTN_OPEN    = (0.06, 0.70, 0.62, 0.78)
    _BTN_MUTE    = (0.68, 0.70, 0.94, 0.78)
    _FIELD_INPUT = (0.06, 0.46, 0.94, 0.54)
    _BTN_SELECT_STREAM = (0.06, 0.32, 0.60, 0.40)
    _BTN_TOGGLE_RECOG  = (0.64, 0.32, 0.94, 0.40)

    def __init__(self, camera_id: str, ui_queue, stop_event, plate_control_queue):
        super().__init__(camera_id, ui_queue, stop_event)
        self._lock = threading.Lock()

        self.entry_motion: bool = False
        self.entry_status: str = "Ожидание автомобиля"
        self.entry_plate_auto: str = ""
        self.entry_plate_manual: str = ""
        self._wait_elapsed: int = 0
        self._alarm_fired: bool = False
        self.alarm_muted: bool = False
        self._log: List[str] = []

        self.plate_control_queue = plate_control_queue

        # persistent settings
        st = load_plategate_settings()
        self.control_camera_id: str = st.get("control_camera_id") or ""
        self.recognition_enabled: bool = bool(st.get("recognition_enabled") or False)

        if self.recognition_enabled:
            self.entry_status = "Распознавание включено. Ожидание движения в зоне контроля…"
        else:
            self.entry_status = "Распознавание выключено."

        # При старте приложения — восстановим режим в processor_proc
        # (очередь уже существует, процесс может стартовать чуть позже — не страшно)
        try:
            if self.control_camera_id:
                self.plate_control_queue.put_nowait({"type": "plate_set_camera", "camera_id": self.control_camera_id})
            if self.recognition_enabled:
                self.plate_control_queue.put_nowait({"type": "plate_enable"})
            else:
                self.plate_control_queue.put_nowait({"type": "plate_disable"})
        except Exception:
            pass


        WIDGET_CONTROLLERS[self.camera_id] = self

    def _append_log(self, text: str) -> None:
        ts = _time.strftime("%H:%M:%S")
        self._log.append(f"{ts}  {text}")
        self._log = self._log[-12:]

    def _start_wait(self) -> None:
        self._wait_elapsed = 0
        self._alarm_fired = False

    def _stop_wait(self) -> None:
        self._wait_elapsed = 0
        self._alarm_fired = False

    def _tick_wait(self) -> None:
        with self._lock:
            if not self.entry_motion:
                return
            self._wait_elapsed += 1
            if self._wait_elapsed % 5 == 0:
                self._append_log(f"Ожидание действия охранника: {self._wait_elapsed} с.")
            if (not self._alarm_fired) and self._wait_elapsed >= 10:
                self._alarm_fired = True
                self.entry_status = "⚠ Нет подтверждения/действия более 10 секунд."
                self._append_log("⚠ Тревога: авто стоит без подтверждения >10с.")
                if not self.alarm_muted:
                    self._append_log("Звуковое оповещение (заглушка): сигнал тревоги.")

    # Заглушки действий
    def action_confirm(self) -> None:
        with self._lock:
            plate = self.entry_plate_auto.strip()
            if not plate:
                self.entry_status = "Нет распознанного номера для подтверждения."
                self._append_log("Нечего подтверждать: распознанный номер пустой.")
                return
            self.entry_status = f"Номер {plate} подтверждён. Открываем шлагбаум…"
            self._append_log(f"Подтверждён номер (auto): {plate}. Открываем шлагбаум.")
            self._stop_wait()
        self._append_log("Команда открыть шлагбаум (заглушка) отправлена.")

    def action_manual_apply(self, plate_text: str) -> None:
        plate_text = (plate_text or "").strip().upper()
        if not plate_text:
            with self._lock:
                self.entry_status = "Введите номер вручную, если распознавание ошиблось."
                self._append_log("Ввод номера пустой — ничего не делаем.")
            return
        with self._lock:
            self.entry_plate_manual = plate_text
            self.entry_status = f"Ручной номер {plate_text} принят. Открываем шлагбаум…"
            self._append_log(f"Ручной ввод: {plate_text}. Сохраняем в датасет (позже) и открываем.")
            self._stop_wait()
        self._append_log("Сохранение training-sample (заглушка): кадр+номер.")
        self._append_log("Команда открыть шлагбаум (заглушка) отправлена.")

    def action_open_manual(self) -> None:
        with self._lock:
            self.entry_status = "Ручное открытие шлагбаума."
            self._append_log("Ручное открытие шлагбаума (без номера).")
            self._stop_wait()
        self._append_log("Команда открыть шлагбаум (заглушка) отправлена.")

    def action_toggle_mute(self) -> None:
        with self._lock:
            self.alarm_muted = not self.alarm_muted
            self._append_log("Звуковое оповещение отключено." if self.alarm_muted else "Звуковое оповещение включено.")
            if self.alarm_muted and self._alarm_fired:
                self._alarm_fired = False

    def handle_ui_click(self, rel_x: float, rel_y: float, parent: QtWidgets.QWidget) -> bool:
        def hit(r):
            x0, y0, x1, y1 = r
            return x0 <= rel_x <= x1 and y0 <= rel_y <= y1

        if hit(self._BTN_SELECT_STREAM):
            self.action_select_stream(parent)
            return True

        if hit(self._BTN_TOGGLE_RECOG):
            self.action_toggle_recognition()
            return True

        if hit(self._BTN_CONFIRM):
            self.action_confirm()
            return True

        if hit(self._BTN_APPLY):
            with self._lock:
                cur = self.entry_plate_manual or ""
            if not cur:
                text, ok = QtWidgets.QInputDialog.getText(parent, "Ручной ввод номера", "Введите номер:")
                if ok:
                    self.action_manual_apply(text)
            else:
                self.action_manual_apply(cur)
            return True

        if hit(self._FIELD_INPUT):
            text, ok = QtWidgets.QInputDialog.getText(parent, "Ручной ввод номера", "Введите номер:")
            if ok:
                self.action_manual_apply(text)
            return True

        if hit(self._BTN_OPEN):
            self.action_open_manual()
            return True

        if hit(self._BTN_MUTE):
            self.action_toggle_mute()
            return True

        return False

    def _render_panel(self, W: int = 1920, H: int = 1080) -> np.ndarray:
        # локальные алиасы на палитру
        C = DS.color

        def rr(draw: ImageDraw.ImageDraw, box, r: int, fill, outline=None, w: int = 1):
            # PIL умеет rounded_rectangle
            draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=w)

        def card(draw: ImageDraw.ImageDraw, box):
            rr(draw, box, r=DS.radii.lg, fill=C.panel, outline=C.grid, w=2)

        with self._lock:
            status = self.entry_status
            motion = self.entry_motion
            auto_plate = self.entry_plate_auto
            manual_plate = self.entry_plate_manual
            muted = self.alarm_muted
            wait = self._wait_elapsed
            log_lines = list(self._log)

        img = Image.new("RGB", (W, H), C.bg)
        d = ImageDraw.Draw(img)

        pad = 36
        d.text((pad, pad), "Шлагбаум — ВЪЕЗД", fill=C.text, font=FONT28 or FONT24)

        badge = "ДВИЖЕНИЕ" if motion else "ОЖИДАНИЕ"
        badge_fill = C.ok if motion else C.sub
        rr(d, (W - 360, pad - 4, W - pad, pad + 40), r=14, fill=badge_fill)
        d.text((W - 340, pad + 4), badge, fill=C.bg, font=FONT18 or FONT16)

        y = pad + 70
        card(d, (pad, y, W - pad, y + 220))
        d.text((pad + 24, y + 18), "Статус", fill=C.sub, font=FONT18 or FONT16)
        d.text((pad + 24, y + 54), status, fill=C.text, font=FONT24 or FONT20)

        d.text((pad + 24, y + 118), f"Auto:  {auto_plate or '—'}", fill=C.text, font=FONT20)
        d.text((pad + 24, y + 154), f"Manual: {manual_plate or '—'}", fill=C.text, font=FONT20)
        d.text((W - pad - 420, y + 154), f"Ожидание: {wait:>2} c", fill=C.sub, font=FONT18 or FONT16)

        # поле ввода (как “input”)
        x0, y0, x1, y1 = self._FIELD_INPUT
        bx0 = int(x0 * W);
        by0 = int(y0 * H);
        bx1 = int(x1 * W);
        by1 = int(y1 * H)
        rr(d, (bx0, by0, bx1, by1), r=18, fill=C.cell, outline=C.grid, w=2)
        d.text((bx0 + 18, by0 + 14), manual_plate or "Ввести номер…", fill=C.text, font=FONT24 or FONT20)

        def draw_btn(r, title, kind="primary"):
            x0, y0, x1, y1 = r
            rx0 = int(x0 * W);
            ry0 = int(y0 * H);
            rx1 = int(x1 * W);
            ry1 = int(y1 * H)

            if kind == "primary":
                fill = C.ok
                txt = C.bg
            elif kind == "danger":
                fill = C.alert
                txt = C.bg
            else:
                fill = C.cell
                txt = C.text

            rr(d, (rx0, ry0, rx1, ry1), r=18, fill=fill, outline=C.grid, w=2)
            bbox = d.textbbox((0, 0), title, font=FONT20 or FONT18)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            d.text((rx0 + (rx1 - rx0 - tw) // 2, ry0 + (ry1 - ry0 - th) // 2), title, fill=txt, font=FONT20 or FONT18)

        # Кнопки управления распознаванием
        with self._lock:
            cam_label = self.control_camera_id or "—"
            recog = self.recognition_enabled

        draw_btn(self._BTN_SELECT_STREAM, f"Контроль: {cam_label}", "secondary")
        draw_btn(self._BTN_TOGGLE_RECOG, "Распознавание: ON" if recog else "Распознавание: OFF", "primary" if recog else "secondary")

        draw_btn(self._BTN_CONFIRM, "Подтвердить (auto)", "primary")
        draw_btn(self._BTN_APPLY, "Принять (manual)", "primary")
        draw_btn(self._BTN_OPEN, "Открыть шлагбаум", "danger")
        draw_btn(self._BTN_MUTE, "Mute: ON" if muted else "Mute: OFF", "secondary")

        # лог
        ly0 = int(0.80 * H)
        card(d, (pad, ly0, W - pad, H - pad))
        d.text((pad + 24, ly0 + 16), "Лог", fill=C.sub, font=FONT18 or FONT16)
        yy = ly0 + 50
        for line in log_lines[-8:]:
            d.text((pad + 24, yy), line, fill=C.text, font=FONT16)
            yy += 28

        # PIL -> OpenCV (BGR)
        return np.array(img)[:, :, ::-1].copy()

    def action_select_stream(self, parent: QtWidgets.QWidget) -> None:
        # список только RTSP (и вообще не widget)
        items = []

        # 1) Архивные записи
        recs = all_recordings()
        for rec in recs.values():
            items.append(rec.id)
            if rec.camera_id in GLOBAL_ROI:
                items.append(f"{rec.id} [ROI]")

        # 2) Живые камеры (не-виджеты)
        for cid, spec in CAM_SOURCES.items():
            if (spec or {}).get("type") != "widget":
                items.append(cid)
                if cid in GLOBAL_ROI:
                    items.append(f"{cid} [ROI]")

        # уникализируем, сортируем
        cam_ids = sorted(set(items))

        cur = self.control_camera_id or (cam_ids[0] if cam_ids else "")
        if not cam_ids:
            with self._lock:
                self.entry_status = "Нет доступных потоков для контроля."
            return

        sel, ok = QtWidgets.QInputDialog.getItem(
            parent,
            "Выбор потока для контроля",
            "Камера:",
            cam_ids,
            cam_ids.index(cur) if cur in cam_ids else 0,
            False
        )
        if not ok:
            return

        with self._lock:
            chosen = str(sel)
            self.control_camera_id = chosen
            base_id = chosen[:-len(" [ROI]")] if chosen.endswith(" [ROI]") else chosen
        # persist + отправим в процесс
        save_plategate_settings(control_camera_id=base_id, recognition_enabled=self.recognition_enabled)
        try:
            self.plate_control_queue.put_nowait({"type": "plate_set_camera", "camera_id": base_id})
        except Exception:
            pass

    def action_toggle_recognition(self) -> None:
        with self._lock:
            self.recognition_enabled = not self.recognition_enabled
            enabled = self.recognition_enabled
            self._append_log("Распознавание включено." if enabled else "Распознавание выключено.")
            if enabled:
                self.entry_status = "Распознавание включено. Ожидание движения в зоне контроля…"
            else:
                self.entry_status = "Распознавание выключено."
                self.entry_plate_auto = ""

        save_plategate_settings(control_camera_id=self.control_camera_id, recognition_enabled=self.recognition_enabled)

        try:
            if self.control_camera_id:
                self.plate_control_queue.put_nowait({"type": "plate_set_camera", "camera_id": self.control_camera_id})
            self.plate_control_queue.put_nowait({"type": "plate_enable" if enabled else "plate_disable"})
        except Exception:
            pass

    def handle_plate_event(self, ev: dict) -> None:
        """
        Сюда прилетают события из processor_proc через ProcEventBus (Qt thread).
        Аккуратно обновляем внутренние поля под lock.
        """
        et = (ev or {}).get("type")

        if et == "plate_status":
            cam_id = str(ev.get("camera_id") or "")
            msg = str(ev.get("message") or "")

            # показываем статусы либо глобальные, либо относящиеся к выбранной камере
            with self._lock:
                if not cam_id or cam_id == self.control_camera_id:
                    if msg:
                        self.entry_status = msg
            return

        if et == "plate_detection":
            cam_id = str(ev.get("camera_id") or "")
            text = str(ev.get("text") or "").strip().upper()
            if not text:
                return

            with self._lock:
                if cam_id != self.control_camera_id:
                    return
                self.entry_plate_auto = text
                self.entry_status = f"Номер распознан: {text}. Ожидание подтверждения…"
                self.entry_motion = True
                self._start_wait()
                self._append_log(f"Авто-номер: {text}")
            return


    def run(self) -> None:
        def _render():
            # тик ожидания (10 секунд, тревога и т.д.)
            self._tick_wait()
            return self._render_panel(1920, 1080)

        # как у calclockweather: ловим исключения и продолжаем жить
        self.run_loop(_render, tick_seconds=0.5)


