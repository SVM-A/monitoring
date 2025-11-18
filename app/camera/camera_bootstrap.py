# app/camera/camera_bootstrap.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from app.camera.camera_controller import CameraController, ApplyResult
from app.db.camera_registry import CameraCapabilities, CameraSettings
from app.core.cam_configs.config_loader import build_rtsp_for_cam, load_json, BASE_DIR as CAMCFG_BASE
import os
from pathlib import Path

from app.util.mask import mask_url


def _resolve_onvif(spec_onvif: dict | None) -> dict | None:
    if not spec_onvif:
        return None
    o = dict(spec_onvif)
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
        if (not spec.get("path")) and spec.get("streams"):
            streams_spec = spec["streams"]
            skey = "main" if "main" in streams_spec else next(iter(streams_spec))
            merged = dict(spec) | dict(streams_spec[skey] or {})
            rtsp = build_rtsp_for_cam(merged, cam_id)
        onvif = _resolve_onvif(spec.get("onvif"))
        out.append({
            "id": cam_id,
            "rtsp": rtsp,
            "onvif": onvif,
            "desired": spec.get("desired") or {},
        })
    return out

def prepare_runtime(cameras_cfg: List[dict]) -> Dict[str, ApplyResult]:
    controller = CameraController()
    results: Dict[str, ApplyResult] = {}

    def _apply_one(cam: dict) -> Tuple[str, ApplyResult]:
        cam_id  = cam["id"]
        rtsp    = cam["rtsp"]
        onvif   = cam.get("onvif")
        desired = cam.get("desired", {}) or {}

        # 1) сохраняем возможности
        CameraCapabilities.save(cam_id, {
            "onvif_supported": bool(onvif),
            "onvif": onvif or {}
        })
        # 2) сохраняем целевые настройки
        CameraSettings.save(cam_id, desired)
        # 3) применяем
        res = controller.apply(cam_id, rtsp, desired)
        return cam_id, res

    # один пулл, один список задач
    with ThreadPoolExecutor(max_workers=max(2, len(cameras_cfg))) as ex:
        futs = [ex.submit(_apply_one, cam) for cam in cameras_cfg]
        for f in as_completed(futs, timeout=60):
            try:
                cam_id, res = f.result(timeout=15)
                results[cam_id] = res
                print(f"[bootstrap] OK: {cam_id} -> {mask_url(res.runtime_url)}")
            except TimeoutError:
                print("[bootstrap] TIMEOUT: camera bootstrap took too long for one task, continue…")
            except Exception as e:
                print(f"[bootstrap] ERROR: {e!r} (continue)")

    return results
