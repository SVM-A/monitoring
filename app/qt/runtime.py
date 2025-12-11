# app/qt/runtime.py
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6 import QtWidgets, QtCore
from typing import Dict, Optional, List
import queue as pyqueue
import numpy as np

from app.core.config import BASE_PATH

class FrameBus(QtCore.QObject):
    """
    Единый брокер кадров: вычитывает ui_queue один раз и рассылает кадры всем подписчикам.
    """
    frameReady = QtCore.pyqtSignal(str, object)  # camera_id, np.ndarray

    def __init__(self, ui_queue: pyqueue.Queue, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.ui_queue = ui_queue
        self.latest: Dict[str, np.ndarray] = {}
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS тик
        self._timer.timeout.connect(self._poll_ui_queue)
        self._timer.start()

    def _poll_ui_queue(self):
        # Считываем несколько элементов за тик, чтобы не отставать
        for _ in range(8):
            try:
                cam_id, frame = self.ui_queue.get_nowait()
            except Exception:
                break
            # Храним последний кадр и шлём сигнал всем окнам
            self.latest[cam_id] = frame
            self.frameReady.emit(cam_id, frame)

    def get_latest(self, cam_id: str):
        return self.latest.get(cam_id)

VIEWS_PATH = Path(BASE_PATH) / "views.json"

@dataclass
class ViewSpec:
    id: str
    name: str
    # Порядок и состав источников (камер/виджетов/половинок cam:A/cam:B)
    selected_ids: Optional[List[str]] = None
    # Выбранная сетка для окна. "auto" | "2x2" | "3x3" | "1L-2S-bottom-1R" | ...
    layout: str = "auto"

def _migrate_item(item: dict) -> ViewSpec:
    vid = item.get("id") or "view-1"
    name = item.get("name") or "Окно"
    # миграция selected_ids
    if "selected_ids" in item and isinstance(item["selected_ids"], list):
        sel = [str(x) for x in item["selected_ids"] if x]
    else:
        sid = item.get("selected_id")
        sel = [sid] if isinstance(sid, str) and sid else []
    # миграция layout
    layout = str(item.get("layout") or "auto")
    return ViewSpec(id=vid, name=name, selected_ids=sel, layout=layout)

def load_views() -> List[ViewSpec]:
    if not VIEWS_PATH.exists():
        return [ViewSpec(id="view-1", name="Окно 1", selected_ids=[], layout="auto")]
    try:
        data = json.loads(VIEWS_PATH.read_text("utf-8"))
        out: List[ViewSpec] = []
        for item in (data or []):
            out.append(_migrate_item(item or {}))
        return out or [ViewSpec(id="view-1", name="Окно 1", selected_ids=[], layout="auto")]
    except Exception:
        return [ViewSpec(id="view-1", name="Окно 1", selected_ids=[], layout="auto")]

def save_views(items: List[ViewSpec]) -> None:
    VIEWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        dict(id=v.id, name=v.name, selected_ids=list(v.selected_ids or []), layout=v.layout)
        for v in items
    ]
    VIEWS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def next_view_id(items: List[ViewSpec]) -> str:
    base = "view-"
    i = 1
    ids = {v.id for v in items}
    while f"{base}{i}" in ids:
        i += 1
    return f"{base}{i}"