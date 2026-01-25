# app/proccesor/worker.py

from queue import Empty
import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np
import time

from app.detector.pipeline import PlateDetectionPipeline
from app.core.config_cams import PLATE_YOLO_MODEL_PATH
from app.db.camera_registry import save_detection


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


def processor_proc(
        in_queue: Queue,
        control_queue: Queue,
        events_queue: Queue,
        stop_event: MPEvent,
        db_path: str,
        roi_config: dict
):
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

    # runtime state (управляется из UI)
    enabled: bool = False
    target_camera_id: str = ""

    # сообщаем UI что процесс детекции поднялся
    try:
        events_queue.put_nowait({
            "type": "plate_status",
            "stage": "ready",
            "message": "Модуль распознавания готов. Ожидание команды включения…",
            "camera_id": "",
            "ts": time.time(),
        })
    except Exception:
        pass

    while not stop_event.is_set():
        # --- команды из UI (не блокируемся) ---
        for _ in range(20):
            try:
                cmd = control_queue.get_nowait()
            except Exception:
                break
            if not isinstance(cmd, dict):
                continue

            ctype = cmd.get("type")
            if ctype == "plate_set_camera":
                target_camera_id = str(cmd.get("camera_id") or "")
                try:
                    events_queue.put_nowait({
                        "type": "plate_status",
                        "stage": "config",
                        "message": f"Камера контроля выбрана: {target_camera_id or '—'}",
                        "camera_id": target_camera_id,
                        "ts": time.time(),
                    })
                except Exception:
                    pass

            elif ctype == "plate_enable":
                enabled = True
                try:
                    events_queue.put_nowait({
                        "type": "plate_status",
                        "stage": "enabled",
                        "message": "Распознавание включено. Ожидание движения в зоне контроля…",
                        "camera_id": target_camera_id,
                        "ts": time.time(),
                    })
                except Exception:
                    pass

            elif ctype == "plate_disable":
                enabled = False
                try:
                    events_queue.put_nowait({
                        "type": "plate_status",
                        "stage": "disabled",
                        "message": "Распознавание выключено.",
                        "camera_id": target_camera_id,
                        "ts": time.time(),
                    })
                except Exception:
                    pass
        try:
            item = in_queue.get(timeout=0.5)  # ждём полсекунды
        except Exception:
            continue
        if item is None:  # sentinel для завершения
            break
        camera_id, jpg_bytes = item

        # если распознавание выключено — вообще не тратим ресурсы
        if not enabled:
            continue

        # если камера контроля не выбрана — тоже ничего не делаем
        if not target_camera_id:
            continue

        # обрабатываем только выбранную камеру
        if camera_id != target_camera_id:
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

        try:
            events_queue.put_nowait({
                "type": "plate_status",
                "stage": "detect",
                "message": "Поиск номерного знака…",
                "camera_id": camera_id,
                "ts": ts,
            })
        except Exception:
            pass

        result = pipeline.process_frame(
            camera_id=camera_id,
            frame=frame,  # полный кадр (pipeline сам применит ROI)
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
            # bbox приходит в координатах ROI-кадра. Для прямоугольного crop ROI
            # можно получить full-bbox, добавив смещения x/y.
            bbox_roi = list(result.bbox) if result.bbox else None
            bbox_full = None
            try:
                if bbox_roi and isinstance(roi_conf, dict) and roi_conf.get("type") == "rect":
                    ox = int(roi_conf.get("x") or 0)
                    oy = int(roi_conf.get("y") or 0)
                    x, y, w, h = map(int, bbox_roi)
                    bbox_full = [x + ox, y + oy, w, h]
                else:
                    bbox_full = bbox_roi
            except Exception:
                bbox_full = bbox_roi

            try:
                events_queue.put_nowait({
                    "type": "plate_detection",
                    "camera_id": camera_id,
                    "text": result.text,
                    "score": float(result.score or 0.0),
                    "bbox_roi": bbox_roi,
                    "bbox_full": bbox_full,
                    "ts": ts,
                })
            except Exception:
                pass

    conn.close()
    print("Processor stopped")
