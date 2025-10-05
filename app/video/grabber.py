# app/video/grabber.py

import queue
import time
from multiprocessing import Queue
from threading import Thread, Event
from typing import Optional

import cv2


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
