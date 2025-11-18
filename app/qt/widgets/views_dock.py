# app/qt/widgets/views_dock.py
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from PyQt6 import QtCore, QtWidgets, QtGui
from app.core.constants import CAM_SOURCES, GLOBAL_ROI
from app.qt.views_state import ViewSpec, load_views, save_views, next_view_id
from app.video.recording import all_recordings

_HALF_LABELS = {
    "h": ("up", "down"),
    "v": ("left", "right"),
}
_HALF_SUFFIX = ("A", "B")

# Доступные сетки по умолчанию — базовый набор
BASE_LAYOUT_OPTIONS = [
    ("auto", "Авто (под число)"),
    ("2x2", "Сетка 2×2"),
    ("3x3", "Сетка 3×3"),
    ("1L-2S-bottom-1R", "1 большой слева + 2 снизу + 1 справа"),
]

def layout_options_for(n: int) -> List[tuple[str,str]]:
    """
    Возвращает список (key, title) сеток, подходящих под текущее количество выбранных источников.
    'auto' — всегда. Поддержка до 16.
    """
    opts = [("auto", "Авто (под число)")]

    # базовые компактные
    if n <= 4:
        opts += [
            ("2x2", "Сетка 2×2"),
            ("spotlight", "Спотлайт (1 большой + справа/снизу)"),
            ("spotlight-balanced", "L-спотлайт (с балансировкой)"),
            ("1L-2S-bottom-1R", "1 большой слева + 2 снизу + 1 справа"),
        ]

    # 5..6 — классические DVR пресеты
    if 5 <= n <= 6:
        opts += [
            ("2x3", "Сетка 2×3"),
            ("spotlight-balanced", "L-спотлайт (с балансировкой)"),
            ("dual-spotlight", "2 большие сверху + мелкие внизу"),
        ]

    # 7..8 — DVR часто «1 большой + 7», «2 большие + мелкие»
    if 7 <= n <= 8:
        opts += [
            ("2x4", "Сетка 2×4"),
            ("spotlight-balanced", "L-спотлайт (с балансировкой)"),
            ("dual-spotlight", "2 большие сверху + мелкие внизу"),
        ]

    # 9 — классическое «3×3», но даём и спотлайт
    if n == 9:
        opts += [
            ("3x3", "Сетка 3×3"),
            ("spotlight-balanced", "L-спотлайт (с балансировкой)"),
            ("dual-spotlight", "2 большие сверху + мелкие внизу"),
        ]

    # 10..16 — обычно «4×4»; альтернативные спотлайты уже мелкие
    if 10 <= n <= 16:
        opts += [("4x4", "Сетка 4×4")]

    # уникализируем и сохраняем порядок
    seen = set(); out = []
    for k, t in opts:
        if k not in seen:
            out.append((k, t)); seen.add(k)
    return out

class ReorderList(QtWidgets.QListWidget):
    """Список источников с чекбоксами и внутренним перетаскиванием."""
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setAlternatingRowColors(True)
        self.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self.itemChanged.connect(lambda *_: self.changed.emit())

    def add_source_item(self, label: str, sid: str, checked: bool):
        it = QtWidgets.QListWidgetItem(label)
        it.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsDragEnabled
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        it.setData(QtCore.Qt.ItemDataRole.UserRole, sid)
        it.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        self.addItem(it)

    def selected_ids_in_order(self) -> List[str]:
        out: List[str] = []
        for i in range(self.count()):
            it = self.item(i)
            if it and it.checkState() == QtCore.Qt.CheckState.Checked:
                sid = it.data(QtCore.Qt.ItemDataRole.UserRole)
                if sid:
                    out.append(str(sid))
        return out

