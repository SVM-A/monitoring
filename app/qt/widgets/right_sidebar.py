# app/qt/widgets/right_sidebar.py
from __future__ import annotations
from PyQt6 import QtCore, QtWidgets
from app.qt.widgets.camera_controls import CameraControlDock
from app.qt.widgets.views_dock import ViewsDock


class RightSidebarDock(QtWidgets.QDockWidget):
    """
    Единая правая панель с табами («Окна»/«Видео») без крестика.
    """

    viewSelected = QtCore.pyqtSignal(str)
    viewRenamed = QtCore.pyqtSignal(str, str)
    viewSourceChanged = QtCore.pyqtSignal(str, list)  # список выбранных источников
    viewAdded = QtCore.pyqtSignal(str)
    viewRemoved = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Панель", parent)
        self.setObjectName("RightSidebarDock")
        self.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable)

        self._tabs = QtWidgets.QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._tabs.setTabsClosable(False)
        self._tabs.setTabPosition(QtWidgets.QTabWidget.TabPosition.North)
        self.setWidget(self._tabs)

        self.ctrl = CameraControlDock(self)
        self.views = ViewsDock(self)

        self.visibilityChanged.connect(self._on_visibility_changed)

        self._views_root = self.views.widget()
        self.views.setParent(None)
        self.ctrl.setParent(None)

        self._tabs.addTab(self._views_root, "Окна")
        self._tabs.addTab(self.ctrl.widget(), "Видео")

        # Прокси сигналов «Окна»
        self.views.viewSelected.connect(self.viewSelected.emit)
        self.views.viewRenamed.connect(self.viewRenamed.emit)
        self.views.viewSourceChanged.connect(self.viewSourceChanged.emit)
        self.views.viewAdded.connect(self.viewAdded.emit)
        self.views.viewRemoved.connect(self.viewRemoved.emit)

        self.visibilityChanged.connect(lambda _v: None)
        self.setMaximumWidth(360)

    def ensure_visible(self):
        if not self.isVisible():
            self.show()
        if self.maximumWidth() == 0:
            self.setMaximumWidth(360)

    def is_open(self) -> bool:
        return self.isVisible() and self.maximumWidth() > 0

    def animate_open(self, parent: QtWidgets.QWidget):
        self.show()
        self.setMaximumWidth(1)
        anim = QtCore.QPropertyAnimation(self, b"maximumWidth", parent)
        anim.setDuration(180)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.setStartValue(1)
        anim.setEndValue(360)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def animate_close(self, parent: QtWidgets.QWidget):
        anim = QtCore.QPropertyAnimation(self, b"maximumWidth", parent)
        anim.setDuration(180)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.setStartValue(self.width())
        anim.setEndValue(0)
        anim.finished.connect(self.hide)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def camera_controls(self) -> CameraControlDock:
        return self.ctrl

    def views_dock(self) -> ViewsDock:
        return self.views

    def _on_visibility_changed(self, visible: bool):
        # при каждом открытии обновляем список источников,
        # чтобы в нём появились свежезаписанные файлы
        if visible:
            try:
                self.views.refresh_sources()
            except Exception:
                pass
