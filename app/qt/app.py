# app/qt/app.py — инициализация Qt-приложения
from __future__ import annotations
import sys
from typing import List
from PyQt6 import QtWidgets

from app.qt.window_manager import WindowManager
from app.qt.main_window import MainWindow
from app.ui.theme import load_qss, setup_hidpi


def run_qt_app(ui_queue, stop_event_threads, stop_event_proc, grabbers, proc):
    app = QtWidgets.QApplication(sys.argv)

    manager = WindowManager(ui_queue, stop_event_threads, stop_event_proc, grabbers, proc)
    manager.boot()

    sys.exit(app.exec())