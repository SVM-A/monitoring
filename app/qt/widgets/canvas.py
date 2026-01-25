# app/qt/widgets/canvas.py
from __future__ import annotations
from typing import Dict, Tuple, Optional, List

import numpy as np
import cv2
from PyQt6 import QtCore, QtGui, QtWidgets

from app.core.config_cams import CAM_SOURCES, GLOBAL_ROI
from app.ui.layout import compose_focus_layout, compose_named_layout
from app.video.ffproxy import apply_roi
from app.video.recording import is_recording_source, next_frame_for, recording_by_id

_VSEP = ":"
_ROI_SUFFIX = " [ROI]"

class CanvasWidget(QtWidgets.QWidget):
    def __init__(self, latest: Dict[str, Optional[np.ndarray]], parent=None):
        super().__init__(parent)
        self.latest = latest
        self.focus_id: Optional[str] = None
        self.fullscreen_id: Optional[str] = None
        self.widget_ids: List[str] = [
            cid for cid, spec in CAM_SOURCES.items() if spec.get("type") == "widget"
        ]
        self.allowed_ids: Optional[List[str]] = None
        self.last_rects: Dict[str, Tuple[int, int, int, int]] = {}
        self.setMouseTracking(True)
        self.setMinimumSize(1280, 720)
        self._right_scroll = 0
        self._right_total = 0
        self._aspect_modes: Dict[str, str] = {}
        self._settings = QtCore.QSettings("MonitoringBazy", "CameraUI")
        self._sb_active = False
        self._sb_track = QtCore.QRect()
        self._sb_thumb = QtCore.QRect()
        self._sb_dragging = False
        self._sb_drag_offset = 0
        # новый параметр: выбранная сетка (именованный шаблон)
        self._layout_key: str = "auto"

        # plate overlays: base_camera_id -> {"bbox_full": [...], "bbox_roi": [...], "expires": float}
        self._plate_overlays: Dict[str, dict] = {}


    def set_layout_key(self, key: str):
        self._layout_key = key or "auto"
        self.update()

    def _is_virtual_half(self, cid: str) -> bool:
        return _VSEP in cid and cid.split(_VSEP)[-1] in ("A", "B")

    def _base_cam(self, vid: str) -> str:
        return vid.split(_VSEP)[0]

    def _visible_frames(self) -> Dict[str, Optional[np.ndarray]]:
        out: Dict[str, Optional[np.ndarray]] = {}

        def add_half(key_full: str, base: str, half: str):
            src = self.latest.get(base)
            spec = CAM_SOURCES.get(base, {})
            if isinstance(src, np.ndarray) and src.size > 0 and (spec or {}).get("split") in ("h", "v"):
                try:
                    if spec["split"] == "v":
                        a, b = np.hsplit(src, 2)
                    else:
                        t, bo = np.vsplit(src, 2)
                        a, b = t, bo
                    out[key_full] = a if half == "A" else b
                    return
                except Exception:
                    pass
            out[key_full] = src

        if self.allowed_ids:
            for aid in self.allowed_ids:
                # ----- ROI-просмотр: <source_id> [ROI] -----
                if aid.endswith(_ROI_SUFFIX):
                    base_id = aid[:-len(_ROI_SUFFIX)]

                    # ROI для записи
                    if is_recording_source(base_id):
                        frame = next_frame_for(base_id)
                        if frame is None:
                            out[aid] = None
                            continue

                        rec = recording_by_id(base_id)
                        roi_key = rec.camera_id if rec else base_id
                        roi_conf = GLOBAL_ROI.get(roi_key)
                        roi_frame = apply_roi(frame, roi_conf)

                        out[aid] = roi_frame
                        continue

                    # ROI для живой камеры — как у тебя было раньше
                    src = self.latest.get(base_id)
                    if isinstance(src, np.ndarray) and src.size > 0:
                        roi_conf = GLOBAL_ROI.get(base_id)
                        roi_frame = apply_roi(src, roi_conf)
                        out[aid] = roi_frame
                    else:
                        out[aid] = None
                    continue
                # --------------------------------------------

                # запись как обычный источник
                if is_recording_source(aid):
                    out[aid] = next_frame_for(aid)
                    continue

                # Половинки (A/B) составных камер
                if _VSEP in aid and self._is_virtual_half(aid):
                    base, part = aid.split(_VSEP, 1)
                    part = "A" if part.upper().startswith("A") else "B"
                    add_half(aid, base, part)
                else:
                    out[aid] = self.latest.get(aid)
            # --- apply plate overlays ---
            now_sec = QtCore.QTime.currentTime().msecsSinceStartOfDay() / 1000.0
            for key, frame in list(out.items()):
                if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                    continue

                # base camera id (для ROI-view отрезаем " [ROI]")
                base = key
                is_roi_view = False
                if base.endswith(_ROI_SUFFIX):
                    is_roi_view = True
                    base = base[:-len(_ROI_SUFFIX)]

                ov = self._plate_overlays.get(base)
                if not ov:
                    continue
                if ov.get("expires", 0) < now_sec:
                    continue

                bbox = ov.get("bbox_roi") if is_roi_view else ov.get("bbox_full")
                if not bbox:
                    continue

                try:
                    x, y, w, h = map(int, bbox)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                except Exception:
                    pass

            return out

        # fallback: все источники проекта (как было)
        for cid, spec in CAM_SOURCES.items():
            frame = self.latest.get(cid)
            split = (spec or {}).get("split")
            if split in ("h", "v") and isinstance(frame, np.ndarray) and frame.size > 0:
                try:
                    if split == "v":
                        left, right = np.hsplit(frame, 2)
                        out[f"{cid}{_VSEP}A"] = left
                        out[f"{cid}{_VSEP}B"] = right
                    else:
                        top, bottom = np.vsplit(frame, 2)
                        out[f"{cid}{_VSEP}A"] = top
                        out[f"{cid}{_VSEP}B"] = bottom
                    continue
                except Exception:
                    pass
            out[cid] = frame
        # --- apply plate overlays (fallback) ---
        now_sec = QtCore.QTime.currentTime().msecsSinceStartOfDay() / 1000.0
        for key, frame in list(out.items()):
            if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
                continue
            base = key.split(_VSEP)[0]  # для половинок берем базовую камеру
            ov = self._plate_overlays.get(base)
            if not ov:
                continue
            if ov.get("expires", 0) < now_sec:
                continue
            bbox = ov.get("bbox_full")
            if not bbox:
                continue
            try:
                x, y, w, h = map(int, bbox)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            except Exception:
                pass
        return out

    def set_focus(self, cid: Optional[str]):
        self.focus_id = cid
        self.update()

    def set_plate_overlay(self, camera_id: str, bbox_full=None, bbox_roi=None, ttl_sec: float = 1.5):
        if not camera_id:
            return
        self._plate_overlays[camera_id] = {
            "bbox_full": bbox_full,
            "bbox_roi": bbox_roi,
            "expires": QtCore.QTime.currentTime().msecsSinceStartOfDay() / 1000.0 + float(ttl_sec),
        }
        self.update()

    def rtsp_ids(self) -> List[str]:
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

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self._sb_dragging and self._sb_active:
            y = e.position().toPoint().y()
            max_scroll = max(0, self._right_total - self.height())
            top_in_track = y - self._sb_drag_offset
            top_in_track = min(max(top_in_track, self._sb_track.top()),
                               self._sb_track.bottom() - self._sb_thumb.height())
            denom = max(1, self._sb_track.height() - self._sb_thumb.height())
            rel = (top_in_track - self._sb_track.top()) / float(denom)
            self._right_scroll = int(rel * max_scroll)
            self.update()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.MouseButton.LeftButton and self._sb_dragging:
            self._sb_dragging = False

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        p = e.position().toPoint()
        x, y = p.x(), p.y()

        # --- правый клик: контекстное меню режимов ---
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            for cid, (x0, y0, x1, y1) in self.last_rects.items():
                if x0 <= x <= x1 and y0 <= y <= y1:
                    self._open_aspect_menu(cid, self.mapToGlobal(p))
                    return
            return

        # --- левый клик: как было — переключение фокуса/выбор камеры ---
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            # клики по плиткам (и камеры, и виджеты)
            for cid, (x0, y0, x1, y1) in self.last_rects.items():
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    continue

                base_id = self._base_cam(cid) if self._is_virtual_half(cid) else cid
                spec = CAM_SOURCES.get(base_id, {}) or {}

                # интерактивные виджеты должны быть кликабельными всегда (и в сетке, и в fullscreen)
                if spec.get("type") == "widget" and spec.get("widget") == "plategate":
                    from app.widgets.widgets import WIDGET_CONTROLLERS
                    ctrl = WIDGET_CONTROLLERS.get(base_id)
                    if ctrl is not None and getattr(ctrl, "handle_ui_click", None):
                        rel_x = (x - x0) / max(1.0, (x1 - x0))
                        rel_y = (y - y0) / max(1.0, (y1 - y0))
                        if ctrl.handle_ui_click(rel_x, rel_y, self):
                            self.update()
                            return

                # Обычный одиночный клик по камерам/виджетам больше ничего не делает
                return

    def mouseDoubleClickEvent(self, e: QtGui.QMouseEvent):
        p = e.position().toPoint()
        x, y = p.x(), p.y()

        if e.button() != QtCore.Qt.MouseButton.LeftButton:
            return

        # определяем по какой плитке был двойной клик
        for cid, (x0, y0, x1, y1) in self.last_rects.items():
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue

            # toggle fullscreen
            if self.fullscreen_id == cid:
                self.fullscreen_id = None
            else:
                self.fullscreen_id = cid

            self.update()
            return

    def _open_aspect_menu(self, cid: str, global_pos: QtCore.QPoint):
        """
        Показать меню выбора режима для конкретного источника.

        Структура:
          - По умолчанию (как есть)
          - Режим заполнения: [Вписать, Заполнить, обрезая, Растянуть*]
          - Соотношение сторон: [Авто (по кадру), Под размер окна, 4:3, 16:9, 16:10]

        Для виджетов пункт «Растянуть» скрыт, чтобы не ломать верстку.
        """
        menu = QtWidgets.QMenu(self)

        # Для половинок cam:A / cam:B смотрим базовую камеру
        base_id = self._base_cam(cid) if self._is_virtual_half(cid) else cid
        spec = CAM_SOURCES.get(base_id, {}) or {}
        is_widget = (spec.get("type") == "widget")

        current = self._mode_for(cid)
        cur_fill, cur_ratio = self._split_mode(current)

        # --- По умолчанию ---
        act_default = menu.addAction("По умолчанию (как есть)")
        act_default.triggered.connect(lambda _chk=False, cid_=cid: self.set_aspect_mode(cid_, "fit"))
        menu.addSeparator()

        # --- Режим заполнения ---
        fill_menu = menu.addMenu("Режим заполнения")
        fill_group = QtGui.QActionGroup(fill_menu)
        fill_group.setExclusive(True)

        fill_modes: list[tuple[str, str]] = [
            ("fit", "Вписать (с полосами)"),
            ("crop", "Заполнить, обрезая"),
        ]
        if not is_widget:
            fill_modes.append(("stretch", "Растянуть под область"))

        for fill_code, label in fill_modes:
            act = fill_menu.addAction(label)
            act.setCheckable(True)
            act.setActionGroup(fill_group)
            if fill_code == cur_fill:
                act.setChecked(True)

            act.triggered.connect(
                lambda _checked=False, cid_=cid, f_=fill_code: self._set_fill_mode(cid_, f_)
            )

        # --- Соотношение сторон ---
        ratio_menu = menu.addMenu("Соотношение сторон")
        ratio_group = QtGui.QActionGroup(ratio_menu)
        ratio_group.setExclusive(True)

        ratio_modes: list[tuple[str, str]] = [
            ("",     "Авто (по кадру)"),
            ("win",  "Под размер окна"),
            ("4:3",  "4 : 3"),
            ("16:9", "16 : 9"),
            ("16:10","16 : 10"),
        ]

        for ratio_code, label in ratio_modes:
            act = ratio_menu.addAction(label)
            act.setCheckable(True)
            act.setActionGroup(ratio_group)
            if ratio_code == cur_ratio:
                act.setChecked(True)
            # отдельный handler, чтобы не было Unresolved reference / late binding
            act.triggered.connect(
                lambda _checked=False, cid_=cid, r_=ratio_code: self._set_ratio_mode(cid_, r_)
            )

        menu.exec(global_pos)

    def paintEvent(self, e: QtGui.QPaintEvent):
        visible = self._visible_frames()

        # собираем карту режимов для всех видимых
        aspect_map = self._build_aspect_map(visible)

        out_w = max(640, self.width())
        out_h = max(360, self.height())

        # === FULLSCREEN (двойной клик) ===
        if self.fullscreen_id:
            cid = self.fullscreen_id
            frame = visible.get(cid)

            if frame is None:
                # безопасный "no signal" на весь экран
                canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

                # ASCII, чтобы не было ????? от OpenCV
                spec = CAM_SOURCES.get(self._base_cam(cid) if self._is_virtual_half(cid) else cid, {}) or {}
                if spec.get("type") == "widget":
                    msg = f"WIDGET {cid} UNAVAILABLE"
                else:
                    msg = "NO SIGNAL"

                cv2.putText(canvas, msg, (20, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3, cv2.LINE_AA)
            else:
                mode = aspect_map.get(cid, "fit")
                from app.ui.layout import fit_into_box_with_mode
                canvas = fit_into_box_with_mode(frame, out_w, out_h, mode)

            rects = {cid: (0, 0, out_w, out_h)}
            self._right_total = out_h
            self.last_rects = rects
        else:
            # === ВСЕГДА СЕТКА (никаких focus-колонок) ===
            if (self._layout_key or "auto") != "auto":
                canvas, rects = compose_named_layout(
                    visible,
                    self._layout_key,
                    out_size=(out_w, out_h),
                    aspect_map=aspect_map,
                )
            else:
                canvas, rects = compose_named_layout(
                    visible,
                    "unknown",
                    out_size=(out_w, out_h),
                    aspect_map=aspect_map,
                )
            self._right_total = out_h
            self.last_rects = rects

        painter = QtGui.QPainter(self)
        img = QtGui.QImage(
            canvas.data, canvas.shape[1], canvas.shape[0],
            canvas.strides[0], QtGui.QImage.Format.Format_BGR888
        )
        painter.drawImage(0, 0, img)
        painter.end()

    def wheelEvent(self, e: QtGui.QWheelEvent):
        return

    def set_allowed_ids(self, ids: List[str]):
        self.allowed_ids = list(ids) if ids else None
        if self.allowed_ids is not None:
            self.widget_ids = [cid for cid in self.allowed_ids
                               if (CAM_SOURCES.get(cid) or {}).get("type") == "widget"]
        else:
            self.widget_ids = [cid for cid, spec in CAM_SOURCES.items() if spec.get("type") == "widget"]
        self.update()

    def _normalize_mode(self, mode: str) -> str:
        """
        Привести значение к допустимому режиму.

        Храним в QSettings строку вида:
          - 'fit' / 'crop' / 'stretch'
          - 'fit@16:9', 'crop@4:3', 'stretch@win'

        Совместимо со старыми значениями ('4:3', '16:9', '16:10').
        """
        if not mode:
            return "fit"

        m_raw = str(mode).strip()
        if "@" in m_raw:
            base_raw, ratio_raw = m_raw.split("@", 1)
        else:
            base_raw, ratio_raw = m_raw, ""

        base = base_raw.lower()
        ratio = ratio_raw.strip()

        # старые значения: '4:3' / '16:9' / '16:10'
        if base not in ("fit", "crop", "stretch"):
            if base_raw in ("4:3", "16:9", "16:10"):
                base = "fit"
                ratio = base_raw
            else:
                base = "fit"

        if ratio not in ("4:3", "16:9", "16:10", "win"):
            ratio = ""

        return f"{base}@{ratio}" if ratio else base

    def _split_mode(self, mode: str) -> tuple[str, str]:
        """
        Разбивает строку режима на (fill_mode, ratio_code).
        fill_mode: 'fit'|'crop'|'stretch'
        ratio_code: ''|'win'|'4:3'|'16:9'|'16:10'
        """
        norm = self._normalize_mode(mode)
        if "@" in norm:
            base, ratio = norm.split("@", 1)
        else:
            base, ratio = norm, ""
        if base not in ("fit", "crop", "stretch"):
            base = "fit"
        if ratio not in ("4:3", "16:9", "16:10", "win"):
            ratio = ""
        return base, ratio

    def _set_fill_mode(self, cid: str, fill: str):
        """Изменить только режим заполнения, сохранив текущие настройки соотношения."""
        cur = self._mode_for(cid)
        _, ratio = self._split_mode(cur)
        fill = (fill or "fit").lower()
        if fill not in ("fit", "crop", "stretch"):
            fill = "fit"
        new_mode = fill if not ratio else f"{fill}@{ratio}"
        self.set_aspect_mode(cid, new_mode)

    def _set_ratio_mode(self, cid: str, ratio: str):
        """Изменить только целевое соотношение, сохранив текущий режим заполнения."""
        cur = self._mode_for(cid)
        fill, _ = self._split_mode(cur)
        ratio = (ratio or "").strip()
        if ratio not in ("4:3", "16:9", "16:10", "win"):
            ratio = ""
        new_mode = fill if not ratio else f"{fill}@{ratio}"
        self.set_aspect_mode(cid, new_mode)

    def _mode_for(self, cid: str) -> str:
        """
        Вернуть текущий режим для источника:
        1) из локального кэша,
        2) если нет — из QSettings,
        3) по умолчанию 'fit'.
        """
        if cid in self._aspect_modes:
            return self._aspect_modes[cid]

        key = f"aspect/{cid}"
        stored = self._settings.value(key, None)
        if stored is not None:
            m = self._normalize_mode(stored)
            self._aspect_modes[cid] = m
            return m

        self._aspect_modes[cid] = "fit"
        return "fit"

    def set_aspect_mode(self, cid: str, mode: str):
        """Установить режим для источника + сохранить в QSettings."""
        m = self._normalize_mode(mode)
        self._aspect_modes[cid] = m
        self._settings.setValue(f"aspect/{cid}", m)
        self.update()

    def _build_aspect_map(self, frames: Dict[str, Optional[np.ndarray]]) -> Dict[str, str]:
        """
        Собрать {id -> режим} для всех видимых источников.
        """
        aspect_map: Dict[str, str] = {}
        for cid in frames.keys():
            aspect_map[cid] = self._mode_for(cid)
        return aspect_map