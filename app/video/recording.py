# app/video/recording.py

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from app.core.config import video_records_path


@dataclass
class RecordingInfo:
    """
    Метаданные одной записи.
    id         — внутренний идентификатор (строка для Canvas/ViewsDock)
    camera_id  — id камеры, с которой сделана запись
    path       — путь к файлу .mp4
    started_at — datetime начала записи (по имени файла)
    ended_at   — datetime конца записи (по имени файла)
    """
    id: str
    camera_id: str
    path: Path
    started_at: Optional[datetime]
    ended_at: Optional[datetime]


_RECORDINGS_CACHE: Dict[str, RecordingInfo] = {}
_PLAYERS: Dict[str, cv2.VideoCapture] = {}


def _records_dir() -> Path:
    path = video_records_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_filename(p: Path) -> Optional[RecordingInfo]:
    """
    Имя файла: <camera_id>__YYYYmmdd-HHMMSS__YYYYmmdd-HHMMSS.mp4
    """
    name = p.stem  # без .mp4
    parts = name.split("__")
    if len(parts) != 3:
        return None
    cam_id, start_s, end_s = parts

    def parse_dt(s: str) -> Optional[datetime]:
        try:
            return datetime.strptime(s, "%Y%m%d-%H%M%S")
        except Exception:
            return None

    started = parse_dt(start_s)
    ended = parse_dt(end_s)
    rec_id = f"rec::{name}"
    return RecordingInfo(
        id=rec_id,
        camera_id=cam_id,
        path=p,
        started_at=started,
        ended_at=ended,
    )


def scan_recordings() -> Dict[str, RecordingInfo]:
    """
    Полный перескан директории записей. Используется ViewsDock для обновления списка.
    """
    global _RECORDINGS_CACHE
    root = _records_dir()
    items: Dict[str, RecordingInfo] = {}
    for p in sorted(root.glob("*.mp4")):
        info = _parse_filename(p)
        if info:
            items[info.id] = info

    # обновляем кэш, старые плееры, для которых файлов больше нет, закрываем
    removed_ids = set(_RECORDINGS_CACHE.keys()) - set(items.keys())
    for rid in removed_ids:
        cap = _PLAYERS.pop(rid, None)
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    _RECORDINGS_CACHE = items
    return dict(_RECORDINGS_CACHE)


def all_recordings() -> Dict[str, RecordingInfo]:
    """
    Быстрый доступ к последнему кэшу. Если кэш пуст, триггерим scan_recordings().
    """
    if not _RECORDINGS_CACHE:
        return scan_recordings()
    return dict(_RECORDINGS_CACHE)


def recording_by_id(src_id: str) -> Optional[RecordingInfo]:
    return all_recordings().get(src_id)


def is_recording_source(src_id: str) -> bool:
    return src_id.startswith("rec::")


def build_filename(camera_id: str, started_at: datetime, ended_at: datetime) -> Path:
    start_s = started_at.strftime("%Y%m%d-%H%M%S")
    end_s = ended_at.strftime("%Y%m%d-%H%M%S")
    fname = f"{camera_id}__{start_s}__{end_s}.mp4"
    return _records_dir() / fname


class RecordingSession:
    """
    Одна активная запись для конкретной камеры.
    Питается кадрами из FrameBus (UI-поток), пишет в .mp4 через VideoWriter.
    """
    def __init__(self, camera_id: str, fps: float = 25.0):
        self.camera_id = camera_id
        self.started_at = datetime.now()
        # пока пишем во временный файл, по окончании переименуем с известным end_at
        tmp_name = f"{camera_id}__{self.started_at.strftime('%Y%m%d-%H%M%S')}__ongoing.mp4"
        self.tmp_path = _records_dir() / tmp_name
        self._writer: Optional[cv2.VideoWriter] = None
        self._fps = fps
        self._size: Optional[Tuple[int, int]] = None  # (w, h)
        self._closed = False

    def write(self, frame: np.ndarray):
        if self._closed:
            return
        if frame is None or frame.size == 0:
            return
        h, w = frame.shape[:2]
        if self._writer is None:
            self._size = (w, h)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                str(self.tmp_path),
                fourcc,
                self._fps,
                self._size,
            )
            if not self._writer.isOpened():
                # не удалось открыть — выключаем запись
                self._writer.release()
                self._writer = None
                self._closed = True
                return
        else:
            # если внезапно изменился размер — игнорируем кадр
            if self._size != (w, h):
                return
        try:
            self._writer.write(frame)
        except Exception:
            # не хотим валить UI, просто прекращаем запись
            self.close()

    def close(self) -> Optional[Path]:
        if self._closed:
            return None
        self._closed = True
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
        end_at = datetime.now()
        final_path = build_filename(self.camera_id, self.started_at, end_at)
        try:
            if self.tmp_path.exists():
                os.replace(self.tmp_path, final_path)
        except Exception:
            # если переименование не удалось, оставляем tmp
            return self.tmp_path
        return final_path


class RecordingManager:
    """
    Глобальный менеджер записей.
    Подключается к FrameBus.frameReady(cam_id, frame) и пишет кадры только для активных камер.
    """
    def __init__(self):
        self._sessions: Dict[str, RecordingSession] = {}

    # --- API для Qt-части ---

    def start_recording(self, cam_id: str):
        """
        Начать запись с камеры cam_id. Если уже идёт — игнорируем.
        """
        if cam_id in self._sessions:
            return
        self._sessions[cam_id] = RecordingSession(cam_id)

    def stop_recording(self, cam_id: str):
        sess = self._sessions.pop(cam_id, None)
        if not sess:
            return
        final_path = sess.close()
        # Обновляем кэш записей, чтобы ViewsDock сразу увидел новую запись
        scan_recordings()
        return final_path

    def stop_all(self):
        for cam_id in list(self._sessions.keys()):
            self.stop_recording(cam_id)

    # --- callback от FrameBus ---

    def on_frame(self, cam_id: str, frame: np.ndarray):
        sess = self._sessions.get(cam_id)
        if not sess:
            return
        sess.write(frame)


def get_player(src_id: str) -> Optional[cv2.VideoCapture]:
    info = recording_by_id(src_id)
    if not info:
        return None
    cap = _PLAYERS.get(src_id)
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(str(info.path))
        if not cap.isOpened():
            return None
        _PLAYERS[src_id] = cap
    return cap


def next_frame_for(src_id: str) -> Optional[np.ndarray]:
    """
    Возвращает следующий кадр из записи. При достижении конца файла — зацикливает воспроизведение.
    """
    cap = get_player(src_id)
    if cap is None:
        return None
    ok, frame = cap.read()
    if not ok:
        # пробуем зациклить
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception:
            return None
        ok, frame = cap.read()
        if not ok:
            return None
    return frame
