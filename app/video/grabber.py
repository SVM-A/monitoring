# app/video/grabber.py

import queue
import time
from multiprocessing import Queue
from threading import Thread, Event
from typing import Optional

import cv2

from app.core.config import get_debug_flags


try:
    # Новый API OpenCV 4.x
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    # На всякий случай для старых версий
    try:
        cv2.setLogLevel(0)
    except Exception:
        pass

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
        self._pending_src = None
        self._switch_needed = False

    def set_source(self, new_src: str):
        """Запросить смену источника (на прокси/обратно)."""
        self._pending_src = new_src
        self._switch_needed = True

    def _switch_capture(self):
        """Аккуратно переключить cap на новый URL, избегая «чёрного экрана»."""
        import cv2
        new_cap = cv2.VideoCapture(self._pending_src, cv2.CAP_FFMPEG)
        if not new_cap or not new_cap.isOpened():
            new_cap = cv2.VideoCapture(self._pending_src)
            if not new_cap or not new_cap.isOpened():
                print(f"[grabber] cannot switch to new src: {self._pending_src}")
                self._pending_src = None
                self._switch_needed = False
                return
        if getattr(self, "cap", None):
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = new_cap
        self.src = self._pending_src
        self._pending_src = None
        self._switch_needed = False
        print(f"[grabber] switched to: {self.src}")

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
                if self._switch_needed and self._pending_src:
                    self._switch_capture()
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    print(f"[{self.camera_id}] frame read failed, reconnecting...")
                    self.cap.release()
                    self.cap = None
                    time.sleep(self.reconnect_delay)
                    continue
                if get_debug_flags().GRABBER_DEBUG:
                    print(f"[{self.camera_id}] frame ok, enqueue to UI (every {self.ui_stride})")
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
