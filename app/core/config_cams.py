# app/core/config_cams.py
import signal
import os
import json
from typing import Dict, Any, Optional
from pathlib import Path

from app.core.config import BASE_PATH



# --config_loader--

try:
    # опционально: pip install python-dotenv
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv отсутствует — надеемся на реальные env
    pass

BASE_DIR = Path(__file__).resolve().parent

def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)

from urllib.parse import quote

def build_rtsp_for_cam(cam_spec: Dict[str, Any], cam_key: str) -> Optional[str]:
    # override через переменные окружения
    override_env = cam_spec.get("override_env") or f"{cam_key.upper()}_RTSP_OVERRIDE"
    override_val = os.environ.get(override_env) or os.environ.get(f"CAM_{cam_key.upper()}_RTSP_OVERRIDE")
    if override_val:
        return override_val

    protocol = cam_spec.get("protocol", "rtsp")
    host = cam_spec.get("host")
    port = cam_spec.get("port")
    path = cam_spec.get("path", "")
    base_params = cam_spec.get("params", "")

    # credentials
    user_env = cam_spec.get("user_env")
    pass_env = cam_spec.get("pass_env")
    user = os.environ.get(user_env) if user_env else None
    pwd = os.environ.get(pass_env) if pass_env else None
    auth = f"{quote(user)}:{quote(pwd)}@" if (user and pwd) else ""

    # собрать список параметров
    param_list = []
    if base_params:
        # уберём возможный ведущий '?', разобьём по '&' и добавим в список
        base_params = base_params.lstrip('?')
        if base_params:
            param_list.extend([p for p in base_params.split('&') if p])

    # дополнительные параметры по флагам
    # "transport": "tcp" -> rtsp_transport=tcp
    transport = cam_spec.get("transport")
    if transport and str(transport).lower() == "tcp":
        if "rtsp_transport=tcp" not in param_list:
            param_list.append("rtsp_transport=tcp")

    # таймаут (в микросекундах для ffmpeg). Можно задать "stimeout": 5000000 в JSON (опционально)
    stimeout = cam_spec.get("stimeout")
    if stimeout:
        entry = f"stimeout={int(stimeout)}"
        if entry not in param_list:
            param_list.append(entry)

    # собрать строку параметров
    params = f"?{'&'.join(param_list)}" if param_list else ""

    # нормализация path
    if path and not path.startswith("/"):
        path = "/" + path

    hostport = f"{host}:{port}" if port else host
    url = f"{protocol}://{auth}{hostport}{path}{params}"
    return url


def load_cameras(cameras_json: str = None) -> Dict[str, dict]:
    if cameras_json is None:
        path = BASE_DIR / "cameras.json"
    else:
        path = Path(cameras_json)
    data = load_json(path)
    cams = data.get("cameras", {})
    result: Dict[str, dict] = {}
    for cam_id, spec in cams.items():
        if str(spec.get("type", "")).lower() == "widget":
            result[cam_id] = {"type": "widget", "widget": spec.get("widget", "").lower()}
            continue

        # базовый URL
        url = build_rtsp_for_cam(spec, cam_id)

        # дополнительные потоки (необязательно)
        streams_spec = spec.get("streams") or {}
        streams = {}
        for skey, sdef in streams_spec.items():
            merged = dict(spec) | dict(sdef or {})  # наследуем логин/пароль/хост/порт/transport
            streams[skey] = build_rtsp_for_cam(merged, cam_id)

        # если верхний url пустой/некорректный, а streams есть — берём main/первый
        if (not spec.get("path")) and streams:
            url = streams.get("main") or next(iter(streams.values()))

        entry = {"type": "rtsp", "url": url}
        if streams:
            entry["streams"] = streams
        if spec.get("quality_presets"):
            entry["quality_presets"] = spec["quality_presets"]
        if spec.get("split"):
            entry["split"] = spec["split"]  # "h" | "v"
        result[cam_id] = entry

    return result

def load_roi(roi_json: str = None) -> Dict[str, Any]:
    if roi_json is None:
        path = BASE_DIR / "roi.json"
    else:
        path = Path(roi_json)
    return load_json(path)

# example quick helper for hot reload:
def reload_roi_from(path: Optional[str] = None):
    return load_roi(path)

# --constants--


# Основные настройки и константы, которые удобно видеть вверху.
DB_PATH_DETECTION = BASE_PATH / "detections.db"
DB_PATH_CAMERAS = BASE_PATH / "cameras.db"
CAM_SOURCES = load_cameras()             # Источники камер и виджетов (из cam_configs/cameras.json)
MAX_QUEUE_SIZE = 8                       # Ограничение очереди кадров для процессинга
GLOBAL_ROI = load_roi()                  # Зоны интереса (можно менять на лету, см. SIGHUP)

# Цвета и локализация текста для виджетов
RU_MONTHS = ["", "Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
RU_MONTHS_SHORT = ["","янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
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
# app/core/config_cams.py  (добавь в конец блока цветов)

# Тема для календаря/погоды
COLOR_TEMP      = (210, 220, 255)    # температура в ячейке (чуть светлее основного текста)
BADGE_BG        = (30, 30, 36)       # фон бейджа
BADGE_TEXT      = (220, 220, 230)    # текст бейджа по умолчанию
BADGE_RAIN      = (120, 160, 220)    # осадки (обычные)
BADGE_RAIN_HIGH = (90, 150, 230)     # осадки (много)
BADGE_WIND      = (230, 160, 160)    # сильный ветер


# Пиктограммы (можешь заменить на свои)
WX_ICON_RAIN_LIGHT = "☔"   # небольшие осадки
WX_ICON_RAIN_HEAVY = "🌧"   # сильные осадки
WX_ICON_WIND       = "💨"
WX_ICON_DRY        = "☁"    # без осадков (облачно / ясно)

# Пороговые значения (если хочешь – меняй)
WIND_ALERT_MS = 12.0   # м/с — сильный ветер
RAIN_ALERT_MM = 8.0    # мм/сутки — «много осадков»


# --signals--

def handle_sighup(signum, frame):
    print("SIGHUP received — reloading ROI config")
    GLOBAL_ROI = reload_roi_from()

if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, handle_sighup)



# -- detection toggles --

# Камеры, на которых включено распознавание номеров.
# Имена здесь – это ключи из CAM_SOURCES (cam_configs/cameras.json).
PLATE_DETECTION_CAMERAS: set[str] = {
    # основной шлагбаум
    "entry gate",
    # сюда потом можно добавлять ещё камеры
    # "entry gate falcone",
    # "dual-sky",
}

# Камеры, на которых включена детекция движения (motion-gate).
# Пока оставим равным PLATE_DETECTION_CAMERAS,
# но в будущем можно разнести.
MOTION_DETECTION_CAMERAS: set[str] = set(PLATE_DETECTION_CAMERAS)