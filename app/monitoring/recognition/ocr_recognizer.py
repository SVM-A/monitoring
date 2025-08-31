# =============================== app/monitoring/recognition/ocr_recognizer.py ===============================
from __future__ import annotations
from multiprocessing import Process, Queue
from dataclasses import dataclass
from typing import Optional
import numpy as np
import cv2

from app.monitoring.config_runtime import RuntimeOptions, ComputeProvider

# PaddleOCR как основной вариант (точнее и стабильно поддерживает кириллицу)
try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None

# EasyOCR как запасной
try:
    import easyocr as _easy
except Exception:
    _easy = None

@dataclass
class OCRTask:
    crop: np.ndarray
    src_name: str
    bbox: tuple

@dataclass
class OCRResult:
    text: str
    conf: float
    src_name: str
    bbox: tuple

class OCRWorker(Process):
    def __init__(self, in_q: Queue, out_q: Queue, rt: RuntimeOptions):
        super().__init__(daemon=True)
        self.in_q = in_q
        self.out_q = out_q
        self.rt = rt
        self._stopping = False

    def _init_engine(self):
        if self.rt.ocr_kind == "paddle":
            if PaddleOCR is None:
                raise RuntimeError("PaddleOCR не установлен")
            use_gpu = self.rt.ocr_provider == ComputeProvider.CUDA
            # lang='ru' включает кириллицу
            self.engine = PaddleOCR(lang='ru', use_angle_cls=True, use_gpu=use_gpu)
            self.kind = "paddle"
        else:
            if _easy is None:
                raise RuntimeError("EasyOCR не установлен")
            self.engine = _easy.Reader(['ru', 'en'], gpu=self.rt.ocr_provider == ComputeProvider.CUDA)
            self.kind = "easy"

    def _preproc(self, img: np.ndarray) -> np.ndarray:
        if self.rt.ocr_preproc == "none":
            return img
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self.rt.ocr_preproc == "clahe":
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            gray = cv2.bilateralFilter(gray, 9, 75, 75)
            return gray
        if self.rt.ocr_preproc == "adaptive_thresh":
            gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY, 31, 9)
            return gray
        return img

    def run(self):
        self._init_engine()
        while not self._stopping:
            try:
                task: OCRTask = self.in_q.get(timeout=0.2)
            except Exception:
                continue
            crop = self._preproc(task.crop)
            text, conf = self._infer(crop)
            self.out_q.put(OCRResult(text=text, conf=conf, src_name=task.src_name, bbox=task.bbox))

    def _infer(self, img: np.ndarray) -> tuple[str, float]:
        if self.kind == "paddle":
            # PaddleOCR ожидает путь или np.ndarray BGR/GRAY
            res = self.engine.ocr(img, cls=True)
            # Схема: [[ [box], [text, conf] ], ...]
            best_text, best_conf = "", 0.0
            for line in res:
                for _, (txt, cf) in line:
                    if cf > best_conf and len(txt) >= 4:
                        best_text, best_conf = txt, float(cf)
            return best_text, best_conf
        else:
            out = self.engine.readtext(img)
            best_text, best_conf = "", 0.0
            for _, txt, cf in out:
                if cf > best_conf and len(txt) >= 4:
                    best_text, best_conf = txt, float(cf)
            return best_text, best_conf
