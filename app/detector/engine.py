# app/detector/engine.py
"""
ENGINE: Тяжёлая часть (детектор рамки номера; позже добавим OCR).

СЕЙЧАС (Этап 1):
- Используем YOLOv11 weights (.pt) от morsetechlab, которую ты уже проверил.
- Возвращаем bbox + score.
- text пока None (OCR подключим на Этапе 2).

БУДУЩЕЕ (Этап 2):
- Добавить OCR по crop номера (fast-plate-ocr или другое).
- Возвращать text + комбинированный score (min(yolo_conf, ocr_conf) или умнее).
- Добавить нормализацию текста + лёгкие "починки" (O/0, B/8 и т.д.) по необходимости.

ПЛАН (сверху вниз):
1) Этап 1: bbox детекция YOLO ✅
2) Этап 2: OCR + text + фильтры по длине/формату
3) Этап 3: авто-тюнинг conf/imgsz под камеру + логирование метрик
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO
import pytesseract


BBoxXYXY = Tuple[int, int, int, int]  # (x1, y1, x2, y2)


@dataclass
class PlateDetectionResult:
    """
    Результат детекции одного номера на одном кадре.

    bbox:
        В координатах того кадра, который подали в detect_*.
        Если подали ROI-кадр — bbox тоже в ROI координатах (это ок для текущего этапа).

    score:
        Уверенность детектора (0..1), сейчас это YOLO conf.

    text:
        Пока None (OCR не подключён). На Этапе 2 станет строкой номера.
    """
    bbox: BBoxXYXY
    score: float
    text: Optional[str] = None


class PlateDetectorEngine:
    def __init__(
        self,
        model_path: str,
        *,
        conf: float = 0.25,
        imgsz: int = 640,
        verbose: bool = False,
        enable_ocr: bool = False,
        device: str = "auto",
        ocr_lang: str = "eng+rus",
    ) -> None:
        self.model_path = model_path
        self.conf = conf
        self.imgsz = imgsz
        self.verbose = verbose
        self.device = device
        self.ocr_lang = ocr_lang
        self.enable_ocr = enable_ocr


        self.model = YOLO(self.model_path)

        # Разрешённые символы РФ-номера (латиница + кириллица похожие)
        self._whitelist = "ABEKMHOPCTYX0123456789АВЕКМНОРСТУХ"

        # Нормализация: приводим кириллицу к “латинским” эквивалентам ГОСТ-номера
        self._cyr_to_lat = str.maketrans({
            "А":"A","В":"B","Е":"E","К":"K","М":"M","Н":"H","О":"O","Р":"P","С":"C","Т":"T","У":"Y","Х":"X",
        })

    def _crop(self, frame: np.ndarray, bbox: BBoxXYXY) -> np.ndarray:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w, x2))
        y2 = max(0, min(h, y2))
        if x2 <= x1 or y2 <= y1:
            return np.empty((0, 0, 3), dtype=frame.dtype)
        return frame[y1:y2, x1:x2]

    def _prep_for_ocr(self, plate_img: np.ndarray) -> np.ndarray:
        if plate_img is None or plate_img.size == 0:
            return plate_img

        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 7, 50, 50)

        # увеличим (tesseract любит крупнее)
        h, w = gray.shape[:2]
        scale = 2.0 if max(h, w) < 220 else 1.5
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

        # бинаризация
        gray = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31, 7
        )
        return gray

    def _ocr_text_and_conf(self, plate_img: np.ndarray) -> tuple[str | None, float]:
        if plate_img is None or plate_img.size == 0:
            return None, 0.0

        img = self._prep_for_ocr(plate_img)

        cfg = (
            f'--oem 1 --psm 7 '
            f'-c tessedit_char_whitelist={self._whitelist}'
        )

        try:
            data = pytesseract.image_to_data(img, lang=self.ocr_lang, config=cfg, output_type=pytesseract.Output.DICT)
        except Exception:
            # OCR упал — просто считаем, что текста нет
            return None, 0.0

        parts = []
        confs = []
        n = len(data.get("text", []))
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            if not txt:
                continue
            try:
                c = float(data["conf"][i])
            except Exception:
                c = -1.0
            if c > 0:
                confs.append(c)
            parts.append(txt)

        raw = "".join(parts).upper()
        raw = re.sub(r"[^0-9A-ZА-Я]", "", raw)

        if not raw:
            return None, 0.0

        # нормализация к “латинскому” виду номера
        norm = raw.translate(self._cyr_to_lat)

        conf = float(sum(confs) / len(confs)) if confs else 0.0
        # conf из tesseract обычно 0..100
        return norm, conf / 100.0

    def detect_one(self, frame: np.ndarray) -> List[PlateDetectionResult]:
        if frame is None or frame.size == 0:
            return []

        results = self.model.predict(
            source=frame,
            conf=self.conf,
            imgsz=self.imgsz,
            verbose=self.verbose,
            device=self.device if self.device != "auto" else None,
        )

        r0 = results[0]
        if r0.boxes is None or len(r0.boxes) == 0:
            return []

        out: List[PlateDetectionResult] = []
        for b in r0.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
            yolo_score = float(b.conf[0].item())



            crop = self._crop(frame, (x1, y1, x2, y2))
            text = None
            ocr_score = 0.0
            if self.enable_ocr:
                text, ocr_score = self._ocr_text_and_conf(crop)

            final_score = yolo_score

            out.append(
                PlateDetectionResult(
                    bbox=(x1, y1, x2, y2),
                    score=float(final_score),
                    text=text,
                )
            )

        out.sort(key=lambda d: d.score, reverse=True)
        return out

    def detect_on_roi(self, frames: List[np.ndarray]) -> List[List[PlateDetectionResult]]:
        return [self.detect_one(f) for f in frames]
