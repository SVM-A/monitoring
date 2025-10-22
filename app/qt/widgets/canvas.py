# app/qt/widgets/canvas.py — канвас: компоновка, рендер, клики, фокус
from __future__ import annotations
from typing import Dict, Tuple, Optional, List

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from app.core.constants import CAM_SOURCES
from app.ui.layout import compose_focus_layout


class CanvasWidget(QtWidgets.QWidget):
    def __init__(self, latest: Dict[str, Optional[np.ndarray]], parent=None):
        super().__init__(parent)
        self.latest = latest
        self.focus_id: Optional[str] = None
        self.widget_ids: List[str] = [
            cid for cid, spec in CAM_SOURCES.items() if spec.get("type") == "widget"
        ]
        self.last_rects: Dict[str, Tuple[int, int, int, int]] = {}
        self.setMouseTracking(True)
        self.setMinimumSize(1280, 720)

    def set_focus(self, cid: Optional[str]):
        self.focus_id = cid
        self.update()

    def rtsp_ids(self) -> List[str]:
        return [cid for cid, spec in CAM_SOURCES.items() if spec.get("type") != "widget"]

    def focus_next_rtsp(self):
        ids = self.rtsp_ids()
        if not ids:
            return
        if self.focus_id not in ids:
            self.focus_id = ids[0]
        else:
            i = ids.index(self.focus_id)
            self.focus_id = ids[(i + 1) % len(ids)]
        self.update()

    def focus_prev_rtsp(self):
        ids = self.rtsp_ids()
        if not ids:
            return
        if self.focus_id not in ids:
            self.focus_id = ids[0]
        else:
            i = ids.index(self.focus_id)
            self.focus_id = ids[(i - 1) % len(ids)]
        self.update()

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            p = e.position().toPoint()
            x, y = p.x(), p.y()
            # Попадание в ячейки сетки
            for cid, (x0, y0, x1, y1) in self.last_rects.items():
                if x0 <= x <= x1 and y0 <= y <= y1:
                    # виджеты не берём в фокус
                    if CAM_SOURCES.get(cid, {}).get("type") != "widget":
                        self.focus_id = None if self.focus_id == cid else cid
                        self.update()
                        break

    def paintEvent(self, e: QtGui.QPaintEvent):
        # получаем составной кадр от вашего компоновщика
        out_w = max(640, self.width())
        out_h = max(360, self.height())
        canvas, rects = compose_focus_layout(
            self.latest,
            focus_id=self.focus_id,
            widget_ids=self.widget_ids,
            out_size=(out_w, out_h),
            widget_size=(640, 360)
        )
        self.last_rects = rects

        if canvas is None or canvas.size == 0:
            return

        # BGR -> RGB
        rgb = canvas[:, :, ::-1].copy()
        h, w, _ = rgb.shape

        # QImage «без копирования» по данным numpy-буфера
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.drawImage(0, 0, qimg)
        painter.end()
