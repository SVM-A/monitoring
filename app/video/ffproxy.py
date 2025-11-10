# app/video/ffproxy.py
from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Optional
import sys
from urllib.parse import quote as urlquote

from app.core.config import get_video_tuning, get_debug_flags
from app.util.mask import mask_url


def _safe_cmd_for_log(cmd: list[str]) -> str:
    out = []
    for x in cmd:
        if isinstance(x, str) and x.startswith(("rtsp://", "rtsps://")):
            out.append(mask_url(x))
        else:
            out.append(x)
    return " ".join(shlex.quote(x) for x in out)


def _wait_port(host: str, port: int, timeout_s: float = 12.0, step: float = 0.1) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except Exception:
            time.sleep(step)
    return False


def _is_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            return s.connect_ex((host, port)) != 0
    except Exception:
        return False


@dataclass
class ProxyParams:
    width: int = 1280
    height: int = 720
    fps: int = 25
    gop: int = 50
    bitrate_kbps: int = 2500
    preset: str = "veryfast"
    codec: str = "libx264"
    tune_zerolatency: bool = True

    def video_filter(self) -> list[str]:
        if self.width and self.height:
            return ["-vf", f"scale={self.width}:{self.height}"]
        return []

    def encode_args(self) -> list[str]:
        args = [
            "-r", str(self.fps),
            "-g", str(self.gop),
            "-c:v", self.codec,
            "-b:v", f"{self.bitrate_kbps}k",
            "-maxrate", f"{self.bitrate_kbps}k",
            "-bufsize", f"{max(self.bitrate_kbps // 2, 1)}k",
            "-preset", self.preset,
            "-an",
        ]
        if self.tune_zerolatency and self.codec.startswith("libx264"):
            args += ["-tune", "zerolatency"]
        return args


class FFProxyError(RuntimeError):
    pass


class FFProxyManager:
    """
    Поднимает по одному ffmpeg-процессу на камеру и выбирает свободный порт
    начиная с base_port (по умолчанию 8554). Несколько камер => разные порты.
    """
    def __init__(self, rtsp_host: str = "127.0.0.1", base_port: int | None = None):
        self.rtsp_host = rtsp_host
        cfg = get_video_tuning()
        self.base_port = base_port or cfg.FFPROXY_BASE_PORT
        self.processes: Dict[str, subprocess.Popen] = {}
        self.runtime_urls: Dict[str, str] = {}
        self._ports: Dict[str, int] = {}

    def _alloc_port(self, cam_id: str) -> int:
        if cam_id in self._ports:
            return self._ports[cam_id]
        # ищем свободный порт, начиная с base_port
        port = self.base_port
        tried = 0
        while tried < 100:  # достаточно для 100 камер подряд
            if _is_free(self.rtsp_host, port) and port not in self._ports.values():
                self._ports[cam_id] = port
                return port
            port += 1
            tried += 1
        raise FFProxyError("no free RTSP port found near base_port")

    def _build_cmd(self, out_url: str, src_url: str, p: ProxyParams) -> list[str]:
        ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")
        return [
            ffmpeg_bin,
            "-nostdin",
            "-rtsp_transport", "tcp",
            "-i", src_url,
            *p.video_filter(),
            *p.encode_args(),
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            "-rtsp_flags", "listen",
            out_url,
        ]

    def start(self, cam_id: str, src_url: str, params: ProxyParams) -> str:
        self.stop(cam_id)

        # ВАЖНО: кодируем path для RTSP, чтобы пробелы и прочие символы не ломали URL
        safe_cam_path = urlquote(cam_id, safe="")
        port = self._alloc_port(cam_id)
        out_url = f"rtsp://{self.rtsp_host}:{port}/{safe_cam_path}"

        cmd = self._build_cmd(out_url, src_url, params)
        print("[ffproxy] starting:", _safe_cmd_for_log(cmd))

        debug = get_debug_flags().FFPROXY_DEBUG

        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": (None if not debug else subprocess.PIPE),
        }

        # Unix: создаём новую процесс-группу через setsid
        # Windows: создаём новый процесс-группу через CREATE_NEW_PROCESS_GROUP
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        p = subprocess.Popen(cmd, **popen_kwargs)
        if p.poll() is not None:
            if debug and p.stderr:
                try:
                    err = p.stderr.read().decode(errors="ignore")[:2000]
                    print(f"[ffproxy:{cam_id}] ffmpeg stderr:\n{err}")
                except Exception:
                    pass
            raise FFProxyError(f"ffmpeg exited immediately for {cam_id} (code={p.returncode})")

        # Порог ожидания — на Windows короче
        listen_timeout = get_video_tuning().FFPROXY_LISTEN_TIMEOUT_S if hasattr(get_video_tuning(),
                                                                                "FFPROXY_LISTEN_TIMEOUT_S") else 10
        if os.name == "nt":
            listen_timeout = min(listen_timeout, 6)  # не держим UI дольше ~6с на камеру

        # Ждём порт с небольшим прогресс-логом
        t0 = time.time()
        while True:
            ready = _wait_port(self.rtsp_host, port, timeout_s=0.5)
            if ready:
                break
            if (time.time() - t0) > listen_timeout:
                if debug and p.stderr:
                    try:
                        err = p.stderr.read().decode(errors="ignore")[-2000:]
                        print(f"[ffproxy:{cam_id}] listen timeout, stderr tail:\n{err}")
                    except Exception:
                        pass
                # мягко завершим процесс и отдадим понятную ошибку
                self.stop(cam_id)
                raise FFProxyError(
                    f"RTSP port {self.rtsp_host}:{port} not listening for {cam_id} within {listen_timeout}s")

            # полезный прогресс: видно, что не зависли
            print(f"[ffproxy:{cam_id}] waiting RTSP {self.rtsp_host}:{port} ...")
            time.sleep(0.3)

        self.runtime_urls[cam_id] = out_url
        return out_url

    def stop(self, cam_id: str) -> None:
        p = self.processes.pop(cam_id, None)
        self.runtime_urls.pop(cam_id, None)
        if not p:
            return

        try:
            if os.name == "nt":
                # Мы запускали с CREATE_NEW_PROCESS_GROUP → можно послать CTRL_BREAK_EVENT
                try:
                    p.send_signal(signal.CTRL_BREAK_EVENT)
                    # немножко подождём мягкого завершения
                    try:
                        p.wait(timeout=1.0)
                    except Exception:
                        pass
                except Exception:
                    pass
                # если ещё жив — пробуем terminate/kill
                if p.poll() is None:
                    try:
                        p.terminate()
                    except Exception:
                        pass
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass
            else:
                # Unix — штатно гасим всю группу
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except Exception:
                    try:
                        p.terminate()
                    except Exception:
                        pass
        except Exception:
            pass

    def restart(self, cam_id: str, src_url: str, params: ProxyParams) -> str:
        self.stop(cam_id)
        return self.start(cam_id, src_url, params)

    def get_runtime_url(self, cam_id: str) -> Optional[str]:
        return self.runtime_urls.get(cam_id)
