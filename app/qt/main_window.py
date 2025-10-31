# app/qt/main_window.py — главное окно и цикл опроса ui_queue
from __future__ import annotations
from typing import Dict, Optional, List
import numpy as np
from PyQt6 import QtCore, QtWidgets, QtGui

from app.core.constants import CAM_SOURCES
from app.qt.widgets.canvas import CanvasWidget
from app.qt.widgets.camera_controls import CameraControlDock
from app.video.ffproxy import FFProxyManager, ProxyParams
from app.core.constants import CAM_SOURCES
from app.util.mask import mask_url


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, ui_queue, stop_event_threads, stop_event_proc, grabbers: List, proc):
        super().__init__()
        self.setWindowTitle("Кожевническая 18")
        self.resize(1920, 1080)

        # Хранилище последних кадров по cam_id
        self.latest: Dict[str, Optional[np.ndarray]] = {cid: None for cid in CAM_SOURCES.keys()}

        # Центральный виджет-канвас
        self.canvas = CanvasWidget(self.latest)
        self.setCentralWidget(self.canvas)

        # Очередь UI и таймер опроса (без блокировки)
        self.ui_queue = ui_queue
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)  # ~60 Гц максимум
        self.timer.timeout.connect(self.poll_ui_queue)
        self.timer.start()

        # Жизненный цикл фоновых потоков/процессов
        self.stop_event_threads = stop_event_threads
        self.stop_event_proc = stop_event_proc
        self.grabbers = grabbers
        # быстрый доступ: cam_id -> grabber
        self._gmap = {g.camera_id: g for g in grabbers if hasattr(g, "camera_id")}
        self._proxy = FFProxyManager()  # локальный менеджер ffmpeg-прокси

        # док-панель
        self.ctrl = CameraControlDock(self)

        # --- узкая кнопка-«хэндл» на левой грани док-панели ---
        self._dock_handle = QtWidgets.QToolButton(self)
        self._dock_handle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._dock_handle.setAutoRaise(True)
        self._dock_handle.setFixedSize(16, 48)  # тонкая, «вровень» с кромкой
        self._dock_handle.setStyleSheet("""
            QToolButton {
                background: rgba(0,0,0,80);
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border: 1px solid rgba(255,255,255,40);
            }
        """)
        self._dock_handle.setText("◀")  # когда панель видна — «свернуть вправо»
        self._dock_handle.clicked.connect(self.toggle_controls)

        # следим за изменением геометрии дока, чтобы держать хэндл на кромке
        self.ctrl.installEventFilter(self)
        self._reposition_dock_handle()

        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.ctrl)
        self.ctrl.applyRequested.connect(self._on_apply_video)
        self.ctrl.streamSwitchRequested.connect(self._on_switch_stream)
        self.proc = proc

        # Горячие клавиши (через QtGui.QShortcut)
        self._setup_shortcuts()

        # Мини-статусбар на будущее
        self.statusBar().showMessage("Ready")

        # == Сохранение геометрии/состояния ==
        self._settings = QtCore.QSettings("MonitoringBazy", "CameraUI")
        if (geo := self._settings.value("win/geometry")):
            self.restoreGeometry(geo)
        if (state := self._settings.value("win/state")):
            self.restoreState(state)

        # == Кнопка-«язычок» для сворачивания панели справа ==
        self._dock_anim = QtCore.QPropertyAnimation(self.ctrl, b"maximumWidth", self)
        self._dock_anim.setDuration(160)
        self._dock_anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        toggle_act = QtGui.QAction("Показать/скрыть настройки (Tab)", self)
        toggle_act.setShortcut(QtGui.QKeySequence("Tab"))
        toggle_act.triggered.connect(self.toggle_controls)
        self.addAction(toggle_act)


    def eventFilter(self, obj, ev):
        if obj is self.ctrl and ev.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Move, QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide):
            self._reposition_dock_handle()
        return super().eventFilter(obj, ev)

    def _reposition_dock_handle(self):
        # ставим хэндл на левую кромку док-панели; если док скрыт — прижимаем к правой кромке окна
        if self.ctrl.isVisible() and self.ctrl.maximumWidth() > 0:
            g = self.ctrl.geometry()
            x = g.left() - self._dock_handle.width() + 1
            y = g.top() + (g.height() - self._dock_handle.height()) // 2
            self._dock_handle.move(max(0, x), max(0, y))
            self._dock_handle.setText("▶")  # <<< "◀": когда панель ОТКРЫТА — стрелка вправо (свернуть)
            self._dock_handle.show()
        else:
            # док скрыт — ставим «в воздухе» у правой кромки окна
            x = self.width() - self._dock_handle.width() - 2
            y = (self.height() - self._dock_handle.height()) // 2
            self._dock_handle.move(max(0, x), max(0, y))
            self._dock_handle.setText("◀")  # <<< было "▶": когда панель ЗАКРЫТА — стрелка влево (открыть)
            self._dock_handle.show()

    def resizeEvent(self, e: QtGui.QResizeEvent):
        super().resizeEvent(e)
        self._reposition_dock_handle()

    def toggle_controls(self):
        # считаем, открыта ли панель сейчас
        is_open = self.ctrl.isVisible() and self.ctrl.maximumWidth() > 0

        # всегда создаём свежую анимацию, чтобы не копились .finished-сигналы
        try:
            if hasattr(self, "_dock_anim") and self._dock_anim is not None:
                self._dock_anim.stop()
                self._dock_anim.deleteLater()
        except Exception:
            pass

        self._dock_anim = QtCore.QPropertyAnimation(self.ctrl, b"maximumWidth", self)
        self._dock_anim.setDuration(180)
        self._dock_anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        if is_open:
            # закрываем
            self._dock_anim.setStartValue(self.ctrl.width())
            self._dock_anim.setEndValue(0)

            def _on_close_finished():
                self.ctrl.setHidden(True)
                self._reposition_dock_handle()

            self._dock_anim.finished.connect(_on_close_finished)
        else:
            # открываем
            self.ctrl.setHidden(False)
            self.ctrl.setMaximumWidth(1)
            self._dock_anim.setStartValue(1)
            self._dock_anim.setEndValue(360)
            self._dock_anim.finished.connect(self._reposition_dock_handle)

        self._dock_anim.start()

    def closeEvent(self, event):
        # сохраним геометрию и состояние доков
        try:
            self._settings.setValue("win/geometry", self.saveGeometry())
            self._settings.setValue("win/state", self.saveState())
        except Exception:
            pass
        # дальше — как было:
        return super().closeEvent(event)


    def _on_switch_stream(self, cam_id: str, skey: str):
        spec = CAM_SOURCES.get(cam_id, {})
        streams = (spec or {}).get("streams") or {}
        url = streams.get(skey) or spec.get("url")
        g = self._gmap.get(cam_id)
        if g and url:
            g.set_source(url)
            self.statusBar().showMessage(f"{cam_id}: switch to {skey} → {mask_url(url)}", 3000)

    def _on_apply_video(self, cam_id: str, p: dict):
        # перезапускаем прокси для данного cam_id:
        spec = CAM_SOURCES.get(cam_id, {})
        source_url = spec.get("url")
        if not source_url:
            return
        params = ProxyParams(
            width=int(p.get("width", 1280)),
            height=int(p.get("height", 720)),
            fps=int(p.get("fps", 25)),
            gop=int(p.get("gop", 50)),
            bitrate_kbps=int(p.get("bitrate_kbps", 2500)),
        )
        try:
            runtime = self._proxy.restart(cam_id, source_url, params)
            # переведём граббер на runtime_url (моментально)
            g = self._gmap.get(cam_id)
            if g:
                g.set_source(runtime)
            self.statusBar().showMessage(f"{cam_id}: proxy {params.width}x{params.height}@{params.fps} {params.bitrate_kbps}k → {mask_url(runtime)}", 4000)
        except Exception as e:
            self.statusBar().showMessage(f"{cam_id}: proxy failed → direct", 4000)
            g = self._gmap.get(cam_id)
            if g:
                g.set_source(source_url)


    def _setup_shortcuts(self):
        # Esc — снять фокус
        sc_esc = QtGui.QShortcut(QtGui.QKeySequence("Esc"), self)
        sc_esc.activated.connect(self._clear_focus)

        # [ / ] — листать RTSP
        sc_prev = QtGui.QShortcut(QtGui.QKeySequence("["), self)
        sc_prev.activated.connect(self.canvas.focus_prev_rtsp)

        sc_next = QtGui.QShortcut(QtGui.QKeySequence("]"), self)
        sc_next.activated.connect(self.canvas.focus_next_rtsp)

        # Q — закрыть окно (если хочешь безопаснее — используй 'Ctrl+Q')
        sc_quit = QtGui.QShortcut(QtGui.QKeySequence("Q"), self)
        sc_quit.activated.connect(self.close)

        # Если вдруг на твоей раскладке строки не сработают —
        # раскомментируй вариант с enum-ами:
        # sc_prev = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_BracketLeft), self)
        # sc_next = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_BracketRight), self)
        # sc_quit = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Q), self)

    def poll_ui_queue(self):
        # читаем несколько элементов за тик, чтобы не отстать
        for _ in range(6):
            try:
                cam_id, frame = self.ui_queue.get_nowait()
            except Exception:
                break
            self.latest[cam_id] = frame.copy()
        self.canvas.update()

    def _clear_focus(self):
        self.canvas.set_focus(None)
