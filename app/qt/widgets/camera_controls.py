# app/qt/widgets/camera_controls.py
from __future__ import annotations
from typing import Dict, Optional

from PyQt6 import QtCore, QtWidgets

from app.core.constants import CAM_SOURCES

class CameraControlDock(QtWidgets.QDockWidget):
    """Док 'Видео': выбор камеры/потока и параметры прокси (ширина/высота/битрейт/т.д.)."""

    applyRequested = QtCore.pyqtSignal(str, dict)          # (cam_id, params)
    streamSwitchRequested = QtCore.pyqtSignal(str, str)    # (cam_id, stream_key)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__("Видео", parent)
        self.setObjectName("CameraControlDock")
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        # -------- центральная форма
        root = QtWidgets.QWidget(self)
        self.setWidget(root)
        form = QtWidgets.QFormLayout(root)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        # камера
        self.cam = QtWidgets.QComboBox(root)
        self.cam.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        for cid, spec in CAM_SOURCES.items():
            if (spec or {}).get("type") == "widget":
                continue
            self.cam.addItem(cid, cid)
        self.cam.currentIndexChanged.connect(self._on_cam_changed)
        form.addRow("Камера:", self.cam)

        # поток
        self.stream = QtWidgets.QComboBox(root)
        form.addRow("Поток:", self.stream)

        # пресеты качества
        self.preset = QtWidgets.QComboBox(root)
        self.preset.currentIndexChanged.connect(self._apply_preset)
        form.addRow("Пресет:", self.preset)

        # параметры кодирования/прокси
        self.w = QtWidgets.QSpinBox(root); self.w.setRange(160, 4096); self.w.setSingleStep(16); self.w.setValue(1280)
        self.h = QtWidgets.QSpinBox(root); self.h.setRange(120, 4096); self.h.setSingleStep(16); self.h.setValue(720)
        self.fps = QtWidgets.QSpinBox(root); self.fps.setRange(1, 60); self.fps.setValue(25)
        self.gop = QtWidgets.QSpinBox(root); self.gop.setRange(1, 240); self.gop.setValue(50)
        self.bitrate = QtWidgets.QSpinBox(root); self.bitrate.setRange(256, 20000); self.bitrate.setValue(2500)
        form.addRow("Ширина:", self.w)
        form.addRow("Высота:", self.h)
        form.addRow("FPS:", self.fps)
        form.addRow("GOP:", self.gop)
        form.addRow("Битрейт (k):", self.bitrate)

        # кнопки
        btns = QtWidgets.QHBoxLayout()
        self.btnApply = QtWidgets.QPushButton("Применить прокси")
        self.btnSwitch = QtWidgets.QPushButton("Переключить поток")
        self.btnApply.clicked.connect(self._emit_apply)
        self.btnSwitch.clicked.connect(self._emit_switch)
        btns.addWidget(self.btnApply)
        btns.addWidget(self.btnSwitch)
        btnw = QtWidgets.QWidget(root); btnw.setLayout(btns)
        form.addRow(btnw)

        # первичное наполнение выпадающих списков
        self._on_cam_changed(0)

    # ---- helpers ----

    def _on_cam_changed(self, _index: int):
        cid = self.cam.currentData()
        spec: Dict = CAM_SOURCES.get(cid) or {}
        # потоки
        self.stream.clear()
        streams = spec.get("streams") or {}
        if streams:
            for key in streams.keys():
                self.stream.addItem(key, key)
        else:
            self.stream.addItem("main", "main")   # фиктивный «main», если дополнительных нет

        # пресеты
        self.preset.clear()
        presets = spec.get("quality_presets") or []
        if presets:
            for p in presets:
                self.preset.addItem(p.get("label", "?"), p)
        else:
            self.preset.addItem("—", None)

    def _apply_preset(self, _idx: int):
        p = self.preset.currentData()
        if not isinstance(p, dict):
            return
        self.w.setValue(int(p.get("width", self.w.value())))
        self.h.setValue(int(p.get("height", self.h.value())))
        self.fps.setValue(int(p.get("fps", self.fps.value())))
        self.bitrate.setValue(int(p.get("bitrate_kbps", self.bitrate.value())))
        self.gop.setValue(int(p.get("gop", self.gop.value())))

    # ---- emitters ----

    def _emit_apply(self):
        cam_id = self.cam.currentData() or self.cam.currentText()
        params = dict(
            width=self.w.value(),
            height=self.h.value(),
            fps=self.fps.value(),
            gop=self.gop.value(),
            bitrate_kbps=self.bitrate.value(),
        )
        self.applyRequested.emit(cam_id, params)

    def _emit_switch(self):
        cam_id = self.cam.currentData() or self.cam.currentText()
        stream_key = self.stream.currentData() or self.stream.currentText() or "main"
        self.streamSwitchRequested.emit(cam_id, stream_key)
