# app/detector/motion.py
"""
MOTION GATE: лёгкий "триггер" по движению в ROI.

Зачем:
- Не гонять YOLO на каждом кадре (дорого и бессмысленно).
- Собирать небольшой буфер ROI-кадров во время движения, чтобы
  при срабатывании запускать YOLO по более удачному кадру.

СЕЙЧАС (Этап 1):
- Реализован базовый детектор движения по разнице с фоном.
- Возвращает True редко и осмысленно: при устойчивом движении + cooldown.

БУДУЩЕЕ:
- Добавить маскирование бликов/шумов, если нужно.
- Добавить адаптивный threshold или авто-калибровку под сцену.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, List

import numpy as np
import cv2


MOTION_SMALL_WIDTH: int = 160
MOTION_SMALL_HEIGHT: int = 90
MOTION_DIFF_THRESHOLD: int = 25
MOTION_BG_ALPHA: float = 0.02
MIN_MOVING_FRAMES_BEFORE_DETECT: int = 3
MIN_STILL_FRAMES_TO_RESET: int = 5


@dataclass
class CameraMotionState:
    bg_frame: Optional[np.ndarray] = None
    last_motion_ts: float = 0.0
    last_trigger_ts: float = 0.0
    still_frames: int = 0
    moving_frames: int = 0
    roi_buffer: List[np.ndarray] = field(default_factory=list)


class RoiMotionGate:
    def __init__(
        self,
        *,
        max_buffer_size: int = 5,
        min_motion_ratio: float = 0.005,
        cooldown_sec: float = 0.75,
    ) -> None:
        self.max_buffer_size = max_buffer_size
        self.min_motion_ratio = min_motion_ratio
        self.cooldown_sec = cooldown_sec
        self._states: Dict[str, CameraMotionState] = {}

    def _get_state(self, camera_id: str) -> CameraMotionState:
        state = self._states.get(camera_id)
        if state is None:
            state = CameraMotionState()
            self._states[camera_id] = state
        return state

    def _preprocess_roi(self, roi_frame: np.ndarray) -> np.ndarray:
        if roi_frame is None or roi_frame.size == 0:
            return np.empty((0, 0), dtype=np.uint8)

        small = cv2.resize(
            roi_frame,
            (MOTION_SMALL_WIDTH, MOTION_SMALL_HEIGHT),
            interpolation=cv2.INTER_AREA,
        )
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if gray.dtype != np.uint8:
            gray = gray.astype(np.uint8)
        return gray

    def update_and_check(self, camera_id: str, roi_frame: np.ndarray, now_ts: float) -> bool:
        state = self._get_state(camera_id)
        small = self._preprocess_roi(roi_frame)
        if small.size == 0:
            return False

        # init background
        if state.bg_frame is None:
            state.bg_frame = small.copy()
            state.roi_buffer = [roi_frame]
            state.still_frames = 0
            state.moving_frames = 0
            return False

        diff = cv2.absdiff(small, state.bg_frame)
        motion_mask = diff > MOTION_DIFF_THRESHOLD
        motion_ratio = float(np.count_nonzero(motion_mask)) / float(motion_mask.size)

        if motion_ratio < self.min_motion_ratio:
            # static
            state.still_frames += 1
            state.moving_frames = 0

            if state.still_frames >= MIN_STILL_FRAMES_TO_RESET:
                bg = state.bg_frame.astype(np.float32)
                cur = small.astype(np.float32)
                bg = (1.0 - MOTION_BG_ALPHA) * bg + MOTION_BG_ALPHA * cur
                state.bg_frame = np.clip(bg, 0, 255).astype(np.uint8)

                # очищаем буфер — чтобы не тянуть мусор из прошлого движения
                state.roi_buffer.clear()

            return False

        # moving
        state.moving_frames += 1
        state.still_frames = 0
        state.last_motion_ts = now_ts

        state.roi_buffer.append(roi_frame)
        if len(state.roi_buffer) > self.max_buffer_size:
            state.roi_buffer.pop(0)

        # cooldown
        if now_ts - state.last_trigger_ts < self.cooldown_sec:
            return False

        # wait stable motion
        if state.moving_frames < MIN_MOVING_FRAMES_BEFORE_DETECT:
            return False

        state.last_trigger_ts = now_ts
        return True

    def pop_buffer(self, camera_id: str) -> List[np.ndarray]:
        state = self._states.get(camera_id)
        if state is None:
            return []
        buf = list(state.roi_buffer)
        state.roi_buffer.clear()
        return buf

    def snapshot(self, camera_id: str) -> dict:
        """
        Снимок состояния motion-gate для внешней логики (worker).
        Ничего не меняет, только читает.
        """
        st = self._get_state(camera_id)
        return {
            "still_frames": int(st.still_frames),
            "moving_frames": int(st.moving_frames),
            "last_motion_ts": float(st.last_motion_ts),
            "last_trigger_ts": float(st.last_trigger_ts),
            "buffer_len": int(len(st.roi_buffer)),
        }