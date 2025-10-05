# app/proccesor/worker.py

import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np

from app.db.utils import save_detection
from app.detector.plate_stub import detect_plate
from app.video.roi import apply_roi


# Процесс, который декодирует JPEG-байты, применяет ROI и выполняет распознавание.

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