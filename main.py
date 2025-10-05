# main.py

import cv2
import time
import argparse
import queue
import signal
from typing import Dict, Optional, Tuple
from threading import Event
from multiprocessing import Process, Queue, Event as MPEvent
import numpy as np

from app.core.constants import DB_PATH, MAX_QUEUE_SIZE, CAM_SOURCES, GLOBAL_ROI
from app.db.utils import init_db
from app.proccesor.worker import processor_proc
from app.ui.layout import compose_focus_layout
from app.util.mask import mask_url
from app.video.grabber import FrameGrabber
from app.widgets.widgets import CalClockWidget


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
    terminate = False

    def _handle_term(signum, frame):
        nonlocal terminate
        terminate = True

    signal.signal(signal.SIGINT, _handle_term)
    signal.signal(signal.SIGTERM, _handle_term)

    # ---- UI loop ----
    WINDOW_NAME = "Monitor"
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1920, 1080)

    exit_requested = False  # ← добавить: флаг выхода по кнопке
    ui_close_rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # ← добавить: актуальный прямоугольник кнопки

    latest: Dict[str, Optional[np.ndarray]] = {cid: None for cid in CAM_SOURCES.keys()}

    # NEW: состояние фокуса и хит-тест-карта
    focus_id: Optional[str] = None
    last_rects: Dict[str, tuple[int,int,int,int]] = {}
    widget_ids = [cid for cid, spec in CAM_SOURCES.items() if spec.get("type") == "widget"]

    # NEW: callback мыши для клика по ячейке
    def on_mouse(event, x, y, flags, param):
        nonlocal focus_id, last_rects, exit_requested, ui_close_rect  # ← добавить новые nonlocal
        if event == cv2.EVENT_LBUTTONDOWN:
            # 1) Клик по кнопке "Закрыть"
            x0, y0, x1, y1 = ui_close_rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                exit_requested = True
                return

            # 2) Клик по ячейке камеры (как было)
            for cid, (x0, y0, x1, y1) in last_rects.items():
                if x0 <= x <= x1 and y0 <= y <= y1:
                    focus_id = None if focus_id == cid else (cid if CAM_SOURCES[cid].get("type") != "widget" else None)
                    break

    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

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

            # ↓↓↓ ДОБАВИТЬ: рисуем кнопку "Закрыть"
            # h, w = canvas.shape[:2]
            # ui_close_rect = (w - 150, 20, w - 20, 60)  # (x0, y0, x1, y1)
            #
            # # фон и рамка
            # cv2.rectangle(canvas, (ui_close_rect[0], ui_close_rect[1]), (ui_close_rect[2], ui_close_rect[3]),
            #               (40, 40, 50), thickness=-1)
            # cv2.rectangle(canvas, (ui_close_rect[0], ui_close_rect[1]), (ui_close_rect[2], ui_close_rect[3]),
            #               (90, 90, 100), thickness=1)



            # ASCII-лейбл по центру (если нужен)
            # label = "EXIT"  # <— кириллица не поддерживается в cv2.putText
            # font = cv2.FONT_HERSHEY_SIMPLEX
            # scale, thick = 0.6, 2
            # (text_w, text_h), base = cv2.getTextSize(label, font, scale, thick)
            # tx = ui_close_rect[0] + (ui_close_rect[2] - ui_close_rect[0] - text_w) // 2
            # ty = ui_close_rect[1] + (ui_close_rect[3] - ui_close_rect[1] + text_h) // 2
            # # cv2.putText(canvas, label, (tx, ty), font, scale, (230, 230, 230), thick, cv2.LINE_AA)

            cv2.imshow(WINDOW_NAME, canvas)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
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
            # 2) закрытие по крестику системного окна
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break

            # 3) закрытие по кнопке в UI
            if exit_requested:
                break
            if terminate:
                break
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
