# app/proccesor/worker.py

import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np
import time

from app.detector.pipeline import PlateDetectionPipeline
from app.core.config_cams import PLATE_YOLO_MODEL_PATH
from app.db.camera_registry import save_detection
from app.video.ffproxy import apply_roi
from app.core.config_cams import PLATE_DETECTION_CAMERAS


# Процесс, который декодирует JPEG-байты, применяет ROI и выполняет распознавание.
#
# Сейчас:
#   - используется простая заглушка detect_plate(frame) -> (None, None),
#     чтобы приложение работало без реального детектора.
#
# В будущем:
#   - detect_plate будет принимать расширенный контекст:
#         detect_plate(proc_frame, camera_id=camera_id, roi_conf=roi_conf, ts=ts)
#   - внутри detect_plate будет создаваться/использоваться PlateDetectionPipeline,
#     который:
#         * применяет ROI (если нужно),
#         * через RoiMotionGate решает, когда запускать тяжёлый детектор,
#         * фильтрует дубликаты по времени/позиции,
#         * возвращает PlateDetectionResult (text, bbox, score, ...).


def processor_proc(in_queue: Queue, stop_event: MPEvent, db_path: str, roi_config: dict):
    """
        Каркас использования пайплайна (на будущее):

        # 1) Получаем кадр и ROI
        camera_id, jpg_bytes = item
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        roi_conf = roi_config.get(camera_id)

        # 2) Вызов detect_plate с контекстом
        import time
        plate, bbox = detect_plate(
            frame,
            camera_id=camera_id,
            roi_conf=roi_conf,
            ts=time.time(),
        )

        # 3) Запись в БД, если детекция успешна
        if plate:
            save_detection(conn, camera_id, plate, bbox=bbox, extra={"detected_by": "pipeline"})

        На данном этапе это только комментарий/ТЗ.
        Реальная логика ниже остаётся максимально простой.
    """
    # Открываем DB в процессе
    conn = sqlite3.connect(db_path, check_same_thread=False)
    pipeline = PlateDetectionPipeline(
        model_path=PLATE_YOLO_MODEL_PATH,
        device="auto",
    )

    while not stop_event.is_set():
        try:
            item = in_queue.get(timeout=0.5)  # ждём полсекунды
        except Exception:
            continue
        if item is None:  # sentinel для завершения
            break
        camera_id, jpg_bytes = item

        # --- Фильтр по камерам: детекцию делаем только там, где она включена в конфиге ---
        # Это независимо от того, есть ROI или нет.
        if PLATE_DETECTION_CAMERAS and camera_id not in PLATE_DETECTION_CAMERAS:
            # для остальных камер просто ничего не считаем (но UI всё равно их показывает)
            continue

        # ---------------------------------------------------------------
        # декодируем
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # Применяем ROI, если есть
        roi_conf = roi_config.get(camera_id)

        ts = time.time()
        result = pipeline.process_frame(
            camera_id=camera_id,
            frame=frame,       # полный кадр (pipeline сам применит ROI)
            roi_conf=roi_conf,
            ts=ts,
        )

        if result and result.text:
            print(f"[{camera_id}] plate detected: {result.text} score={result.score:.3f} bbox={result.bbox}")
            save_detection(
                conn,
                camera_id,
                result.text,
                bbox=list(result.bbox),
                extra={"detected_by": "yolo+tesseract", "score": result.score},
            )

    conn.close()
    print("Processor stopped")
