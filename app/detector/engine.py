# app/detector/engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class PlateDetectionResult:
    """
    Результат детекции для одного номера на кадре.
    Координаты bbox — в системе координат того кадра, который подавали
    на вход (обычно ROI кадр).
    """
    text: str              # распознанный номер (строка)
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)
    score: float           # уверенность (0..1)
    frame_idx: int = 0     # опционально — индекс кадра в буфере, если детекция по нескольким
    extra: dict = None     # запас на будущее (страна, тип номера, цвет и т.п.)


class PlateDetectorEngine:
    """
    Обёртка над тяжёлой моделью(ями) для детекции номерного знака и OCR.

    Внутри может быть:
    - модель детекции рамки номера (YOLO/ONNX/TensorRT)
    - модель OCR (CRNN/transformer/готовый EasyOCR)

    Задачи:
    - один раз инициализировать модели и выбрать устройство (GPU/CPU)
    - предоставлять простой метод detect_on_roi() для пайплайна
    - уметь батчить несколько ROI с разных камер
    """

    def __init__(self, device: str = "auto"):
        """
        device:
            "auto"   — пытаемся использовать CUDA, если доступно, иначе CPU
            "cpu"    — принудительно CPU
            "cuda:0" — конкретный GPU, если много карт (актуально для Tesla)
        Здесь:
        - определяем доступность GPU (torch.cuda / tensorrt / onnxruntime-gpu)
        - грузим веса моделей (пути/названия берём из конфига)
        - подготавливаем всё к batched-инференсу
        """
        self.device = device
        # self.detector_model = ...
        # self.ocr_model = ...
        # здесь же удобно задать размер входа для детектора и OCR
        raise NotImplementedError

    def _preprocess_batch(self, roi_batch: List[np.ndarray]):
        """
        Подготовка батча ROI-кадров к подаче в модель:
        - resize до нужного размера
        - нормализация
        - упаковка в тензор/массив для фреймворка (torch / onnxruntime)
        Возвращаем структуру, которую понимает модель.
        """
        raise NotImplementedError

    def _run_detector(self, preprocessed_batch):
        """
        Запуск модели детекции рамки номера.
        Возвращает сырые боксы + скоры для каждого ROI в батче.
        Тип возврата — на твой вкус (список list[ndarray] или что-то подобное).
        """
        raise NotImplementedError

    def _crop_plate_regions(self, roi_batch: List[np.ndarray], raw_detections) -> List[np.ndarray]:
        """
        По сырым детекциям и исходным ROI кадрам:
        - приводим боксы к целым пикселям
        - фильтруем по размеру/соотношению сторон (типичные номера)
        - вырезаем фрагменты картинок с номерами.
        Возвращаем список plate_image'ов (может быть больше, чем ROI, если несколько номеров).
        """
        raise NotImplementedError

    def _run_ocr(self, plate_images: List[np.ndarray]) -> List[Tuple[str, float]]:
        """
        Запуск OCR-модели по каждому вырезанному номеру.
        Возвращаем список (text, score) для каждого входного изображения.
        """
        raise NotImplementedError

    def detect_on_roi(self, roi_batch: List[np.ndarray]) -> List[List[PlateDetectionResult]]:
        """
        Высокоуровневый метод: вся тяжёлая магия в одном шаге.

        Вход:
            roi_batch — список ROI-кадров (один или несколько, с разных камер).

        Логика:
        1) preprocess_batch(...)
        2) raw_detections = _run_detector(...)
        3) plate_images = _crop_plate_regions(roi_batch, raw_detections)
           (и сопоставить, какой plate к какому ROI относится)
        4) texts_scores = _run_ocr(plate_images)
        5) собрать список PlateDetectionResult по каждому ROI:
            [
              [PlateDetectionResult(...), ...],  # для ROI 0
              [PlateDetectionResult(...), ...],  # для ROI 1
              ...
            ]

        Важно:
        - здесь не занимаемся дедупликацией по времени, только детекция текущего батча.
        """
        raise NotImplementedError
