# app/qt/widgets/canvas.py — канвас: компоновка, рендер, клики, фокус
from __future__ import annotations
from typing import Dict, Tuple, Optional, List

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from app.core.constants import CAM_SOURCES
from app.ui.layout import compose_focus_layout  # compose_two_panel больше не нужен тут

_VSEP = ":"  # разделитель для виртуальных половин, напр. "exit:A" / "exit:B"

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

    # ==== хелперы для "виртуальных" половин ====

    def _is_virtual_half(self, cid: str) -> bool:
        return _VSEP in cid and cid.split(_VSEP)[-1] in ("A", "B")

    def _base_cam(self, vid: str) -> str:
        # "exit:A" -> "exit"
        return vid.split(_VSEP)[0]

    def _visible_frames(self) -> Dict[str, Optional[np.ndarray]]:
        """
        Формирует словарь кадров для отрисовки в сетке:
        - обычные камеры -> как есть;
        - камеры со split -> подставляем "cam:A" и "cam:B" как две ячейки.
        """
        out: Dict[str, Optional[np.ndarray]] = {}
        for cid, spec in CAM_SOURCES.items():
            if spec.get("type") == "widget":
                # виджеты остаются как есть
                out[cid] = self.latest.get(cid)
                continue

            frame = self.latest.get(cid)
            split = (spec or {}).get("split")
            if split in ("h", "v") and isinstance(frame, np.ndarray) and frame.size > 0:
                try:
                    if split == "v":
                        left, right = np.hsplit(frame, 2)
                    else:
                        top, bottom = np.vsplit(frame, 2)
                        left, right = top, bottom
                    out[f"{cid}{_VSEP}A"] = left
                    out[f"{cid}{_VSEP}B"] = right
                    # исходный cid в сетку не добавляем, чтобы не было третьей ячейки
                    continue
                except Exception:
                    # если не удалось распилить — показываем целиком
                    pass
            out[cid] = frame
        return out

    # ==== публичные методы ====

    def set_focus(self, cid: Optional[str]):
        self.focus_id = cid
        self.update()

    def rtsp_ids(self) -> List[str]:
        """
        Для листания фокуса хоткеями отдаём те же id, что на экране:
        - обычные камеры -> один id
        - split-камеры -> две «виртуальные» половинки A/B
        """
        ids: List[str] = []
        for cid, spec in CAM_SOURCES.items():
            if spec.get("type") == "widget":
                continue
            split = spec.get("split")
            if split in ("h", "v"):
                ids += [f"{cid}{_VSEP}A", f"{cid}{_VSEP}B"]
            else:
                ids.append(cid)
        return ids

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

    # ==== события ====

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            p = e.position().toPoint()
            x, y = p.x(), p.y()
            for cid, (x0, y0, x1, y1) in self.last_rects.items():
                if x0 <= x <= x1 and y0 <= y <= y1:
                    # виджеты не берём в фокус
                    if CAM_SOURCES.get(cid.split(_VSEP)[0], {}).get("type") != "widget":
                        self.focus_id = None if self.focus_id == cid else cid
                        self.update()
                        break

    def paintEvent(self, e: QtGui.QPaintEvent):
        # 1) готовим "видимые" кадры (с распилом split-камер)
        visible = self._visible_frames()

        # 2) если в фокусе виртуальная половина — подменим кадр для фокуса на соответствующую часть
        focus_id = self.focus_id
        if focus_id and self._is_virtual_half(focus_id):
            base = self._base_cam(focus_id)
            part = focus_id.split(_VSEP)[-1]  # "A"|"B"
            base_spec = CAM_SOURCES.get(base, {})
            src = self.latest.get(base)
            if isinstance(src, np.ndarray) and src.size > 0 and base_spec.get("split") in ("h", "v"):
                try:
                    if base_spec["split"] == "v":
                        a, b = np.hsplit(src, 2)
                    else:
                        t, bo = np.vsplit(src, 2)
                        a, b = t, bo
                    visible[focus_id] = a if part == "A" else b
                except Exception:
                    visible[focus_id] = src  # fallback: целиком

        # 3) рендер лэйаута (если нет фокуса — обычная сетка)
        out_w = max(640, self.width())
        out_h = max(360, self.height())
        canvas, rects = compose_focus_layout(
            visible,
            focus_id=focus_id,
            widget_ids=self.widget_ids,
            out_size=(out_w, out_h),
            widget_size=(640, 360)
        )
        self.last_rects = rects

        if canvas is None or canvas.size == 0:
            return

        # BGR -> RGB и вывод
        rgb = canvas[:, :, ::-1].copy()
        h, w, _ = rgb.shape
        qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.drawImage(0, 0, qimg)
        painter.end()
