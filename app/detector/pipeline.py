# app/detector/pipeline.py

from __future__ import annotations

from typing import Dict, Optional, List, Tuple

import numpy as np

from app.detector.motion import RoiMotionGate
from app.detector.engine import PlateDetectorEngine, PlateDetectionResult

# ==========================
# Константы пайплайна детекции номера
# ==========================

# Минимальная уверенность (score) детекции/ОCR, ниже которой результат
# считается "мусором" и отбрасывается.
PLATE_MIN_SCORE: float = 0.5

# Максимальное количество номеров, которое имеет смысл обрабатывать
# с одного кадра ROI. Для шлагбаума почти всегда это 1, но оставим запас.
PLATE_MAX_PER_FRAME: int = 3

# Временное окно (секунды) для фильтрации дубликатов.
# Если тот же текст номера появляется в пределах этого окна на похожей позиции,
# считаем, что это тот же автомобиль в той же ситуации и не пишем дубль в БД.
PLATE_DUP_WINDOW_SEC: float = 3.0

# Максимальная относительная дистанция между центрами bbox (0..1)
# для признания детекции дубликатом. Например, 0.2 означает, что
# центры старого и нового bbox должны быть ближе 20 % от минимального
# размера ROI по ширине/высоте.
PLATE_DUP_MAX_CENTER_DIST_REL: float = 0.2

# Минимальная длина текста номера (по символам), чтобы не считать
# короткий OCR "мусор" валидным номером.
PLATE_MIN_TEXT_LEN: int = 4


