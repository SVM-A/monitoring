# app/qt/frame_bus.py
from __future__ import annotations
from typing import Dict, Optional, Tuple
import queue as pyqueue
import numpy as np
from PyQt6 import QtCore

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
