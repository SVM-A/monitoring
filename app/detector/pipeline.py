# app/detector/pipeline.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple, Callable, Any

import numpy as np
import cv2

from app.detector.motion import RoiMotionGate
from app.detector.engine import PlateDetectorEngine, PlateDetectionResult

PLATE_MIN_SCORE: float = 0.45
PLATE_MAX_PER_FRAME: int = 3

PLATE_DUP_WINDOW_SEC: float = 3.0
PLATE_DUP_MAX_CENTER_DIST_REL: float = 0.2

PLATE_MIN_TEXT_LEN: int = 4

PLATE_DUP_WINDOW_SEC_TEXT: float = 10.0
PLATE_DUP_WINDOW_SEC_BBOX: float = 30.0

PLATE_CLEAR_LAST_AFTER_IDLE_SEC: float = 2.5


@dataclass
class _LastDet:
    ts: float
    text: Optional[str]
    bbox_xyxy: tuple[int, int, int, int]  # (x1,y1,x2,y2)

class PlateDetectionPipeline:
    def __init__(
        self,
        *,
        model_path: str,
        device: str = "auto",
    ) -> None:
        self.motion_gate = RoiMotionGate()
        self.engine = PlateDetectorEngine(
            model_path=model_path,
            device=device,
            conf=0.25,
            imgsz=640,
            verbose=False,
            enable_ocr=True,
        )

        self._last_detection: Dict[str, _LastDet] = {}
        self._idle_since: Dict[str, float] = {}

    def _apply_roi(self, frame: np.ndarray, roi_conf: Optional[dict]) -> np.ndarray:
        if frame is None or frame.size == 0:
            return frame
        if not roi_conf:
            return frame

        # чтобы не ловить циклические импорты — импортируем внутри
        from app.video.ffproxy import apply_roi
        return apply_roi(frame, roi_conf)

    def _select_best_frame(self, roi_buffer: List[np.ndarray]) -> Optional[np.ndarray]:
        if not roi_buffer:
            return None
        if len(roi_buffer) == 1:
            return roi_buffer[0]

        # выбираем самый резкий кадр (вариация Лапласиана)
        best = None
        best_score = -1.0
        for fr in roi_buffer:
            if fr is None or fr.size == 0:
                continue
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            v = float(cv2.Laplacian(g, cv2.CV_64F).var())
            if v > best_score:
                best_score = v
                best = fr
        return best if best is not None else roi_buffer[-1]

    def _bbox_center(self, bbox_xyxy: tuple[int, int, int, int]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox_xyxy
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    def _dist(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _is_duplicate(
            self,
            camera_id: str,
            det_text: Optional[str],
            det_bbox_xyxy: tuple[int, int, int, int],
            now_ts: float,
            frame_hw: tuple[int, int],
    ) -> bool:
        """
        Анти-дубликаты:
        - если есть text → сравниваем text
        - если text нет → сравниваем bbox по центру
        """
        last = self._last_detection.get(camera_id)
        if last is None:
            return False

        # окно по времени
        dup_window = PLATE_DUP_WINDOW_SEC_TEXT if (det_text and last.text) else PLATE_DUP_WINDOW_SEC_BBOX
        if (now_ts - last.ts) > dup_window:
            return False

        # ───── OCR режим ─────
        if det_text and last.text:
            return det_text == last.text

        # ───── bbox-only режим ─────
        h, w = frame_hw
        max_dist_px = PLATE_DUP_MAX_CENTER_DIST_REL * max(h, w)

        c1 = self._bbox_center(last.bbox_xyxy)
        c2 = self._bbox_center(det_bbox_xyxy)

        return self._dist(c1, c2) <= max_dist_px

    def process_frame(
            self,
            camera_id: str,
            frame: np.ndarray,
            roi_conf: Optional[dict],
            ts: float,
            force_detect: bool = False,
            on_stage: Optional[Callable[[str, dict], None]] = None,
    ) -> Optional[PlateDetectionResult]:

        def _stage(name: str, **payload: Any) -> None:
            if on_stage:
                try:
                    on_stage(name, payload)
                except Exception:
                    pass

        _stage("roi")
        roi_frame = self._apply_roi(frame, roi_conf)
        if roi_frame is None or roi_frame.size == 0:
            return None

        _stage("motion_check")

        if not force_detect:
            should_trigger = self.motion_gate.update_and_check(camera_id, roi_frame, ts)
            if not should_trigger:
                _stage("idle")

                # Если сцена стабильно "idle" — считаем, что авто уехало/сцена чистая
                idle_since = self._idle_since.get(camera_id)
                if idle_since is None:
                    self._idle_since[camera_id] = ts
                else:
                    if (ts - idle_since) >= PLATE_CLEAR_LAST_AFTER_IDLE_SEC:
                        # сбрасываем "последнюю детекцию", чтобы новый авто не блокировался длинным dup-window
                        if camera_id in self._last_detection:
                            del self._last_detection[camera_id]
                        # держим idle_since на ts, чтобы не дёргать delete каждый кадр
                        self._idle_since[camera_id] = ts

                return None
            self._idle_since.pop(camera_id, None)
            _stage("motion_trigger")
        else:
            _stage("motion_trigger")
            self._idle_since.pop(camera_id, None)

        roi_buffer = self.motion_gate.pop_buffer(camera_id)
        if roi_buffer and (roi_buffer[-1] is not roi_frame):
            roi_buffer.append(roi_frame)
        elif not roi_buffer:
            roi_buffer = [roi_frame]

        best_frame = self._select_best_frame(roi_buffer)
        if best_frame is None or best_frame.size == 0:
            return None

        _stage("yolo")
        if getattr(self.engine, "enable_ocr", False):
            _stage("ocr")
        detections = self.engine.detect_one(best_frame)

        # фильтруем мусор
        good: List[PlateDetectionResult] = []
        for d in detections:
            if d.score < PLATE_MIN_SCORE:
                continue

            # Этап 1: bbox-only. Текст не обязателен.
            if d.text:
                if len(d.text) < PLATE_MIN_TEXT_LEN:
                    continue

            good.append(d)

        if not good:
            _stage("none")
            return None

        good.sort(key=lambda x: x.score, reverse=True)
        best = good[0]

        h, w = roi_frame.shape[:2]
        if self._is_duplicate(
                camera_id=camera_id,
                det_text=best.text,
                det_bbox_xyxy=best.bbox,
                now_ts=ts,
                frame_hw=(h, w),
        ):
            _stage("dup")
            return None

        self._last_detection[camera_id] = _LastDet(
            ts=ts,
            text=best.text,
            bbox_xyxy=best.bbox,
        )
        _stage("found", text=best.text, bbox=best.bbox, score=best.score)
        return best
