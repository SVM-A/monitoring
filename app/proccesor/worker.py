# app/proccesor/worker.py

import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np

from app.db.camera_registry import save_detection
from app.detector.plate_stub import detect_plate
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
        proc_frame = apply_roi(frame, roi_conf)

        # ---- ТЕКУЩАЯ ЛОГИКА РАСПОЗНАВАНИЯ (ЗАГЛУШКА) ----
        # detect_plate сейчас принимает только кадр и всегда возвращает (None, None).
        # Интерфейс уже подготовлен к расширению, но мы им пока не пользуемся:
        #
        #   plate, bbox = detect_plate(
        #       proc_frame,
        #       camera_id=camera_id,
        #       roi_conf=roi_conf,
        #       ts=time.time(),
        #   )
        #
        # Чтобы не ломать приложение и не зависеть от нереализованного пайплайна,
        # используем простой вызов:
        plate, bbox = detect_plate(proc_frame)

        if plate:
            print(f"[{camera_id}] plate detected: {plate} bbox={bbox}")
            save_detection(conn, camera_id, plate, bbox=bbox, extra={"detected_by": "stub"})
        # ----------------------------------------------

        # Ниже оставляем "выхолощенный" псевдокод для напоминания,
        # как будет выглядеть логика напрямую через motion_gate/pipeline:

        # PSEUDO:
        # ts = time.time()
        # if not pipeline.motion_gate.update_and_check(camera_id, proc_frame, ts):
        #     continue
        # buffer = pipeline.motion_gate.pop_buffer(camera_id)
        # buffer.append(proc_frame)
        # best_frame = pipeline._select_best_frame(buffer)
        # result = pipeline.process_frame(camera_id, best_frame, roi_conf, ts)
        # if result is not None:
        #     save_detection(conn, camera_id, result.text, bbox=result.bbox, extra={"detected_by": "pipeline"})

    conn.close()
    print("Processor stopped")
