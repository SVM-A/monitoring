# app/qt/widgets/views_dock.py
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from PyQt6 import QtCore, QtWidgets, QtGui
from app.core.constants import CAM_SOURCES
from app.qt.views_state import ViewSpec, load_views, save_views, next_view_id

# сопоставление ярлыков половинок
_HALF_LABELS = {
    "h": ("up", "down"),    # горизонтальный сплит -> верх/низ
    "v": ("left", "right"), # вертикальный сплит   -> лево/право
}
# суффиксы используемые в Canvas ("A"/"B")
_HALF_SUFFIX = ("A", "B")

class ViewsDock(QtWidgets.QDockWidget):
    viewSelected = QtCore.pyqtSignal(str)                # window_id выбран
    viewRenamed = QtCore.pyqtSignal(str, str)            # window_id, new_name
    viewSourceChanged = QtCore.pyqtSignal(str, list)     # window_id, selected_ids
    viewAdded = QtCore.pyqtSignal(str)                   # window_id
    viewRemoved = QtCore.pyqtSignal(str)                 # window_id

    def __init__(self, parent=None):
        super().__init__("Окна", parent)
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(260)
        self.setMaximumWidth(360)
        self.setObjectName("ViewsDock")

        self._views: List[ViewSpec] = load_views()
        self._active_id: str = self._views[0].id

        root = QtWidgets.QWidget(self)
        self.setWidget(root)
        v = QtWidgets.QVBoxLayout(root); v.setContentsMargins(6,6,6,6); v.setSpacing(8)

        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(self._scroll)

        self._inner = QtWidgets.QWidget(self._scroll)
        self._scroll.setWidget(self._inner)
        self._form = QtWidgets.QFormLayout(self._inner)
        self._form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self._form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self._views_list = QtWidgets.QComboBox()
        self._views_list.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._views_list.currentIndexChanged.connect(self._on_view_switch)
        self._form.addRow("Окно:", self._views_list)

        self._name_edit = QtWidgets.QLineEdit()
        self._name_edit.editingFinished.connect(self._on_rename_active)
        self._form.addRow("Название:", self._name_edit)

        # Контейнер с чекбоксами источников
        self._sources_box = QtWidgets.QWidget(self._inner)
        self._sources_layout = QtWidgets.QVBoxLayout(self._sources_box)
        self._sources_layout.setSpacing(2)
        self._form.addRow("Показывать:", self._sources_box)

        # Кнопки добавить/удалить окно
        btns = QtWidgets.QHBoxLayout()
        self._add_btn = QtWidgets.QPushButton("＋")
        self._del_btn = QtWidgets.QPushButton("Удалить")
        self._add_btn.clicked.connect(self._on_add_view)
        self._del_btn.clicked.connect(self._on_del_view)
        btns.addWidget(self._add_btn); btns.addWidget(self._del_btn)
        btn_box = QtWidgets.QWidget(self._inner); btn_box.setLayout(btns)
        self._form.addRow(btn_box)

        # инициализация
        self._rebuild_views_list()
        self._rebuild_sources()
        self._apply_active_to_ui()

    # блокируем прокрутку наружу
    def wheelEvent(self, e: QtGui.QWheelEvent):  # type: ignore[override]
        e.accept()

    # ——— helpers ———
    def _rebuild_views_list(self):
        self._views_list.blockSignals(True)
        self._views_list.clear()
        for v in self._views:
            self._views_list.addItem(v.name, v.id)
        idx = max(0, next((i for i,v in enumerate(self._views) if v.id == self._active_id), 0))
        self._views_list.setCurrentIndex(idx)
        self._views_list.blockSignals(False)
        self._del_btn.setEnabled(len(self._views) > 1)

    def _add_source_checkbox(self, label: str, sid: str) -> QtWidgets.QCheckBox:
        cb = QtWidgets.QCheckBox(label, self._sources_box)
        cb.setProperty("sid", sid)  # например "exit", "dual-sky:A", "calclockweather"
        cb.stateChanged.connect(self._on_sources_changed)
        self._sources_layout.addWidget(cb)
        return cb

    def _rebuild_sources(self):
        # очистка
        while self._sources_layout.count():
            it = self._sources_layout.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

        # список «камер и виджетов», дополненный половинками для split-камер
        items: list[tuple[str, str]] = []  # (sid, label)
        for cid, spec in CAM_SOURCES.items():
            t = (spec or {}).get("type")
            if t == "widget":
                items.append((cid, f"[виджет] {cid}"))
                continue
            # обычная камера целиком
            items.append((cid, cid))
            # если split — добавляем A/B как up/down (или left/right)
            split = (spec or {}).get("split")
            if split in ("h", "v"):
                a_lbl, b_lbl = _HALF_LABELS["h" if split == "h" else "v"]
                items.append((f"{cid}:A", f"{cid} — {a_lbl}"))
                items.append((f"{cid}:B", f"{cid} — {b_lbl}"))

        # сортировка: виджеты отдельно не поднимаем — просто по label
        items.sort(key=lambda t: t[1].lower())

        # создаём чекбоксы
        for sid, label in items:
            self._add_source_checkbox(label, sid)

        self._sources_layout.addStretch(1)

    def _apply_active_to_ui(self):
        cur = next((v for v in self._views if v.id == self._active_id), self._views[0])
        self._name_edit.setText(cur.name)
        # отметить выбранные чекбоксы
        selected = set(cur.selected_ids or [])
        for i in range(self._sources_layout.count()):
            it = self._sources_layout.itemAt(i).widget()
            if isinstance(it, QtWidgets.QCheckBox):
                sid = it.property("sid")
                it.blockSignals(True)
                it.setChecked(sid in selected)
                it.blockSignals(False)

    def _collect_selected_from_ui(self) -> List[str]:
        sids: List[str] = []
        for i in range(self._sources_layout.count()):
            it = self._sources_layout.itemAt(i).widget()
            if isinstance(it, QtWidgets.QCheckBox) and it.isChecked():
                sid = it.property("sid")
                if sid:
                    sids.append(str(sid))
        return sids

    # ——— handlers ———
    def _on_view_switch(self, idx: int):
        vid = self._views_list.itemData(idx)
        if not vid:
            return
        self._active_id = vid
        self._apply_active_to_ui()
        self.viewSelected.emit(self._active_id)

    def _on_rename_active(self):
        cur = next((v for v in self._views if v.id == self._active_id), None)
        if not cur:
            return
        new_name = self._name_edit.text().strip() or cur.name
        if new_name != cur.name:
            cur.name = new_name
            save_views(self._views)
            self._rebuild_views_list()
            self.viewRenamed.emit(cur.id, cur.name)

    def _on_sources_changed(self, _state: int):
        cur = next((v for v in self._views if v.id == self._active_id), None)
        if not cur:
            return
        cur.selected_ids = self._collect_selected_from_ui()
        save_views(self._views)
        self.viewSourceChanged.emit(cur.id, list(cur.selected_ids))

    def _on_add_view(self):
        vid = next_view_id(self._views)
        v = ViewSpec(id=vid, name=f"Окно {len(self._views)+1}", selected_ids=[])
        self._views.append(v)
        save_views(self._views)
        self._rebuild_views_list()
        self._active_id = vid
        self._apply_active_to_ui()
        self.viewAdded.emit(vid)

    def _on_del_view(self):
        if len(self._views) <= 1:
            return
        i = next((i for i,v in enumerate(self._views) if v.id == self._active_id), 0)
        removed = self._views.pop(i)
        save_views(self._views)
        self._active_id = self._views[max(0, i-1)].id
        self._rebuild_views_list()
        self._apply_active_to_ui()
        self.viewRemoved.emit(removed.id)

    # ——— публичные ———
    def views(self) -> List[ViewSpec]:
        return list(self._views)

    def set_active_view(self, view_id: str):
        self._active_id = view_id or self._active_id
        # Обновляем комбо без сигналов, чтобы не затронуть другие окна
        self._views_list.blockSignals(True)
        idx = max(0, next((i for i, v in enumerate(self._views) if v.id == self._active_id), 0))
        self._views_list.setCurrentIndex(idx)
        self._views_list.blockSignals(False)
        # Обновляем чекбоксы под выбранное окно
        self._apply_active_to_ui()
