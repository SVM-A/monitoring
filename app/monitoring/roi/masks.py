# =============================== app/monitoring/roi/masks.py ===============================
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any
import numpy as np
import cv2
import yaml

@dataclass
class MaskConfig:
    # Обрезка по прямоугольнику (x, y, w, h)
    crop: Tuple[int, int, int, int]
    # Многоугольник ROI в координатах полного кадра
    polygon: List[Tuple[int, int]]

    def as_np_polygon(self) -> np.ndarray:
        return np.array(self.polygon, dtype=np.int32)

class MaskStore:
    def __init__(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._masks: Dict[str, MaskConfig] = {}
        for cam_name, cfg in raw.get("cameras", {}).items():
            crop = tuple(cfg["mask"]["crop"])  # type: ignore
            polygon = [tuple(p) for p in cfg["mask"]["polygon"]]
            self._masks[cam_name] = MaskConfig(crop=crop, polygon=polygon)

    def get(self, cam_name: str) -> MaskConfig:
        return self._masks[cam_name]


def apply_mask(frame, mask: MaskConfig):
    # многоугольная маска
    mask_img = np.zeros_like(frame)
    cv2.fillPoly(mask_img, [mask.as_np_polygon()], (255, 255, 255))
    masked = cv2.bitwise_and(frame, mask_img)
    x, y, w, h = mask.crop
    return masked[y:y+h, x:x+w]