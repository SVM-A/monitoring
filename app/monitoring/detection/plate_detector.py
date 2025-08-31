# =============================== app/monitoring/detection/plate_detector.py ===============================
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
import cv2

try:
    import onnxruntime as ort
except Exception:
    ort = None

from app.monitoring.config_runtime import RuntimeOptions, ComputeProvider

@dataclass
class PlateBBox:
    xyxy: Tuple[int, int, int, int]
    conf: float

class PlateDetector:
    def __init__(self, rt: RuntimeOptions, model_path_onnx: str | None = None, cascade_path: str | None = None):
        self.rt = rt
        self.kind = rt.detector_kind
        self.net = None
        self.session = None
        if self.kind == "haar":
            cascade_path = cascade_path or "scaning/haarcascade_russian_plate_number.xml"
            self.net = cv2.CascadeClassifier(cascade_path)
        else:
            if ort is None:
                raise RuntimeError("onnxruntime не установлен")
            providers = ["CPUExecutionProvider"]
            if self.rt.detector_provider == ComputeProvider.CUDA and "CUDAExecutionProvider" in ort.get_available_providers():
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            self.session = ort.InferenceSession(model_path_onnx or "models/plate_yolov5s.onnx", providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            self.input_size = (640, 640)  # подгони под модель

    def _preprocess(self, img: np.ndarray) -> Tuple[np.ndarray, float, float]:
        # letterbox до 640x640
        h, w = img.shape[:2]
        r = min(self.input_size[1] / h, self.input_size[0] / w)
        nh, nw = int(h * r), int(w * r)
        resized = cv2.resize(img, (nw, nh))
        canvas = np.full((self.input_size[1], self.input_size[0], 3), 114, dtype=np.uint8)
        top, left = (self.input_size[1] - nh) // 2, (self.input_size[0] - nw) // 2
        canvas[top:top+nh, left:left+nw] = resized
        blob = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        return blob, left, top

    def _postprocess(self, out: np.ndarray, left: int, top: int, orig_shape: Tuple[int, int]) -> List[PlateBBox]:
        # Ожидаем формат [num, 6]: x1,y1,x2,y2,conf,cls
        H, W = orig_shape
        preds = out
        boxes: List[PlateBBox] = []
        for x1, y1, x2, y2, conf, cls in preds:
            if conf < self.rt.det_conf_threshold:
                continue
            # смещаем из letterbox в исходные координаты
            x1 = int(x1 - left)
            y1 = int(y1 - top)
            x2 = int(x2 - left)
            y2 = int(y2 - top)
            # клиппинг
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(W-1, x2), min(H-1, y2)
            boxes.append(PlateBBox((x1, y1, x2, y2), float(conf)))
        return boxes

    def detect(self, img: np.ndarray) -> List[PlateBBox]:
        if self.kind == "haar":
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            dets = self.net.detectMultiScale(gray, 1.1, 1)
            boxes = []
            for (x, y, w, h) in dets:
                boxes.append(PlateBBox((x, y, x+w, y+h), 0.6))
            return boxes
        else:
            blob, left, top = self._preprocess(img)
            out = self.session.run(None, {self.input_name: blob})[0]
            return self._postprocess(out, left, top, (img.shape[0], img.shape[1]))
