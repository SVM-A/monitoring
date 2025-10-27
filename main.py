# main.py
import argparse
import queue
from threading import Event
from multiprocessing import Process, Queue, Event as MPEvent
from typing import Tuple
import numpy as np
from pathlib import Path


from app.core.constants import DB_PATH_DETECTION, MAX_QUEUE_SIZE, CAM_SOURCES, GLOBAL_ROI
from app.db.utils import init_db
from app.proccesor.worker import processor_proc
from app.util.mask import mask_url
from app.video.grabber import FrameGrabber
from app.camera.camera_bootstrap import load_cameras, prepare_runtime

# запуск Qt-приложения
from app.qt.app import run_qt_app


def main(selected_cams):
    # 1) БД
    conn = init_db(DB_PATH_DETECTION)
    conn.close()


    # 2) Очереди/события
    frame_queue = Queue(maxsize=MAX_QUEUE_SIZE)  # JPEG в процесс-обработчик
    ui_queue: "queue.Queue[Tuple[str, np.ndarray]]" = queue.Queue(maxsize=8)  # кадры для UI

    stop_event_threads = Event()
    stop_event_proc = MPEvent()

    # 3) Старт источников
    grabbers = []
    widgets = []

    # Собираем карту {cam_id: final_rtsp_url} из CAM_SOURCES
    cam_urls = {}
    for cam_id in (selected_cams or list(CAM_SOURCES.keys())):
        spec = CAM_SOURCES.get(cam_id, {})
        if spec.get("type") == "rtsp" and spec.get("url"):
            cam_urls[cam_id] = spec["url"]


    # Применяем настройки: если onvif доступен → прямое применение; иначе → прокси.
    runtime_map = prepare_runtime(load_cameras())

    # Теперь стартуем виджеты/грабберы
    cams = selected_cams or list(CAM_SOURCES.keys())
    for cam_id in cams:
        spec = CAM_SOURCES.get(cam_id, {})
        if not spec:
            print(f"[{cam_id}] spec not found, skip")
            continue

        if spec.get("type") == "widget":
            from app.widgets.widgets import (
                CalClockWidget, CaClockWeatherWidget,
                CalendarWidget, ClockWidget, HolidaysWidget
            )
            wtype = spec.get("widget")
            if wtype == "calclock":
                w = CalClockWidget(cam_id, ui_queue, stop_event_threads)
            elif wtype == "calclockweather":
                w = CaClockWeatherWidget(cam_id, ui_queue, stop_event_threads)
            elif wtype == "calendar":
                w = CalendarWidget(cam_id, ui_queue, stop_event_threads)
            elif wtype == "clock":
                w = ClockWidget(cam_id, ui_queue, stop_event_threads)
            elif wtype == "holidays":
                w = HolidaysWidget(cam_id, ui_queue, stop_event_threads)
            else:
                print(f"[{cam_id}] unknown widget '{wtype}', skip")
                continue
            w.start()
            widgets.append(w)
            print(f"Widget started for {cam_id} -> {wtype}")
        else:
            # Берём runtime_url, если он есть (после применения настроек), иначе — исходный url
            run_url = runtime_map.get(cam_id).runtime_url if cam_id in runtime_map else spec.get("url")
            if not run_url:
                print(f"[{cam_id}] url not found, skip")
                continue

            g = FrameGrabber(
                cam_id, run_url, frame_queue, stop_event_threads,
                ui_queue=ui_queue, ui_stride=2
            )
            g.start()
            grabbers.append(g)
            print(f"Grabber started for {cam_id} -> {mask_url(run_url)}")

    # 4) Процесс-обработчик
    proc = Process(
        target=processor_proc,
        args=(frame_queue, stop_event_proc, DB_PATH_DETECTION, GLOBAL_ROI),
        daemon=True
    )
    proc.start()

    # 5) Запуск Qt
    run_qt_app(
        ui_queue=ui_queue,
        stop_event_threads=stop_event_threads,
        stop_event_proc=stop_event_proc,
        grabbers=grabbers,
        proc=proc
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cams", nargs="*", help="cam ids to run, default: all")
    args = parser.parse_args()
    main(args.cams)
