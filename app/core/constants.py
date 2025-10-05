# app/core/constants.py

from app.core.cam_configs.config_loader import load_roi, load_cameras
from app.core.config import BASE_PATH

# Основные настройки и константы, которые удобно видеть вверху.
DB_PATH = BASE_PATH / "detections.db"    # База для фиксации распознанных номеров
CAM_SOURCES = load_cameras()             # Источники камер и виджетов (из cam_configs/cameras.json)
MAX_QUEUE_SIZE = 8                       # Ограничение очереди кадров для процессинга
GLOBAL_ROI = load_roi()                  # Зоны интереса (можно менять на лету, см. SIGHUP)

# Цвета и локализация текста для виджетов
RU_MONTHS = ["", "Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
RU_WD = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

COLOR_BG        = (18, 18, 22)
COLOR_TEXT      = (230, 230, 230)
COLOR_SUB       = (200, 200, 255)
COLOR_GRID      = (70, 70, 78)
COLOR_CELL      = (35, 35, 40)
COLOR_WEEKEND   = (40, 45, 70)      # подложка выходных дней
COLOR_HOLIDAY   = (120, 30, 40)     # подложка праздников (перекрывает выходные)
COLOR_TODAY     = (80, 90, 110)

COLOR_ALERT     = (255, 170, 60)    # яркий блок про «флаги должны висеть»
COLOR_OK        = (140, 210, 120)   # блок про «флаги не нужны»

CLOCK_NORMAL    = (28, 28, 34)      # фон циферблата — обычный день
CLOCK_WEEKEND   = (34, 34, 48)      # фон циферблата — выходной
CLOCK_HOLIDAY   = (60, 22, 28)      # фон циферблата — праздник
