from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, List, Literal, Tuple

from app.db.camera_registry import CameraCapabilities, CameraSettings
from app.camera.camera_controller import CameraController, ApplyResult
from app.core.cam_configs.config_loader import BASE_DIR as CAMCFG_BASE, load_json, build_rtsp_for_cam
from app.util.mask import mask_url
from app.video.ffproxy import FFProxyManager, ProxyParams, FFProxyError


def start_proxy_or_direct(
    cam_id: str,
    src_rtsp: str,
    proxy: FFProxyManager,
    params: ProxyParams,
) -> Tuple[Literal["proxy", "direct"], str]:
    """
    Пытаемся поднять ffmpeg-RTSP-прокси; при неудаче — возвращаем прямой RTSP.
    Возвращает (mode, runtime_url), где mode in {"proxy", "direct"}.
    """
    try:
        runtime = proxy.start(cam_id, src_rtsp, params)
        print(f"[bootstrap] {cam_id}: mode=proxy, runtime={mask_url(runtime)}")
        return "proxy", runtime
    except FFProxyError as e:
        # В лог — без чувствительных данных
        print(f"[bootstrap] {cam_id}: proxy failed ({e}), fallback to direct: {mask_url(src_rtsp)}")
        return "direct", src_rtsp


def prepare_runtime(cameras_cfg: List[dict]) -> Dict[str, ApplyResult]:
    controller = CameraController()
    results: Dict[str, ApplyResult] = {}
    for cam in cameras_cfg:
        cam_id = cam["id"]
        rtsp   = cam["rtsp"]
        onvif  = cam.get("onvif")
        desired = cam.get("desired", {}) or {}

        # 1) capabilities → одно место правды
        CameraCapabilities.save(cam_id, {
            "onvif_supported": bool(onvif),
            "onvif": onvif or {}
        })
        # 2) сохраняем целевые настройки
        CameraSettings.save(cam_id, desired)
        # 3) применяем
        res = controller.apply(cam_id, rtsp, desired)
        results[cam_id] = res
        print(f"[bootstrap] {cam_id}: mode={res.mode}, runtime={mask_url(res.runtime_url)}")
    return results

def _resolve_onvif(spec_onvif: dict | None) -> dict | None:
    if not spec_onvif:
        return None
    o = dict(spec_onvif)
    # поддержка user_env / pass_env
    if o.get("user_env"):
        o["user"] = os.environ.get(o["user_env"], o.get("user") or "")
    if o.get("pass_env"):
        o["password"] = os.environ.get(o["pass_env"], o.get("password") or "")
    return o

def load_cameras(json_path: Path | None = None) -> List[dict]:
    path = json_path or (CAMCFG_BASE / "cameras.json")
    data = load_json(path)
    cams = data.get("cameras", {})
    out: List[dict] = []
    for cam_id, spec in cams.items():
        if str(spec.get("type", "")).lower() == "widget":
            continue
        rtsp = build_rtsp_for_cam(spec, cam_id)
        onvif = _resolve_onvif(spec.get("onvif"))
        out.append({
            "id": cam_id,
            "rtsp": rtsp,
            "onvif": onvif,
            "desired": spec.get("desired") or {},
        })
    return out