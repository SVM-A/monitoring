from queue import Empty
import sqlite3
from multiprocessing import Queue, Event as MPEvent

import cv2
import numpy as np
import time

from app.detector.pipeline import PlateDetectionPipeline
from app.core.config_cams import PLATE_YOLO_MODEL_PATH
from app.db.camera_registry import save_detection
from app.video.recording import recording_by_id


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
    target_use_roi: bool = False

    target_mode: str = "perf"  # "perf" | "accuracy"
    force_interval_sec: float = 0.8  # для accuracy: раз в 0.8с принудительный проход

    _hold_until: float = 0.0
    _hold_bbox_roi = None
    _hold_bbox_full = None
    _hold_text = None
    _last_hold_emit: float = 0.0
    _hold_emit_every: float = 0.20
    _last_force_ts: float = 0.0


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
                target_use_roi = bool(cmd.get("use_roi") or False)

                m = str(cmd.get("mode") or cmd.get("detect_mode") or "perf").lower().strip()
                if m not in ("perf", "accuracy"):
                    m = "perf"
                target_mode = m

                # интервал для accuracy (сек), можно задавать из UI
                try:
                    fi = cmd.get("force_interval_sec", None)
                    if fi is None:
                        fi = cmd.get("accuracy_interval_sec", None)
                    if fi is not None:
                        force_interval_sec = float(fi)
                        # защита от мусора
                        if force_interval_sec < 0.2:
                            force_interval_sec = 0.2
                        if force_interval_sec > 10.0:
                            force_interval_sec = 10.0
                except Exception:
                    pass

                # при смене камеры/режима — сбросим таймер, чтобы первый forced сработал сразу
                _last_force_ts = 0.0
                src_label = str(cmd.get("source_id") or target_camera_id or "—")
                if target_mode == "accuracy":
                    push_status("config", f"Камера контроля: {src_label} • режим: accuracy ({force_interval_sec:.1f}s)",
                                target_camera_id)
                else:
                    push_status("config", f"Камера контроля: {src_label} • режим: perf", target_camera_id)
                _hold_until = 0.0
                _hold_bbox_roi = None
                _hold_bbox_full = None
                _hold_text = None
                _last_hold_emit = 0.0

            elif ctype == "plate_enable":
                enabled = True
                if target_camera_id:
                    push_status("enabled", "Распознавание включено. Ожидаю движение в зоне контроля…", target_camera_id)
                else:
                    push_status("enabled", "Распознавание включено. Выберите камеру контроля.", "")

            elif ctype == "plate_disable":
                enabled = False
                _hold_until = 0.0
                _hold_bbox_roi = None
                _hold_bbox_full = None
                _hold_text = None
                _last_hold_emit = 0.0
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

        roi_conf = None
        if target_use_roi:
            roi_key = camera_id
            if is_recording_source_id(camera_id):
                rec = recording_by_id(camera_id)
                roi_key = (rec.camera_id if rec else camera_id)
            roi_conf = roi_config.get(roi_key)

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
            is_rec = is_recording_source_id(camera_id)

            force_detect = False
            if is_rec:
                # записи — всегда форсим, чтобы тесты работали предсказуемо
                force_detect = True
            elif target_mode == "accuracy":
                # форсим по таймеру, даже если движения нет
                if _last_force_ts == 0.0 or (ts - _last_force_ts) >= force_interval_sec:
                    force_detect = True
                    _last_force_ts = ts

            result = pipeline.process_frame(
                camera_id=camera_id,
                frame=frame,
                roi_conf=roi_conf,
                ts=ts,
                force_detect=force_detect,
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
            # если недавно был bbox — держим рамку без YOLO/без OCR
            if enabled and camera_id == target_camera_id and (_hold_bbox_full or _hold_bbox_roi) and ts < _hold_until:
                if (ts - _last_hold_emit) >= _hold_emit_every:
                    _last_hold_emit = ts
                    try:
                        events_queue.put_nowait({
                            "type": "plate_detection",
                            "camera_id": camera_id,
                            "text": _hold_text,
                            "score": 0.0,
                            "bbox_roi": _hold_bbox_roi,
                            "bbox_full": _hold_bbox_full,
                            "ts": ts,
                            "ttl_sec": 1.0,
                        })
                    except Exception:
                        pass

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
                ox = int((roi_conf.get("rect") or [0, 0, 0, 0])[0] or 0)
                oy = int((roi_conf.get("rect") or [0, 0, 0, 0])[1] or 0)
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
                "ttl_sec": 2.0,
            })

            # --- hold focus for UI overlay ---
            _hold_bbox_roi = bbox_roi
            _hold_bbox_full = bbox_full
            _hold_text = (str(getattr(result, "text", "") or "").strip().upper() or None)
            _hold_until = ts + 3.0

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

        # обновим hold текст и продлим фокус, чтобы рамка/текст не мигали
        _hold_text = plate_text
        _hold_until = ts + 3.0

        try:
            events_queue.put_nowait({
                "type": "plate_detection",
                "camera_id": camera_id,
                "text": plate_text,
                "score": float(getattr(result, "score", 0.0) or 0.0),
                "bbox_roi": bbox_roi,
                "bbox_full": bbox_full,
                "ts": ts,
                "ttl_sec": 2.0,
            })
        except Exception:
            pass

    try:
        conn.close()
    except Exception:
        pass

    print("Processor stopped")
