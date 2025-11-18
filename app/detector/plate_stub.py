# app/detector/plate_stub.py

"""
Заглушка распознавания автомобильного номера.

Логика:
 1) Лёгкий триггер: Haar-каскад ищет плашку номера.
 2) Если нашли bbox — здесь же (пока что) возвращаем заглушечный текст.
    Позже этот же bbox можно передать в реальный OCR / нейросеть.

Формат ответа:
    (plate_text: str | None, bbox: [x, y, w, h] | None)
"""

import os
import cv2
import numpy as np
from typing import Tuple, Optional


from app.core.config import plate_cascade_path

# Путь к каскаду можно переопределить через переменную окружения
_DEFAULT_CASCADE = str(plate_cascade_path() / "haarcascade_russian_plate_number.xml")

_plate_cascade: Optional[cv2.CascadeClassifier] = None
if os.path.exists(_DEFAULT_CASCADE):
    try:
        _plate_cascade = cv2.CascadeClassifier(_DEFAULT_CASCADE)
        if _plate_cascade.empty():
            _plate_cascade = None
    except Exception:
        _plate_cascade = None


def _cheap_plate_trigger(frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """
    Лёгкий триггер: пытаемся найти плашку номера Haar-каскадом.
    Возвращаем bbox в координатах frame или None.
    """
    global _plate_cascade
    if _plate_cascade is None:
        # Каскад не подключен — триггер выключен
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Немного разгружаем: уменьшаем картинку
    scale = 0.5
    small = cv2.resize(
        gray,
        (int(gray.shape[1] * scale), int(gray.shape[0] * scale)),
        interpolation=cv2.INTER_AREA,
    )

    plates = _plate_cascade.detectMultiScale(
        small,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(50, 15),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    if len(plates) == 0:
        return None

    # Берём первую найденную плашку и пересчитываем координаты
    x, y, w, h = plates[0]
    x = int(x / scale)
    y = int(y / scale)
    w = int(w / scale)
    h = int(h / scale)
    return x, y, w, h


def detect_plate(frame: np.ndarray) -> Tuple[Optional[str], Optional[list]]:
    """
    Главная функция для processor_proc.

    На выходе:
      plate_text: str | None
      bbox: [x, y, w, h] | None  — в координатах входного frame
    """
    if frame is None or frame.size == 0:
        return None, None

    # 1) Лёгкий триггер
    bbox = _cheap_plate_trigger(frame)
    if bbox is None:
        # ничего похожего на номер / машину не нашли
        return None, None

    x, y, w, h = bbox
    plate_roi = frame[y : y + h, x : x + w]

    # 2) Тяжёлое распознавание номера (пока заглушка)
    #    Здесь в будущем можно затащить OCR/нейросеть.
    #    Пока просто возвращаем тестовый номер, чтобы
    #    посмотеть, что виджет и БД работают.
    plate_text = "TEST-PLATE"

    return plate_text, [int(x), int(y), int(w), int(h)]
