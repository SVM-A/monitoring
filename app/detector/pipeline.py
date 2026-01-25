# app/detector/pipeline.py
from __future__ import annotations

from typing import Dict, Optional, List, Tuple

import numpy as np
import cv2

from app.detector.motion import RoiMotionGate
from app.detector.engine import PlateDetectorEngine, PlateDetectionResult

PLATE_MIN_SCORE: float = 0.45
PLATE_MAX_PER_FRAME: int = 3

PLATE_DUP_WINDOW_SEC: float = 3.0
PLATE_DUP_MAX_CENTER_DIST_REL: float = 0.2

PLATE_MIN_TEXT_LEN: int = 4


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
        )

        # camera_id -> (text, bbox_xyxy, ts)
        self._last_detection: Dict[str, Tuple[str, Tuple[int, int, int, int], float]] = {}

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

    def _is_duplicate(
        self,
        camera_id: str,
        det: PlateDetectionResult,
        ts: float,
        roi_shape: Tuple[int, int],
    ) -> bool:
        if not det.text:
            return False

        last = self._last_detection.get(camera_id)
        if last is None:
            return False

        last_text, last_bbox, last_ts = last

        if ts - last_ts > PLATE_DUP_WINDOW_SEC:
            return False

        if (last_text or "").upper() != det.text.upper():
            return False

        h, w = roi_shape
        x1, y1, x2, y2 = last_bbox
        cx1 = (x1 + x2) / 2.0
        cy1 = (y1 + y2) / 2.0

        X1, Y1, X2, Y2 = det.bbox
        cx2 = (X1 + X2) / 2.0
        cy2 = (Y1 + Y2) / 2.0

        dist = ((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) ** 0.5
        denom = float(max(1, min(h, w)))
        dist_norm = dist / denom

        return dist_norm <= PLATE_DUP_MAX_CENTER_DIST_REL

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        roi_conf: Optional[dict],
        ts: float,
    ) -> Optional[PlateDetectionResult]:
        roi_frame = self._apply_roi(frame, roi_conf)
        if roi_frame is None or roi_frame.size == 0:
            return None

        should_trigger = self.motion_gate.update_and_check(camera_id, roi_frame, ts)
        if not should_trigger:
            return None

        roi_buffer = self.motion_gate.pop_buffer(camera_id)
        if roi_buffer and (roi_buffer[-1] is not roi_frame):
            roi_buffer.append(roi_frame)
        elif not roi_buffer:
            roi_buffer = [roi_frame]

        best_frame = self._select_best_frame(roi_buffer)
        if best_frame is None or best_frame.size == 0:
            return None

        detections = self.engine.detect_one(best_frame)

        # фильтруем мусор
        good: List[PlateDetectionResult] = []
        for d in detections:
            if d.score < PLATE_MIN_SCORE:
                continue
            if not d.text:
                continue
            if len(d.text) < PLATE_MIN_TEXT_LEN:
                continue
            good.append(d)

        if not good:
            return None

        good.sort(key=lambda x: x.score, reverse=True)
        best = good[0]

        h, w = roi_frame.shape[:2]
        if self._is_duplicate(camera_id, best, ts, (h, w)):
            return None

        self._last_detection[camera_id] = (best.text, best.bbox, ts)
        return best
