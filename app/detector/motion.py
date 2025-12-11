# app/detector/motion.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, List

import numpy as np

# ==========================
# Константы для детекции движения
# ==========================

# Размер уменьшенного ROI, на котором считаем движение.
# 160x90 при исходном 1920x1080 даёт сильное снижение
# числа пикселей и нагрузки на CPU, но сохраняет структуру движения.
MOTION_SMALL_WIDTH: int = 160
MOTION_SMALL_HEIGHT: int = 90

# Порог по яркости (0–255), выше которого пиксель считаем "изменившимся".
# Подбирается экспериментально. 20–30 — разумное начальное значение.
MOTION_DIFF_THRESHOLD: int = 25

# Коэффициент сглаживания при экспоненциальном обновлении фона
# (используется только на "статичных" кадрах, чтобы машина не стала фоном).
# 0.02 означает, что фон обновится примерно за 1 / 0.02 = 50 кадров
# (~2 секунды при 25 fps), если кадр остаётся статичным.
MOTION_BG_ALPHA: float = 0.02

# Минимальное количество подряд "движущихся" кадров, прежде чем
# мы разрешим запуск тяжёлого детектора.
# Нужно, чтобы не реагировать на одиночные шумы / блики / артефакты.
MIN_MOVING_FRAMES_BEFORE_DETECT: int = 3

# Сколько подряд "статичных" кадров нужно, чтобы считать,
# что эпизод движения закончился и можно спокойно обновлять фон.
MIN_STILL_FRAMES_TO_RESET: int = 5


@dataclass
class CameraMotionState:
    """
    Состояние детекции движения для одной камеры.

    bg_frame:
        Уменьшенный grayscale "фон" (MOTION_SMALL_WIDTH x MOTION_SMALL_HEIGHT),
        с которым сравниваем текущий кадр. Обновляется только на статичных кадрах.

    last_motion_ts:
        Время (timestamp в секундах), когда в последний раз был зафиксирован
        кадр с заметным движением (motion_ratio >= min_motion_ratio).

    last_trigger_ts:
        Время (timestamp), когда в последний раз был "разрешён" запуск
        тяжёлого детектора номера (с учётом cooldown).

    still_frames:
        Количество подряд кадров, классифицированных как "статичные"
        (motion_ratio < min_motion_ratio).

    moving_frames:
        Количество подряд кадров, классифицированных как "движущиеся"
        (motion_ratio >= min_motion_ratio).

    roi_buffer:
        Буфер исходных ROI-кадров (в полном разрешении), накопленный с тех пор,
        как началось движение. Используется, чтобы при срабатывании триггера
        выбрать "лучший" кадр для детекции (по резкости, контрасту и т.п.).
    """
    bg_frame: Optional[np.ndarray] = None
    last_motion_ts: float = 0.0
    last_trigger_ts: float = 0.0
    still_frames: int = 0
    moving_frames: int = 0
    roi_buffer: List[np.ndarray] = field(default_factory=list)


