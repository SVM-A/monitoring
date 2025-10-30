from __future__ import annotations
from typing import Dict, Optional
from PyQt6 import QtWidgets, QtCore

from app.core.constants import CAM_SOURCES
from app.video.ffproxy import ProxyParams
from app.db.camera_registry import CameraSettings

class CameraControlDock(QtWidgets.QDockWidget):
    applyRequested = QtCore.pyqtSignal(str, dict)     # (cam_id, params)
    streamSwitchRequested = QtCore.pyqtSignal(str, str)  # (cam_id, stream_key ["main"/"sub"])

    def __init__(self, parent=None):
        super().__init__("Камера", parent)
        self.setObjectName("CameraControlDock")
        w = QtWidgets.QWidget(self)
        self.setWidget(w)
        lay = QtWidgets.QFormLayout(w)

        self.cam = QtWidgets.QComboBox()
        self.cam.addItems([cid for cid, spec in CAM_SOURCES.items() if spec.get("type") != "widget"])
        lay.addRow("Камера:", self.cam)

        self.stream = QtWidgets.QComboBox()
        lay.addRow("Поток:", self.stream)

        self.preset = QtWidgets.QComboBox()
        lay.addRow("Пресет:", self.preset)

        self.w = QtWidgets.QSpinBox(); self.w.setRange(160, 7680); self.w.setValue(1280)
        self.h = QtWidgets.QSpinBox(); self.h.setRange(120, 4320); self.h.setValue(720)
        self.fps = QtWidgets.QSpinBox(); self.fps.setRange(1, 120); self.fps.setValue(25)
        self.bitrate = QtWidgets.QSpinBox(); self.bitrate.setRange(128, 20000); self.bitrate.setValue(2500)
        self.gop = QtWidgets.QSpinBox(); self.gop.setRange(1, 400); self.gop.setValue(50)
        lay.addRow("Ширина:", self.w)
        lay.addRow("Высота:", self.h)
        lay.addRow("FPS:", self.fps)
        lay.addRow("Битрейт (кбит/с):", self.bitrate)
        lay.addRow("GOP:", self.gop)

        btns = QtWidgets.QHBoxLayout()
        self.btnApply = QtWidgets.QPushButton("Применить")
        self.btnSwitch = QtWidgets.QPushButton("Переключить поток")
        btns.addWidget(self.btnApply); btns.addWidget(self.btnSwitch)
        box = QtWidgets.QWidget(); box.setLayout(btns)
        lay.addRow(box)

        self.cam.currentTextChanged.connect(self._refresh_for_cam)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        self.btnApply.clicked.connect(self._emit_apply)
        self.btnSwitch.clicked.connect(self._emit_switch)

        # первичная инициализация
        self._refresh_for_cam(self.cam.currentText())

    def _refresh_for_cam(self, cam_id: str):
        spec = CAM_SOURCES.get(cam_id, {})
        self.stream.clear()
        streams = spec.get("streams") or {}
        if streams:
            self.stream.addItems(list(streams.keys()))
        else:
            self.stream.addItem("main")  # фиктивный
        self.preset.clear()
        presets = spec.get("quality_presets") or []
        if presets:
            for p in presets:
                self.preset.addItem(p.get("label", "?"), p)
        else:
            self.preset.addItem("—")
        # подтянуть last settings (если есть)
        rec = CameraSettings.load(cam_id)
        if rec and isinstance(rec.data, dict):
            d = rec.data
            self.w.setValue(int(d.get("width", self.w.value())))
            self.h.setValue(int(d.get("height", self.h.value())))
            self.fps.setValue(int(d.get("fps", self.fps.value())))
            self.bitrate.setValue(int(d.get("bitrate_kbps", self.bitrate.value())))
            self.gop.setValue(int(d.get("gop", self.gop.value())))

    def _apply_preset(self, idx: int):
        p = self.preset.currentData()
        if not isinstance(p, dict):
            return
        self.w.setValue(int(p.get("width", self.w.value())))
        self.h.setValue(int(p.get("height", self.h.value())))
        self.fps.setValue(int(p.get("fps", self.fps.value())))
        self.bitrate.setValue(int(p.get("bitrate_kbps", self.bitrate.value())))
        self.gop.setValue(int(p.get("gop", self.gop.value())))

    def _emit_apply(self):
        cam_id = self.cam.currentText()
        params = dict(
            width=self.w.value(), height=self.h.value(),
            fps=self.fps.value(), gop=self.gop.value(),
            bitrate_kbps=self.bitrate.value(),
        )
        self.applyRequested.emit(cam_id, params)

    def _emit_switch(self):
        cam_id = self.cam.currentText()
        stream_key = self.stream.currentText() or "main"
        self.streamSwitchRequested.emit(cam_id, stream_key)
