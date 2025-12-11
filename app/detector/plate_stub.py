# app/detector/plate_stub.py

"""
Заглушка распознавания автомобильного номера.

Сейчас:
    - detect_plate(...) всегда возвращает (None, None), чтобы не ломать приложение.
    - Пайплайн PlateDetectionPipeline не создаётся и не используется.

Дальше:
    - сюда будет подключён PlateDetectionPipeline из app.detector.pipeline;
    - интерфейс уже подготовлен к тому, чтобы принимать
      camera_id / roi_conf / ts, но это опционально:
        * старые вызовы detect_plate(frame) по-прежнему работают;
        * новые вызовы смогут передавать детальной контекст для пайплайна.
"""

from typing import Tuple, Optional, Dict, Any

import numpy as np

# Когда будем готовы подключать реальный пайплайн — раскомментируем:
# from app.detector.pipeline import PlateDetectionPipeline
#
# GLOBAL_PIPELINE: Optional[PlateDetectionPipeline] = None


def setup_pipeline_if_needed():
    """
    Инициализация глобального пайплайна детекции.

    Идея (на будущее):
        - вызывать один раз при старте processor_proc ИЛИ лениво при первом
          вызове detect_plate(..., camera_id=..., roi_conf=..., ts=...);
        - внутри создать PlateDetectionPipeline с нужным device:
              * на ноуте с RTX 3050 — device="auto" (CUDA, если есть);
              * на проде с 1080/2070/Tesla — тоже "auto" или конкретный "cuda:0";
        - сохранить экземпляр в GLOBAL_PIPELINE.

    Пример будущей реализации:

        global GLOBAL_PIPELINE
        if GLOBAL_PIPELINE is None:
            GLOBAL_PIPELINE = PlateDetectionPipeline(device="auto")

    Сейчас:
        - оставляем тело пустым, чтобы не дёргать ещё нереализованный пайплайн.
    """
    # global GLOBAL_PIPELINE
    # if GLOBAL_PIPELINE is None:
    #     GLOBAL_PIPELINE = PlateDetectionPipeline(device="auto")
    pass


def detect_plate(
    frame: np.ndarray,
    *,
    camera_id: Optional[str] = None,
    roi_conf: Optional[Dict[str, Any]] = None,
    ts: Optional[float] = None,
) -> Tuple[Optional[str], Optional[list]]:
    """
    Главная функция детекции номера для processor_proc и canvas.

    Режимы вызова:

      1) ЛЕГАСИ-РЕЖИМ (как сейчас):
            plate, bbox = detect_plate(frame)

         - используется в worker.py и canvas.py;
         - никакого контекста камеры нет;
         - пока что мы просто возвращаем (None, None), чтобы приложение работало.

      2) РАСШИРЕННЫЙ РЕЖИМ (на будущее):
            plate, bbox = detect_plate(
                frame,
                camera_id="entry gate",
                roi_conf=...,
                ts=time.time(),
            )

         - сюда будем пробрасывать:
             * camera_id — для раздельного motion_gate и анти-дубликатов;
             * roi_conf  — чтобы пайплайн сам применял ROI при необходимости;
             * ts        — timestamp кадра для motion_gate и окна дубликатов.
         - внутри detect_plate:
             * вызовем setup_pipeline_if_needed();
             * передадим всё в GLOBAL_PIPELINE.process_frame(...);
             * вернём (result.text, list(result.bbox)).

    План будущей реализации:

        if frame is None or frame.size == 0:
            return None, None

        # Если не передали camera_id/ts — работа в "простейшем" режиме
        # (можно, например, сделать один проход без motion_gate).
        if camera_id is None or ts is None:
            return None, None

        setup_pipeline_if_needed()
        if GLOBAL_PIPELINE is None:
            return None, None

        result = GLOBAL_PIPELINE.process_frame(
            camera_id=camera_id,
            frame=frame,
            roi_conf=roi_conf,
            ts=ts,
        )
        if result is None:
            return None, None

        return result.text, list(result.bbox)

    Сейчас:
        - мы НЕ создаём пайплайн и НЕ вызываем его;
        - функция остаётся безопасной заглушкой.
    """

    # Минимальная защита от мусора на входе
    if frame is None or frame.size == 0:
        return None, None

    # На данном этапе пайплайн ещё не реализован,
    # поэтому всегда возвращаем "нет номера".
    # Когда PlateDetectionPipeline будет готов, сюда приедет логика выше.
    return None, None
