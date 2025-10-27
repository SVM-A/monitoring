# app/camera/camera_controller.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.camera.onvif_client import OnvifAuth, OnvifClient
from app.core.config import get_onvif_settings
from app.db.camera_registry import CameraCapabilities, CameraRuntime
from app.video.ffproxy import FFProxyManager, ProxyParams, FFProxyError
from app.util.mask import mask_url

@dataclass
class ApplyResult:
    mode: str               # 'direct' | 'proxy'
    runtime_url: str        # where grabber should connect
    applied: Dict[str, Any] # what we actually applied

class CameraController:
    def __init__(self, proxy: Optional[FFProxyManager] = None):
        self.proxy = proxy or FFProxyManager()

    def apply(self, camera_id: str, source_rtsp: str, desired: Dict[str, Any]) -> ApplyResult:
        caps = CameraCapabilities.load(camera_id)
        onvif_enabled = get_onvif_settings().ONVIF_ENABLE
        supports_onvif = bool(caps and caps.data.get("onvif_supported")) and onvif_enabled

        # режим выбираем как и прежде
        mode = desired.get("mode") or ("direct" if supports_onvif else "proxy")

        if supports_onvif and mode == "direct":
            try:
                onv = caps.data.get("onvif", {})
                auth = OnvifAuth(onv["host"], int(onv.get("port", 80)), onv.get("user"), onv.get("password"))
                client = OnvifClient(auth)
                profile_token = onv.get("profile_token")
                width = int(desired.get("width") or onv.get("width", 1280))
                height = int(desired.get("height") or onv.get("height", 720))
                bitrate_kbps = int(desired.get("bitrate_kbps") or onv.get("bitrate_kbps", 2048))
                fps = desired.get("fps")

                try:
                    client.set_video_encoder(profile_token, width=width, height=height, bitrate_kbps=bitrate_kbps,
                                             fps=fps)
                except Exception:
                    # fallback: найти настоящий video_enc_token и повторить
                    profs = client.list_profiles()
                    venc = None
                    for p in profs:
                        if p.get("profile_token") == profile_token and p.get("video_enc_token"):
                            venc = p["video_enc_token"];
                            break
                    if not venc:
                        for p in profs:
                            if p.get("video_enc_token"): venc = p["video_enc_token"]; break
                    if not venc:
                        raise
                    client.set_video_encoder(venc, width=width, height=height, bitrate_kbps=bitrate_kbps, fps=fps)
                applied = {
                    "mode": "direct",
                    "profile_token": profile_token,
                    "width": width, "height": height, "bitrate_kbps": bitrate_kbps, "fps": fps
                }
                CameraRuntime.save(camera_id, applied)
                return ApplyResult("direct", source_rtsp, applied)
            except Exception as e:
                print(f"[controller] ONVIF apply failed for {camera_id}, fallback to proxy: {e}")

        p = ProxyParams(
            width=int(desired.get("width", 1280)),
            height=int(desired.get("height", 720)),
            bitrate_kbps=int(desired.get("bitrate_kbps", 2500)),
            fps=int(desired.get("fps", 25)),
            gop=int(desired.get("gop", 50)),
            codec=str(desired.get("codec", "libx264")),
            preset=str(desired.get("preset", "veryfast")),
            tune_zerolatency=bool(desired.get("tune_zerolatency", True)),
        )
        try:
            runtime_url = self.proxy.restart(camera_id, source_rtsp, p)
            applied = {"mode": "proxy", "proxy_params": p.__dict__, "source": mask_url(source_rtsp),
                       "runtime_url": runtime_url}
            CameraRuntime.save(camera_id, applied)
            return ApplyResult("proxy", runtime_url, applied)
        except FFProxyError as e:
            print(f"[controller] proxy failed for {camera_id}: {e} → fallback to DIRECT RTSP")
            applied = {"mode": "direct-fallback", "reason": str(e)}
            CameraRuntime.save(camera_id, applied)
            return ApplyResult("direct", source_rtsp, applied)