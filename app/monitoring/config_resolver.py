# app/monitoring/config_resolver.py
from typing import Any, Optional
import os
from urllib.parse import quote

from app.core.config import (
    get_receiver_settings,      # FalconEyeReceiverSettings
    get_camera_settings,        # FalconEyeCameraSettings
)
from app.monitoring.onvif_client import get_rtsp_from_onvif

# Если у тебя будет Dahua — сделай похожий Settings, как FalconEyeReceiverSettings
# и верни тут get_dahua_receiver_settings()
try:
    from app.core.config import get_dahua_receiver_settings
except Exception:
    get_dahua_receiver_settings = None  # опционально

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name, default)
    return val

def resolve_rtsp(rtsp_cfg: Any) -> str:
    """
    Принимает:
      - строку (если вдруг решишь класть в env полный URL)
      - dict c provider + параметрами (см. cameras.yaml)
    Возвращает готовый RTSP-URL.
    """
    if isinstance(rtsp_cfg, str):
        # Поддержка ${VAR} через expandvars, если решишь хранить итоговый URL в секрете
        return os.path.expandvars(rtsp_cfg)

    if isinstance(rtsp_cfg, dict):
        provider = rtsp_cfg.get("provider")
        if provider == "falcon_eye_receiver":
            s = get_receiver_settings()
            ch = rtsp_cfg.get("channel")
            st = rtsp_cfg.get("subtype")
            return s.rtsp(channel=ch, subtype=st)

        if provider == "falcon_eye_camera":
            s = get_camera_settings()
            which = rtsp_cfg.get("which", "main")
            mode  = rtsp_cfg.get("mode")
            idc   = rtsp_cfg.get("idc")
            ids   = rtsp_cfg.get("ids")
            return s.stream(which=which, mode=mode, idc=idc, ids=ids)

        if provider == "dahua_receiver":
            if get_dahua_receiver_settings is None:
                raise RuntimeError("DahuaReceiverSettings не подключён")
            s = get_dahua_receiver_settings()
            ch = rtsp_cfg.get("channel")
            st = rtsp_cfg.get("subtype")
            return s.rtsp(channel=ch, subtype=st)

        if provider == "onvif":
            host = _env(rtsp_cfg.get("host_env")) or rtsp_cfg.get("host")
            port = int(_env(rtsp_cfg.get("port_env"), "80"))
            user = _env(rtsp_cfg.get("user_env")) or rtsp_cfg.get("user")
            pwd  = _env(rtsp_cfg.get("pass_env")) or rtsp_cfg.get("pass")
            if not all([host, user, pwd]):
                raise RuntimeError("ONVIF: не хватает host/user/pass (через *_env или прямые поля)")
            uri = get_rtsp_from_onvif(host, port, user, pwd)
            if not uri:
                raise RuntimeError("ONVIF: не удалось получить RTSP URI")
            return uri

    raise ValueError(f"Невалидный rtsp-конфиг: {rtsp_cfg!r}")