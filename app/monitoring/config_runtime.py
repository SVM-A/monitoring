# =============================== app/monitoring/config_runtime.py ===============================
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Literal
import os

# Выбор провайдера вычислений для распознавания/детекции
class ComputeProvider(str, Enum):
    CPU = "cpu"
    CUDA = "cuda"              # NVIDIA GPU через onnxruntime-gpu / PaddleGPU
    OPENVINO = "openvino"      # опционально, если будешь использовать OpenVINO

@dataclass
class RuntimeOptions:
    # Управление производительностью
    capture_queue_size: int = 5           # очерёдь кадров из захвата
    detect_queue_size: int = 12           # очередь детекций на OCR
    ocr_workers: int = 2                  # число OCR-процессов (2–4 для 8–16 потоков)
    detector_provider: ComputeProvider = ComputeProvider.CUDA
    ocr_provider: ComputeProvider = ComputeProvider.CUDA
    detector_batch_size: int = 1          # можно >1 для ONNX детектора
    drop_frames_when_busy: bool = True    # стратегия «последний кадр важнее»
    show_debug_windows: bool = False

    # Препроцессинг для OCR
    ocr_preproc: Literal["none", "clahe", "adaptive_thresh"] = "clahe"

    # Границы уверенности
    det_conf_threshold: float = 0.5
    ocr_conf_threshold: float = 0.5

    # Выбор детектора и OCR
    detector_kind: Literal["haar", "onnx_yolo"] = "onnx_yolo"
    ocr_kind: Literal["paddle", "easyocr"] = "paddle"

    # Выбор провайдера через ENV как override (удобно менять без кода)
    @classmethod
    def from_env(cls) -> RuntimeOptions:
        return cls(
            ocr_workers=int(os.getenv("LPR_OCR_WORKERS", 2)),
            detector_provider=ComputeProvider(os.getenv("LPR_DET_PROVIDER", "cuda")),
            ocr_provider=ComputeProvider(os.getenv("LPR_OCR_PROVIDER", "cuda")),
            detector_kind=os.getenv("LPR_DETECTOR", "onnx_yolo"),
            ocr_kind=os.getenv("LPR_OCR", "paddle"),
            show_debug_windows=os.getenv("LPR_DEBUG", "0") == "1",
        )
