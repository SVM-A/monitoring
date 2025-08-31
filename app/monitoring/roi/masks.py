# app/monitoring/roi/masks.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import numpy as np, cv2, yaml

@dataclass
class MaskConfig:
    enabled: bool = True
    apply_to: List[str] = None  # ["analysis"], ["display"], ...
    crop: Optional[Tuple[int,int,int,int]] = None
    polygon: Optional[List[Tuple[int,int]]] = None
    def as_np_polygon(self): return None if not self.polygon else np.array(self.polygon, np.int32)

class MaskStore:
    def __init__(self, path: str):
        raw = yaml.safe_load(open(path, "r", encoding="utf-8"))
        self._m: Dict[str, MaskConfig] = {}
        for cam, cfg in (raw.get("cameras") or {}).items():
            m = cfg.get("mask") or {}
            self._m[cam] = MaskConfig(
                enabled=bool(m.get("enabled", False)),
                apply_to=list(m.get("apply_to", ["analysis"])),
                crop=tuple(m["crop"]) if "crop" in m else None,
                polygon=[tuple(p) for p in m["polygon"]] if "polygon" in m else None,
            )
    def get(self, cam: str) -> Optional[MaskConfig]: return self._m.get(cam)

def apply_mask(frame, mask: Optional[MaskConfig], mode: str = "analysis"):
    if not mask or not mask.enabled or mode not in (mask.apply_to or []):
        return frame  # маска не нужна для этого режима
    out = frame
    poly = mask.as_np_polygon()
    if poly is not None:
        mimg = np.zeros_like(out); cv2.fillPoly(mimg, [poly], (255,255,255))
        out = cv2.bitwise_and(out, mimg)
    if mask.crop:
        x,y,w,h = mask.crop
        H,W = out.shape[:2]
        x=max(0,min(x,W-1)); y=max(0,min(y,H-1))
        w=max(1,min(w,W-x)); h=max(1,min(h,H-y))
        out = out[y:y+h, x:x+w]
    return out
