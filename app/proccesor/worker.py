from queue import Empty
import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np
import time

from app.detector.pipeline import PlateDetectionPipeline
from app.core.config_cams import PLATE_YOLO_MODEL_PATH
from app.db.camera_registry import save_detection


def processor_proc(
    in_queue: Queue,
    control_queue: Queue,
    events_queue: Queue,
    stop_event: MPEvent,
    db_path: str,
    roi_config: dict
):
    """
    Процесс детекции:
      - принимает кадры (jpeg bytes) из in_queue
      - принимает команды (выбор камеры / enable / disable) из control_queue
      - шлёт события (статусы / детекции) в events_queue
      - пишет распознанные номера в sqlite

    Статусы:
      boot / ready / config / enabled / disabled
      decode / roi / motion_check / motion_trigger / yolo / ocr / found / dup / none / error / idle
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)

    # -------- pipeline init --------
    last_stage: str = ""
    last_stage_ts: float = 0.0
    last_idle_ts: float = 0.0

    def push_status(stage: str, message: str, cam: str = ""):
        """
        Отправляет статус в UI с троттлингом (не спамит одинаковыми стадиями).
        """
        nonlocal last_stage, last_stage_ts
        now = time.time()

        # если стадия та же и прошло мало времени — не спамим
        if stage == last_stage and (now - last_stage_ts) < 0.30:
            return

        last_stage = stage
        last_stage_ts = now

        try:
            events_queue.put_nowait({
                "type": "plate_status",
                "stage": stage,
                "message": message,
                "camera_id": cam or "",
                "ts": now,
            })
        except Exception:
            pass

    # сразу сообщаем что грузимся
    push_status("boot", "Загружаю модуль распознавания…")

    pipeline = PlateDetectionPipeline(
        model_path=PLATE_YOLO_MODEL_PATH,
        device="auto",
    )

    push_status("ready", "Модуль распознавания готов. Выберите камеру и включите распознавание…")

    # -------- runtime state --------
    enabled: bool = False
    target_camera_id: str = ""

    def normalize_camera_id(s: str) -> str:
        # worker понимает только базовый id
        if not s:
            return ""
        s = str(s)
        if s.endswith(" [ROI]"):
            s = s[:-len(" [ROI]")]
        return s

    def is_recording_source_id(s: str) -> bool:
        """
        Архивные записи у тебя имеют id вида: rec::....
        """
        return str(s or "").startswith("rec::")

    def maybe_idle(cam: str):
        """
        Пишем idle не чаще чем раз в ~1.5 сек.
        """
        nonlocal last_idle_ts
        now = time.time()
        if now - last_idle_ts >= 1.5:
            last_idle_ts = now
            push_status("idle", "Ожидаю движение в зоне контроля…", cam)

    while not stop_event.is_set():
        # -------- commands from UI --------
        for _ in range(30):
            try:
                cmd = control_queue.get_nowait()
            except Exception:
                break
            if not isinstance(cmd, dict):
                continue

            ctype = cmd.get("type")

            if ctype == "plate_set_camera":
                target_camera_id = normalize_camera_id(cmd.get("camera_id") or "")
                push_status("config", f"Камера контроля выбрана: {target_camera_id or '—'}", target_camera_id)

            elif ctype == "plate_enable":
                enabled = True
                if target_camera_id:
                    push_status("enabled", "Распознавание включено. Ожидаю движение в зоне контроля…", target_camera_id)
                else:
                    push_status("enabled", "Распознавание включено. Выберите камеру контроля.", "")

            elif ctype == "plate_disable":
                enabled = False
                push_status("disabled", "Распознавание выключено.", target_camera_id)

        # -------- frame input --------
        try:
            item = in_queue.get(timeout=0.5)
        except Exception:
            continue

        if item is None:
            break

        camera_id, jpg_bytes = item

        # runtime filters
        if not enabled:
            continue
        if not target_camera_id:
            continue
        if camera_id != target_camera_id:
            continue

        ts = time.time()

        # -------- decode --------
        push_status("decode", "Получен кадр. Декодирование…", camera_id)

        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            push_status("error", "Ошибка декодирования кадра.", camera_id)
            continue

        roi_conf = roi_config.get(camera_id)

        # -------- stage callback for pipeline (если поддерживается) --------
        def on_stage(stage_name: str, payload: dict):
            # stage_name -> человеческий текст
            if stage_name == "roi":
                push_status("roi", "Применяю зону контроля (ROI)…", camera_id)
            elif stage_name == "motion_check":
                push_status("motion_check", "Проверяю движение…", camera_id)
            elif stage_name == "motion_trigger":
                push_status("motion_trigger", "Движение подтверждено. Фиксирую лучший кадр…", camera_id)
            elif stage_name == "yolo":
                push_status("yolo", "Ищу номерной знак…", camera_id)
            elif stage_name == "ocr":
                push_status("ocr", "Распознаю символы номера…", camera_id)
            elif stage_name == "dup":
                push_status("dup", "Похоже на дубль — пропускаю.", camera_id)
            elif stage_name == "none":
                # не спамим "не найден" — лучше idle
                maybe_idle(camera_id)
            elif stage_name == "idle":
                maybe_idle(camera_id)
            elif stage_name == "found":
                txt = (payload or {}).get("text") or ""
                if txt:
                    push_status("found", f"Номер распознан: {txt}. Ожидаю подтверждение…", camera_id)

        # -------- run pipeline --------
        result = None
        try:
            # Если ты уже добавил on_stage в pipeline.process_frame — будет подробная телеметрия.
            result = pipeline.process_frame(
                camera_id=camera_id,
                frame=frame,
                roi_conf=roi_conf,
                ts=ts,
                force_detect=is_recording_source_id(camera_id),
                on_stage=on_stage,
            )
        except TypeError:
            # Если on_stage ещё не добавлен — работаем по-старому, но статусы всё равно будут (упрощённо).
            push_status("roi", "Применяю зону контроля (ROI)…", camera_id)
            push_status("motion_check", "Проверяю движение…", camera_id)
            push_status("yolo", "Ищу номерной знак…", camera_id)
            try:
                result = pipeline.process_frame(
                    camera_id=camera_id,
                    frame=frame,
                    roi_conf=roi_conf,
                    ts=ts,
                )
            except Exception as e:
                push_status("error", f"Ошибка пайплайна: {e}", camera_id)
                continue
        except Exception as e:
            push_status("error", f"Ошибка пайплайна: {e}", camera_id)
            continue

        # -------- result handling --------
        if not result:
            # если пайплайн вернул None — обычно это "нет триггера motion" или "не найден номер"
            maybe_idle(camera_id)
            continue

        # Этап 1: детекция рамки номера (bbox) — даже если OCR ещё не подключён (text=None)
        bbox_xyxy = getattr(result, "bbox", None)
        if not bbox_xyxy:
            maybe_idle(camera_id)
            continue

        # Конвертация XYXY -> XYWH (как ожидает CanvasWidget)
        try:
            x1, y1, x2, y2 = map(int, bbox_xyxy)
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            bbox_roi_xywh = [x1, y1, w, h]
        except Exception:
            bbox_roi_xywh = None

        # full bbox (если rect ROI — добавляем смещение)
        bbox_full_xywh = bbox_roi_xywh
        try:
            if bbox_roi_xywh and isinstance(roi_conf, dict) and roi_conf.get("type") == "rect":
                ox = int(roi_conf.get("x") or 0)
                oy = int(roi_conf.get("y") or 0)
                bbox_full_xywh = [bbox_roi_xywh[0] + ox, bbox_roi_xywh[1] + oy, bbox_roi_xywh[2], bbox_roi_xywh[3]]
        except Exception:
            bbox_full_xywh = bbox_roi_xywh

        # Статус: номерной знак найден (но текст может быть ещё не распознан)
        push_status("plate_found", "Найден номерной знак. Выполняю распознавание…", camera_id)

        # Событие детекции -> для обводки в Canvas
        try:
            events_queue.put_nowait({
                "type": "plate_detection",
                "camera_id": camera_id,
                "text": (str(result.text).strip().upper() if getattr(result, "text", None) else None),
                "score": float(getattr(result, "score", 0.0) or 0.0),
                "bbox_roi": bbox_roi_xywh,
                "bbox_full": bbox_full_xywh,
                "ts": ts,
            })
        except Exception:
            pass

        # -------- result handling --------
        if not result:
            maybe_idle(camera_id)
            continue

        # 1) Детекция = bbox (текст вторичен, OCR позже)
        bbox_xyxy = getattr(result, "bbox", None)
        if not bbox_xyxy:
            maybe_idle(camera_id)
            continue

        # CanvasWidget ожидает bbox в формате XYWH, а модель даёт XYXY
        try:
            x1, y1, x2, y2 = map(int, bbox_xyxy)
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            bbox_roi = [x1, y1, w, h]
        except Exception:
            bbox_roi = None

        # full bbox (если rect ROI — добавляем смещение)
        bbox_full = bbox_roi
        try:
            if bbox_roi and isinstance(roi_conf, dict) and roi_conf.get("type") == "rect":
                ox = int(roi_conf.get("x") or 0)
                oy = int(roi_conf.get("y") or 0)
                bbox_full = [bbox_roi[0] + ox, bbox_roi[1] + oy, bbox_roi[2], bbox_roi[3]]
        except Exception:
            bbox_full = bbox_roi

        # статус (детекция прошла)
        push_status("yolo_found", "Найден номерной знак.", camera_id)

        # 2) Событие для обводки — отправляем ВСЕГДА при bbox, даже если text ещё пустой
        try:
            events_queue.put_nowait({
                "type": "plate_detection",
                "camera_id": camera_id,
                "text": (str(getattr(result, "text", "") or "").strip().upper() or None),
                "score": float(getattr(result, "score", 0.0) or 0.0),
                "bbox_roi": bbox_roi,
                "bbox_full": bbox_full,
                "ts": ts,
            })
        except Exception:
            pass

        # 3) OCR (если текст появился) — только тогда пишем “номер распознан”
        plate_text_raw = getattr(result, "text", None)
        if not plate_text_raw:
            continue

        plate_text = str(plate_text_raw).strip().upper()
        push_status("found", f"Номер распознан: {plate_text}. Ожидаю подтверждение…", camera_id)

        # сохраняем в БД только когда есть текст
        try:
            save_detection(
                conn,
                camera_id,
                plate_text,
                bbox=bbox_roi,
                extra={"detected_by": "yolo+tesseract", "score": float(getattr(result, "score", 0.0) or 0.0)},
            )
        except Exception:
            pass

        # bbox: ROI coords -> full coords (если rect ROI)
        bbox_roi = list(result.bbox) if getattr(result, "bbox", None) else None
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

        # событие детекции -> для обводки
        try:
            events_queue.put_nowait({
                "type": "plate_detection",
                "camera_id": camera_id,
                "text": plate_text,
                "score": float(result.score or 0.0),
                "bbox_roi": bbox_roi,
                "bbox_full": bbox_full,
                "ts": ts,
            })
        except Exception:
            pass

    try:
        conn.close()
    except Exception:
        pass

    print("Processor stopped")