class PlateDetectionPipeline:
    """
    Высокоуровневая обвязка детекции номера.

    Задачи:
    - Применить ROI к кадру.
    - Использовать RoiMotionGate, чтобы решить, надо ли запускать тяжёлый детектор
      по этому кадру.
    - При срабатывании motion-gate выбрать "лучший" кадр из буфера.
    - Запустить PlateDetectorEngine и получить список кандидатов.
    - Отфильтровать мусор по порогу score, длине текста и, при желании, по регуляркам.
    - Отфильтровать дубликаты по времени/позиции по камере.
    - Вернуть один предпочитаемый PlateDetectionResult или None.

    Таким образом, весь "бизнес-алгоритм" ANPR живёт здесь, а PlateDetectorEngine
    отвечает только за infer моделей, не зная ни про motion, ни про БД.
    """

    def __init__(self, *, device: str = "auto") -> None:
        """
        device:
            "auto"   — попытаться использовать GPU (например, "cuda:0"), если доступен,
                       иначе CPU.
            "cpu"    — принудительно CPU.
            "cuda:0" — конкретный GPU. Актуально для серверов с несколькими картами
                       (например, Tesla + ещё что-то).

        Внутри:
            - создаём RoiMotionGate с дефолтными параметрами;
            - создаём PlateDetectorEngine(device=device);
            - инициализируем кэш последних детекций по камерам.
        """
        # Лёгкая детекция движения по ROI
        self.motion_gate = RoiMotionGate()

        # Тяжёлый движок (детектор рамки номера + OCR) на CPU/GPU
        self.engine = PlateDetectorEngine(device=device)

        # Кэш последних детекций: camera_id -> (text, bbox, ts)
        # bbox: (x, y, w, h) — в координатах ROI-кадра, который был подан в детектор.
        self._last_detection: Dict[str, Tuple[str, Tuple[int, int, int, int], float]] = {}

    def _apply_roi(self, frame: np.ndarray, roi_conf: Optional[dict]) -> np.ndarray:
        """
        Применяет ROI-конфигурацию к кадру.

        Параметры:
            frame:
                Исходный кадр BGR (декодированный из JPEG) в полном разрешении.
            roi_conf:
                Конфигурация ROI для камеры. Должна быть совместима с форматом,
                который использует app.video.ffproxy.apply_roi. Варианты:

                - None:
                    Нет ROI — используется весь кадр.

                - {"type": "rect", "x": int, "y": int, "w": int, "h": int}:
                    Прямоугольная область интереса. В реализации кадр обрезается
                    по этому прямоугольнику.

                - {"type": "poly", "points": [(x1, y1), (x2, y2), ...]}:
                    Полигональная область интереса. В реализации:
                        * создаётся бинарная маска по полигону,
                        * всё, что вне полигона, зануляется (чёрный фон).

                - {"type": "multi", "items": [<rect|poly>, ...]}:
                    Составной ROI (несколько областей), которые объединяются.

        План реализации:
            - Если roi_conf is None — вернуть исходный frame.
            - В иных случаях:
                * аккуратно обработать выход за границы кадра;
                * использовать cv2 для вырезки и/или маскирования;
                * вернуть BGR np.ndarray того же типа, что frame.
            - При желании можно просто делегировать в app.video.ffproxy.apply_roi
              (чтобы не дублировать логику), но тогда надо аккуратно организовать импорт.

        Возвращает:
            BGR np.ndarray ROI-кадра, пригодный для передачи в motion_gate
            и PlateDetectorEngine.
        """
        raise NotImplementedError

    def _select_best_frame(self, roi_buffer: List[np.ndarray]) -> Optional[np.ndarray]:
        """
        Выбирает "лучший" кадр из буфера ROI-кадров для детекции.

        roi_buffer:
            Список ROI-кадров (обычно последних N кадров с момента начала движения),
            накопленных RoiMotionGate.

        Базовая реализация:
            - Если roi_buffer пустой — возвращаем None.
            - Если не хотим усложнять — возвращаем последний кадр в буфере
              (как наиболее актуальный и, скорее всего, уже стабилизировавшийся).

        Расширенная реализация (на будущее):
            - Для каждого кадра считать "резкость" (вариация Лапласиана: cv2.Laplacian),
              выбрать кадр с максимальной резкостью.
            - Можно добавить критерий средней яркости/контраста,
              чтобы избежать слишком тёмных/засвеченных кадров.

        На старте можно реализовать простейший вариант — "последний кадр".
        """
        raise NotImplementedError

    def _is_duplicate(
        self,
        camera_id: str,
        det: PlateDetectionResult,
        ts: float,
        roi_shape: Tuple[int, int],
    ) -> bool:
        """
        Проверяет, не является ли детекция дубликатом последней по данной камере.

        Параметры:
            camera_id:
                Идентификатор камеры.
            det:
                Новый результат детекции (PlateDetectionResult).
            ts:
                Время текущего кадра (timestamp в секундах).
            roi_shape:
                Размер ROI-кадра (H, W), чтобы нормализовать расстояние между
                центрами bbox.

        Логика:

            1) Если по камере ещё не было детекции:
                 return False.

            2) Получаем из кэша:
                 last_text, last_bbox, last_ts = self._last_detection[camera_id]

            3) Если ts - last_ts > PLATE_DUP_WINDOW_SEC:
                 # Слишком давно была последняя детекция — окно закрыто
                 return False

            4) Если текст номера отличается (без учёта регистра):
                 # Другой номер — это не дубликат
                 return False

            5) Если текст совпадает в пределах окна:
                 - Вычисляем центры bbox:
                     (cx1, cy1) для last_bbox, (cx2, cy2) для det.bbox
                 - Считаем евклидово расстояние между центрами.
                 - Нормализуем его на min(H, W) ROI:
                     dist_norm = dist / min(H, W)
                 - Если dist_norm <= PLATE_DUP_MAX_CENTER_DIST_REL:
                     # Считаем, что это тот же автомобиль в той же зоне кадра,
                     # не пишем дубль в БД:
                     return True
                 - Иначе:
                     # Машина сильно сдвинулась (уехала/подъехала опять),
                     # детекцию считаем новой:
                     return False

        Опционально:
            - Можно учитывать score: если новая детекция того же номера имеет
              заметно более высокий score, можно обновить запись в кэше
              (чтобы UI показывал более уверенную детекцию), но в БД всё равно
              писать только одну запись.
        """
        raise NotImplementedError

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        roi_conf: Optional[dict],
        ts: float,
    ) -> Optional[PlateDetectionResult]:
        """
        Главный вход в пайплайн — обрабатывает один кадр с камеры.

        Параметры:
            camera_id:
                Идентификатор камеры (например, "entry gate").
            frame:
                Полный кадр BGR (после декодирования JPEG).
            roi_conf:
                Конфигурация ROI для камеры (или None, если ROI не задан).
            ts:
                Время кадра (timestamp в секундах).

        Возвращает:
            PlateDetectionResult или None.

        Алгоритм:

            1) Применяем ROI:
                 roi_frame = self._apply_roi(frame, roi_conf)
               Если roi_frame пустой (None или размер 0) — сразу return None.

            2) Проверяем движение:
                 should_trigger = self.motion_gate.update_and_check(
                     camera_id, roi_frame, ts
                 )
               Если should_trigger == False:
                 - Ничего дальше не делаем (motion_gate сам обновит фон/буфер).
                 - return None.

            3) Если should_trigger == True:
                 - Забираем буфер ROI-кадров:
                     roi_buffer = self.motion_gate.pop_buffer(camera_id)
                 - При необходимости добавляем текущий roi_frame в буфер,
                   если его там ещё нет.
                 - Выбираем лучший кадр:
                     best_frame = self._select_best_frame(roi_buffer)
                   Если best_frame is None — return None.

            4) Запускаем детектор:
                 detections_batch = self.engine.detect_on_roi([best_frame])
                 detections = detections_batch[0]  # список PlateDetectionResult для 1 ROI

            5) Фильтрация кандидатов:
                 - Оставляем только те, у кого det.score >= PLATE_MIN_SCORE.
                 - Оставляем только те, у кого длина det.text >= PLATE_MIN_TEXT_LEN.
                 - Опционально можно применить регулярки под формат номера
                   (например, ГОСТ Р), чтобы отсеять экзотику.

                 - Ограничиваемся максимум PLATE_MAX_PER_FRAME детекциями
                   (по score или по площади bbox).

            6) Выбор лучшего:
                 - Сортируем оставшиеся детекции по score (убывание).
                 - Берём лучший (первый) как best_det.
                 - Если после всех фильтров кандидатов нет — return None.

            7) Проверка на дубликат:
                 h, w = roi_frame.shape[:2]
                 if self._is_duplicate(camera_id, best_det, ts, (h, w)):
                     # Не пишем второй раз тот же номер в БД
                     return None

            8) Если не дубликат:
                 - Обновляем кэш:
                     self._last_detection[camera_id] = (
                         best_det.text,
                         best_det.bbox,
                         ts,
                     )
                 - Возвращаем best_det, чтобы вызывающая сторона (worker)
                   могла сохранить его в БД и/или передать в UI.

        Таким образом, вызов process_frame() на каждом кадре камеры:
            - в большинстве случаев заканчивается на шаге (2) (нет движения),
            - при движении и срабатывании триггера запускает детектор ровно
              на одном "лучшем" кадре,
            - защищает БД от "спама" дубликатами одного и того же номера.
        """
        raise NotImplementedError
