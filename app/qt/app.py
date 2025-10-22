# app/qt/app.py — инициализация Qt-приложения
from __future__ import annotations
import sys
from typing import List
from PyQt6 import QtWidgets

from app.qt.main_window import MainWindow
from app.ui.theme import load_qss, setup_hidpi


def run_qt_app(ui_queue, stop_event_threads, stop_event_proc, grabbers: List, proc):
    # HiDPI и базовые атрибуты
    setup_hidpi()
    app = QtWidgets.QApplication(sys.argv)

    # Применяем QSS
    app.setStyleSheet(load_qss())

    # Главное окно
    win = MainWindow(
        ui_queue=ui_queue,
        stop_event_threads=stop_event_threads,
        stop_event_proc=stop_event_proc,
        grabbers=grabbers,
        proc=proc
    )
    win.show()
    sys.exit(app.exec())
