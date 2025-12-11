# app/video/ffproxy.py
from __future__ import annotations

import os
import cv2
import shlex
import signal
import socket
import subprocess
import time
import queue
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass
from multiprocessing import Queue
from threading import Thread, Event


from app.core.config import get_video_tuning, get_debug_flags
from app.util.mask import mask_url


# --ffproxy--

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

        from urllib.parse import quote as urlquote
        safe_cam_path = urlquote(cam_id, safe="")
        port = self._alloc_port(cam_id)
        out_url = f"rtsp://{self.rtsp_host}:{port}/{safe_cam_path}"

        cmd = self._build_cmd(out_url, src_url, params)
        print("[ffproxy] starting:", _safe_cmd_for_log(cmd))

        debug = get_debug_flags().FFPROXY_DEBUG

        # stdout глушим всегда, stderr — только если debug включён
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
        }

        if debug:
            # хотим видеть stderr ffmpeg в debug-режиме
            popen_kwargs["stderr"] = subprocess.PIPE
        else:
            # в обычном режиме полностью молчим
            popen_kwargs["stderr"] = subprocess.DEVNULL

        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        p = subprocess.Popen(cmd, **popen_kwargs)
        # >>> ВАЖНО: сохраняем процесс <<<
        self.processes[cam_id] = p

        if p.poll() is not None:
            if debug and p.stderr:
                try:
                    err = p.stderr.read().decode(errors="ignore")[:2000]
                    print(f"[ffproxy:{cam_id}] ffmpeg stderr:\n{err}")
                except Exception:
                    pass
            self.processes.pop(cam_id, None)
            raise FFProxyError(f"ffmpeg exited immediately for {cam_id} (code={p.returncode})")

        listen_timeout = get_video_tuning().FFPROXY_LISTEN_TIMEOUT_S if hasattr(get_video_tuning(),
                                                                                "FFPROXY_LISTEN_TIMEOUT_S") else 10
        if os.name == "nt":
            listen_timeout = min(listen_timeout, 6)

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
                self.stop(cam_id)
                raise FFProxyError(
                    f"RTSP port {self.rtsp_host}:{port} not listening for {cam_id} within {listen_timeout}s")
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


# --grabber--


try:
    # Новый API OpenCV 4.x
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except AttributeError:
    # На всякий случай для старых версий
    try:
        cv2.setLogLevel(0)
    except Exception:
        pass

class FrameGrabber(Thread):
    def __init__(self, camera_id, src, out_queue: Queue, stop_event: Event,
                 reconnect_delay=5, ui_queue: Optional[queue.Queue]=None, ui_stride: int = 3):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.src = src
        self.out_queue = out_queue          # в процесс-обработчик (JPEG bytes)
        self.stop_event = stop_event
        self.reconnect_delay = reconnect_delay
        self.cap = None
        self.ui_queue = ui_queue            # локальная очередь для отрисовки (numpy кадры)
        self.ui_stride = ui_stride          # каждый N-й кадр кидать в UI (снижаем нагрузку)
        self._frame_idx = 0
        self._pending_src = None
        self._switch_needed = False

    def set_source(self, new_src: str):
        """Запросить смену источника (на прокси/обратно)."""
        self._pending_src = new_src
        self._switch_needed = True

    def _switch_capture(self):
        """Аккуратно переключить cap на новый URL, избегая «чёрного экрана»."""
        import cv2
        new_cap = cv2.VideoCapture(self._pending_src, cv2.CAP_FFMPEG)
        if not new_cap or not new_cap.isOpened():
            new_cap = cv2.VideoCapture(self._pending_src)
            if not new_cap or not new_cap.isOpened():
                print(f"[grabber] cannot switch to new src: {self._pending_src}")
                self._pending_src = None
                self._switch_needed = False
                return
        if getattr(self, "cap", None):
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = new_cap
        self.src = self._pending_src
        self._pending_src = None
        self._switch_needed = False
        print(f"[grabber] switched to: {self.src}")

    def open_capture(self):
        self.cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        if not self.cap or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.src)

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.cap is None or not self.cap.isOpened():
                    self.open_capture()
                    if not self.cap or not self.cap.isOpened():
                        print(f"[{self.camera_id}] can't open stream, retry in {self.reconnect_delay}s")
                        time.sleep(self.reconnect_delay)
                        continue
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if self._switch_needed and self._pending_src:
                    self._switch_capture()
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    print(f"[{self.camera_id}] frame read failed, reconnecting...")
                    self.cap.release()
                    self.cap = None
                    time.sleep(self.reconnect_delay)
                    continue
                if get_debug_flags().GRABBER_DEBUG:
                    print(f"[{self.camera_id}] frame ok, enqueue to UI (every {self.ui_stride})")
                # 1) в процесс — JPEG
                ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    jpg_bytes = encoded.tobytes()
                    try:
                        self.out_queue.put_nowait((self.camera_id, jpg_bytes))
                    except:
                        pass

                # 2) в UI — сырой кадр (раз в ui_stride кадров)
                self._frame_idx += 1
                if self.ui_queue is not None and (self._frame_idx % self.ui_stride == 0):
                    try:
                        self.ui_queue.put_nowait((self.camera_id, frame))
                    except:
                        # если переполнена — просто пропускаем
                        pass

            except Exception as e:
                print(f"[{self.camera_id}] grabber exception:", e)
                time.sleep(self.reconnect_delay)

        if self.cap:
            self.cap.release()
        print(f"[{self.camera_id}] grabber stopped")


