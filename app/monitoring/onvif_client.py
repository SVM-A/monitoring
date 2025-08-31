# =============================== app/monitoring/onvif_client.py ===============================
"""
ONVIF-клиент: получаем RTSP-профили для камер, у которых неизвестен точный RTSP.
Пакет: onvif-zeep (pip install onvif-zeep)
В проде пригодится для Dahua/Hik/и т.д., чтобы автоматически вытаскивать URL.
"""
from typing import Optional, List

try:
    from onvif import ONVIFCamera
except Exception:  # библиотека необязательная
    ONVIFCamera = None


def get_rtsp_from_onvif(host: str, port: int, user: str, password: str) -> Optional[str]:
    if ONVIFCamera is None:
        return None
    try:
        cam = ONVIFCamera(host, port, user, password, wsdl=None)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        # Берём первый доступный профиль (или по имени), затем получаем URI
        if not profiles:
            return None
        token = profiles[0].token
        stream_setup = {
            'Stream': 'RTP-Unicast',
            'Transport': {'Protocol': 'RTSP'}
        }
        uri = media.GetStreamUri(stream_setup, token)
        return uri.Uri
    except Exception:
        return None