class ViewsDock(QtWidgets.QDockWidget):
    viewSelected = QtCore.pyqtSignal(str)
    viewRenamed = QtCore.pyqtSignal(str, str)
    viewSourceChanged = QtCore.pyqtSignal(str, list)
    viewAdded = QtCore.pyqtSignal(str)
    viewRemoved = QtCore.pyqtSignal(str)

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

        # Новый селектор сетки
        self._layout_combo = QtWidgets.QComboBox()
        self._layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        self._form.addRow("Сетка:", self._layout_combo)

        # Заменяем вертикальный набор чекбоксов на перетаскиваемый список
        self._sources_list = ReorderList(self._inner)
        self._sources_list.changed.connect(self._on_sources_changed)
        self._form.addRow("Показывать:", self._sources_list)

        btns = QtWidgets.QHBoxLayout()
        self._add_btn = QtWidgets.QPushButton("＋")
        self._del_btn = QtWidgets.QPushButton("Удалить")
        self._add_btn.clicked.connect(self._on_add_view)
        self._del_btn.clicked.connect(self._on_del_view)
        btns.addWidget(self._add_btn); btns.addWidget(self._del_btn)
        btn_box = QtWidgets.QWidget(self._inner); btn_box.setLayout(btns)
        self._form.addRow(btn_box)

        self._rebuild_views_list()
        self._rebuild_sources()
        self._apply_active_to_ui()

    def refresh_sources(self):
        """Публичный метод: пересобрать список источников (камера/записи)."""
        self._rebuild_sources()

    def wheelEvent(self, e: QtGui.QWheelEvent):  # блокируем прокрутку наружу
        e.accept()

    def _rebuild_views_list(self):
        self._views_list.blockSignals(True)
        self._views_list.clear()
        for v in self._views:
            self._views_list.addItem(v.name, v.id)
        idx = max(0, next((i for i,v in enumerate(self._views) if v.id == self._active_id), 0))
        self._views_list.setCurrentIndex(idx)
        self._views_list.blockSignals(False)
        self._del_btn.setEnabled(len(self._views) > 1)

    def _add_source_item(self, label: str, sid: str, checked: bool):
        self._sources_list.add_source_item(label, sid, checked)

    def _rebuild_sources(self):
        self._sources_list.clear()
        items: list[tuple[str, str]] = []  # (sid, label)

        recs = all_recordings()
        for rec in recs.values():
            # базовый источник записи
            label = "[запись] "
            if rec.started_at and rec.ended_at:
                label += f"{rec.camera_id} {rec.started_at.strftime('%d.%m %H:%M')}–{rec.ended_at.strftime('%H:%M')}"
            else:
                label += f"{rec.camera_id} {rec.path.name}"
            items.append((rec.id, label))

            # ROI-версия записи, если есть ROI для исходной камеры
            if rec.camera_id in GLOBAL_ROI:
                roi_sid = f"{rec.id} [ROI]"
                roi_label = f"[запись ROI] {rec.camera_id}"
                items.append((roi_sid, roi_label))

        for cid, spec in CAM_SOURCES.items():
            t = (spec or {}).get("type")
            if t == "widget":
                # обычные виджеты
                items.append((cid, f"[виджет] {cid}"))
                continue

            # базовая камера
            items.append((cid, cid))

            # ROI-просмотр для камер с настроенным ROI
            if cid in GLOBAL_ROI:
                # здесь id источника: "<camera_id> [ROI]"
                items.append((f"{cid} [ROI]", f"{cid} — ROI"))

            # половинки составных камер (split A/B)
            split = (spec or {}).get("split")
            if split in ("h", "v"):
                a_lbl, b_lbl = _HALF_LABELS["h" if split == "h" else "v"]
                items.append((f"{cid}:A", f"{cid} — {a_lbl}"))
                items.append((f"{cid}:B", f"{cid} — {b_lbl}"))

        # сортируем по подписи
        items.sort(key=lambda t: t[1].lower())

        cur = next((v for v in self._views if v.id == self._active_id), self._views[0])
        selected = list(cur.selected_ids or [])
        selected_set = set(selected)

        # Сначала добавляем выбранные (в их текущем порядке), потом все остальные
        for sid in selected:
            label = next((lbl for _sid, lbl in items if _sid == sid), sid)
            self._add_source_item(label, sid, True)
        for sid, label in items:
            if sid not in selected_set:
                self._add_source_item(label, sid, False)

        # Обновить список сеток под текущее N
        self._rebuild_layout_options(len(selected), cur.layout)

    def _rebuild_layout_options(self, n: int, current: str):
        opts = layout_options_for(n)
        self._layout_combo.blockSignals(True)
        self._layout_combo.clear()
        cur_idx = 0
        for i, (key, title) in enumerate(opts):
            self._layout_combo.addItem(title, key)
            if key == (current or "auto"):
                cur_idx = i
        self._layout_combo.setCurrentIndex(cur_idx)
        self._layout_combo.blockSignals(False)

    def _apply_active_to_ui(self):
        cur = next((v for v in self._views if v.id == self._active_id), self._views[0])
        self._name_edit.setText(cur.name)
        # пересобрать списки под текущее окно
        self._rebuild_sources()

    def _collect_selected_from_ui(self) -> List[str]:
        result = self._sources_list.selected_ids_in_order()
        return result[:16]  # максимум 16 источников на окно

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

    def _on_layout_changed(self, _idx: int):
        cur = next((v for v in self._views if v.id == self._active_id), None)
        if not cur:
            return
        key = self._layout_combo.currentData() or "auto"
        if cur.layout != key:
            cur.layout = key
            save_views(self._views)
            # при смене сетки — просто сообщаем об изменении источников (перерисовка окна)
            self.viewSourceChanged.emit(cur.id, list(cur.selected_ids or []))

    def _on_sources_changed(self):
        cur = next((v for v in self._views if v.id == self._active_id), None)
        if not cur:
            return
        cur.selected_ids = self._collect_selected_from_ui()
        save_views(self._views)
        # обновить возможные сетки под новое N
        self._rebuild_layout_options(len(cur.selected_ids or []), cur.layout)
        self.viewSourceChanged.emit(cur.id, list(cur.selected_ids))

    def _on_add_view(self):
        vid = next_view_id(self._views)
        v = ViewSpec(id=vid, name=f"Окно {len(self._views)+1}", selected_ids=[], layout="auto")
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
        self._views_list.blockSignals(True)
        idx = max(0, next((i for i, v in enumerate(self._views) if v.id == self._active_id), 0))
        self._views_list.setCurrentIndex(idx)
        self._views_list.blockSignals(False)
        self._apply_active_to_ui()