# --roi--

def _apply_rect(frame, conf):
    x, y, w, h = conf.get("rect", [0, 0, frame.shape[1], frame.shape[0]])
    x = int(max(0, x))
    y = int(max(0, y))
    w = int(max(1, w))
    h = int(max(1, h))
    x2 = min(frame.shape[1], x + w)
    y2 = min(frame.shape[0], y + h)
    return frame[y:y2, x:x2]


def _apply_poly(frame, conf):
    poly = np.array(
        conf.get(
            "poly",
            [
                [0, 0],
                [frame.shape[1], 0],
                [frame.shape[1], frame.shape[0]],
                [0, frame.shape[0]],
            ],
        ),
        dtype=np.int32,
    )
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    masked = cv2.bitwise_and(frame, frame, mask=mask)
    return masked


def apply_roi(frame, roi_conf):
    """
    Возвращает кадр после применения ROI.

    Поддерживаем форматы:
      {
        "type": "rect",
        "rect": [x, y, w, h]
      }

      {
        "type": "poly",
        "poly": [[x1,y1], [x2,y2], ...]
      }

      {
        "type": "multi",
        "zones": [
          {"type": "rect", ...},
          {"type": "poly", ...},
          ...
        ]
      }

    Для multi: строим общую маску по всем зонам и оставляем только их.
    """
    if frame is None or frame.size == 0:
        return frame
    if not roi_conf:
        return frame

    t = roi_conf.get("type")

    # Обычные случаи
    if t == "rect":
        return _apply_rect(frame, roi_conf)
    if t == "poly":
        return _apply_poly(frame, roi_conf)

    # Несколько зон
    if t == "multi":
        zones = roi_conf.get("zones") or []
        if not zones:
            return frame

        mask = np.zeros(frame.shape[:2], dtype=np.uint8)

        for z in zones:
            z_type = z.get("type")
            if z_type == "rect":
                x, y, w, h = z.get("rect", [0, 0, frame.shape[1], frame.shape[0]])
                x = int(max(0, x))
                y = int(max(0, y))
                w = int(max(1, w))
                h = int(max(1, h))
                x2 = min(frame.shape[1], x + w)
                y2 = min(frame.shape[0], y + h)
                cv2.rectangle(mask, (x, y), (x2, y2), 255, thickness=-1)
            elif z_type == "poly":
                poly = np.array(z.get("poly", []), dtype=np.int32)
                if poly.size == 0:
                    continue
                cv2.fillPoly(mask, [poly], 255)

        masked = cv2.bitwise_and(frame, frame, mask=mask)
        return masked

    # На всякий случай – если тип неизвестен
    return frame