class RoiMotionGate:
    """
    Гейт движения по ROI кадра.

    Задачи:
    - По каждому кадру камеры оценить, есть ли заметное движение в ROI.
    - Поддерживать буфер последних ROI-кадров в момент движения.
    - Решить, когда "имеет смысл" запустить тяжёлый детектор номерного знака
      (YOLO/нейросетка), чтобы не дёргать модель на каждом кадре.

    Алгоритм в общих чертах:

      1) Для каждой камеры храним CameraMotionState (фон, счётчики, буфер).
      2) Для каждого кадра:
         - ROI уменьшаетcя до (MOTION_SMALL_WIDTH x MOTION_SMALL_HEIGHT),
           переводится в grayscale, слегка блюрится.
         - Если фон ещё не инициализирован — принимаем текущий кадр как фон,
           добавляем ROI в буфер, возвращаем False.
         - Иначе считаем разницу |current_small - bg_frame|.
         - Строим маску diff > MOTION_DIFF_THRESHOLD и считаем motion_ratio.
      3) Если motion_ratio < min_motion_ratio:
           - Кадр считаем статичным:
             still_frames++, moving_frames = 0.
             При достижении MIN_STILL_FRAMES_TO_RESET аккуратно обновляем фон
             по экспоненциальной схеме:
                 bg = (1 - MOTION_BG_ALPHA) * bg + MOTION_BG_ALPHA * current
             Буфер ROI можно частично очищать.
             Возвращаем False.
      4) Если motion_ratio >= min_motion_ratio:
           - Кадр считаем "движущимся":
             moving_frames++, still_frames = 0.
             Добавляем ROI в roi_buffer (с обрезкой по max_buffer_size).
             last_motion_ts обновляем на now_ts.
           - Если с момента last_trigger_ts прошло меньше cooldown_sec —
             пока не даём разрешение, возвращаем False.
           - Если moving_frames < MIN_MOVING_FRAMES_BEFORE_DETECT —
             ждём ещё кадров, возвращаем False.
           - Иначе:
             - Фиксируем last_trigger_ts = now_ts.
             - Возвращаем True, сигнализируя, что можно запускать детектор.

    Таким образом:
    - motion_gate сильно срезает число запусков нейросети;
    - при этом мы всё равно успеваем "подхватить" машину на подъезде к шлагбауму.
    """

    def __init__(
        self,
        *,
        max_buffer_size: int = 5,
        min_motion_ratio: float = 0.02,
        cooldown_sec: float = 0.75,
    ) -> None:
        """
        max_buffer_size:
            Максимальное количество ROI-кадров в буфере на камеру.
            При 25 fps буфер из 5 кадров покрывает ~0.2 секунды движения перед триггером.

        min_motion_ratio:
            Минимальная доля изменившихся пикселей (0..1), чтобы считать кадр
            "движущимся". Например, 0.02 = 2 % пикселей.

        cooldown_sec:
            Минимальный временной интервал в секундах между разрешёнными
            запусками тяжёлого детектора для одной камеры. Позволяет
            не дергать нейросеть слишком часто по одной и той же машине.
        """
        self.max_buffer_size = max_buffer_size
        self.min_motion_ratio = min_motion_ratio
        self.cooldown_sec = cooldown_sec

        # Состояние по камерам: camera_id -> CameraMotionState
        # Используется только внутри одного процесса (processor_proc),
        # отдельно от UI и других процессов.
        self._states: Dict[str, CameraMotionState] = {}

    def _get_state(self, camera_id: str) -> CameraMotionState:
        """
        Возвращает (и при необходимости создаёт) состояние для камеры.

        Логика:
        - Если camera_id ещё не встречался, создаём новый CameraMotionState
          и кладём в self._states.
        - Возвращаем ссылку на объект, в котором будут накапливаться фон,
          счётчики и буфер ROI-кадров.
        """
        raise NotImplementedError

    def _preprocess_roi(self, roi_frame: np.ndarray) -> np.ndarray:
        """
        Подготовка ROI для детекции движения.

        План реализации:
        1) Если roi_frame пустой (None или размер 0) — вернуть пустой массив.
        2) Преобразовать roi_frame к размеру (MOTION_SMALL_WIDTH, MOTION_SMALL_HEIGHT)
           через cv2.resize с INTER_AREA (подходит для уменьшения).
        3) Перевести в grayscale через cv2.cvtColor(..., cv2.COLOR_BGR2GRAY).
        4) Нанести лёгкое размытие (например, cv2.GaussianBlur) для снижения шума.
        5) Убедиться, что выходной массив имеет тип uint8.

        Результат:
            Небольшой двумерный np.ndarray (H x W) с яркостями пикселей,
            пригодный для дальнейшего сравнения с фоном.
        """
        raise NotImplementedError

    def update_and_check(self, camera_id: str, roi_frame: np.ndarray, now_ts: float) -> bool:
        """
        Обновляет состояние по очередному кадру ROI и решает,
        нужно ли запускать тяжёлый детектор номерного знака.

        Параметры:
            camera_id:
                Идентификатор камеры (как в config_cams и camera_registry).
            roi_frame:
                Кадр ROI в полном разрешении (после apply_roi для данной камеры).
            now_ts:
                Текущее время (time.time() или аналогичный timestamp в секундах).

        Возвращает:
            True  — есть движение, накоплено достаточно кадров, cooldown прошёл —
                    можно запускать детектор номерного знака по буферу ROI.
            False — запускать детектор сейчас не стоит.

        Подробный алгоритм:

            1) Получаем/создаём состояние:
                 state = self._get_state(camera_id)

            2) Препроцессинг ROI:
                 small = self._preprocess_roi(roi_frame)
               Если small пустой — возвращаем False.

            3) Инициализация фона:
               Если state.bg_frame is None:
                 - принимаем small как фон: state.bg_frame = small.copy()
                 - добавляем исходный roi_frame в state.roi_buffer
                   (с учётом max_buffer_size)
                 - возвращаем False (слишком рано для детекции).

            4) Рассчитываем разницу:
                 diff = |small - state.bg_frame|
                 motion_mask = diff > MOTION_DIFF_THRESHOLD
                 motion_ratio = (число True в motion_mask) / (общее число пикселей)

            5) Если motion_ratio < self.min_motion_ratio (кадр статичен):
                 - state.still_frames += 1
                 - state.moving_frames = 0
                 - Если state.still_frames >= MIN_STILL_FRAMES_TO_RESET:
                     * аккуратно обновляем фон:
                         state.bg_frame = (1 - MOTION_BG_ALPHA) * state.bg_frame
                                           + MOTION_BG_ALPHA * small
                       (в реализации надо привести к типу uint8)
                     * при желании можем уменьшить или очистить roi_buffer,
                       чтобы не хранить старый мусор.
                 - Возвращаем False (детектор не вызываем).

            6) Если motion_ratio >= self.min_motion_ratio (есть движение):
                 - state.moving_frames += 1
                 - state.still_frames = 0
                 - добавляем roi_frame в state.roi_buffer:
                     * append
                     * если длина > max_buffer_size — удалить самый старый
                 - state.last_motion_ts = now_ts

                 - Проверяем cooldown:
                     if now_ts - state.last_trigger_ts < self.cooldown_sec:
                         возвращаем False (движение есть, но детектор недавно работал).

                 - Проверяем, достаточно ли подряд "движущихся" кадров:
                     if state.moving_frames < MIN_MOVING_FRAMES_BEFORE_DETECT:
                         возвращаем False (ждём ещё пару кадров, чтобы кадр был чётче).

                 - Если дошли сюда:
                     * считаем, что пора запускать детектор.
                     * state.last_trigger_ts = now_ts
                     * возвращаем True.

        Таким образом, detctor вызывается только при "значимом" движении
        и не чаще, чем раз в cooldown_sec секунд по каждой камере.
        """
        raise NotImplementedError

    def pop_buffer(self, camera_id: str) -> List[np.ndarray]:
        """
        Возвращает и очищает буфер ROI-кадров для камеры.

        Использование:
            if motion_gate.update_and_check(camera_id, roi_frame, ts):
                roi_buffer = motion_gate.pop_buffer(camera_id)
                # добавить текущий roi_frame, если он ещё не в буфере
                # best_frame = pipeline._select_best_frame(roi_buffer)
                # далее отправить best_frame в PlateDetectorEngine

        Логика:
            - Находим state = self._get_state(camera_id).
            - Делаем копию списка state.roi_buffer (или просто забираем ссылку).
            - Очищаем state.roi_buffer (список становится пустым).
            - Если состояния для камеры ещё не было — возвращаем пустой список.
        """
        raise NotImplementedError
