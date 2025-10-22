# app/qt/main_window.py — главное окно и цикл опроса ui_queue
from __future__ import annotations
from typing import Dict, Optional, List
import numpy as np
from PyQt6 import QtCore, QtWidgets, QtGui

from app.core.constants import CAM_SOURCES
from app.qt.widgets.canvas import CanvasWidget


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
        self.proc = proc

        # Горячие клавиши (через QtGui.QShortcut)
        self._setup_shortcuts()

        # Мини-статусбар на будущее
        self.statusBar().showMessage("Ready")

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

    def closeEvent(self, event):
        # корректное завершение фоновых задач
        try:
            self.stop_event_threads.set()
            self.stop_event_proc.set()
        except Exception:
            pass
        try:
            for g in self.grabbers:
                g.join(timeout=2)
        except Exception:
            pass
        try:
            if self.proc is not None:
                self.proc.join(timeout=3)
        except Exception:
            pass
        return super().closeEvent(event)
