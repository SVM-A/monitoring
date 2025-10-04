import os
import json
from typing import Dict, Any, Optional
from pathlib import Path
from urllib.parse import quote


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
    base_params = cam_spec.get("params", "")  # << твои обязательные параметры камеры (mode/idc/ids)

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
        url = build_rtsp_for_cam(spec, cam_id)
        if url:
            result[cam_id] = {"type": "rtsp", "url": url}
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
