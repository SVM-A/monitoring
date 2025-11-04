# app/qt/window_manager.py
from __future__ import annotations
from typing import Dict, Optional, List
from PyQt6 import QtWidgets
from app.qt.main_window import MainWindow
from app.qt.views_state import load_views, ViewSpec
from app.qt.frame_bus import FrameBus


class WindowManager(QtWidgets.QWidget):
    """
    Простой менеджер: держит ссылку на все MainWindow и следит за списком ViewSpec.
    """
    def __init__(self, ui_queue, stop_event_threads, stop_event_proc, grabbers, proc):
        super().__init__()
        self.ui_queue = ui_queue
        self.frame_bus = FrameBus(self.ui_queue, parent=self)
        self.stop_event_threads = stop_event_threads
        self.stop_event_proc = stop_event_proc
        self.grabbers = grabbers
        self.proc = proc

        self._views: List[ViewSpec] = load_views()
        self._wins: Dict[str, MainWindow] = {}

    def boot(self):
        # поднять все окна из настроек
        for v in self._views:
            self._spawn_window(v)

    def _spawn_window(self, v: ViewSpec):
        if v.id in self._wins:
            return

        # ВАЖНО: не передаём selected_id при создании,
        # чтобы окно не "увеличивало" первую камеру само по себе.
        w = MainWindow(
            self.ui_queue, self.stop_event_threads, self.stop_event_proc,
            self.grabbers, self.proc, window_id=v.id, selected_id=None,
            frame_bus=self.frame_bus
        )
        # Привяжем заголовок и саму панель «Окна» к этому view_id
        w.setWindowTitle(v.name)
        # У каждого MainWindow свой экземпляр ViewsDock, жёстко активируем нужный view
        try:
            w.viewsDock.set_active_view(v.id)
        except Exception:
            pass

        # Первичная синхронизация списка выбранных источников -> канвас
        try:
            w._apply_views_to_canvas()
        except Exception:
            pass

        # Сигналы из конкретного окна
        w.viewsDock.viewAdded.connect(self._on_view_added)
        w.viewsDock.viewRemoved.connect(self._on_view_removed)
        w.viewsDock.viewSourceChanged.connect(self._on_view_source)
        w.viewsDock.viewRenamed.connect(self._on_view_renamed)

        w.show()
        self._wins[v.id] = w

    # ——— сигналы ———
    def _on_view_added(self, view_id: str):
        # обновим модель и создадим окно
        self._views = load_views()
        v = next((x for x in self._views if x.id == view_id), None)
        if v:
            self._spawn_window(v)

    def _on_view_removed(self, view_id: str):
        self._views = load_views()
        w = self._wins.pop(view_id, None)
        if w:
            # окно само закроется по сигналу
            pass

    def _on_view_source(self, view_id: str, selected_ids: list):
        """
        Теперь сигнал отдаёт список выбранных источников.
        Фокус можно мягко синхронизировать на первую позицию (или убрать, если список пуст).
        Отрисовку самого списка делает окно через собственный обработчик.
        """
        w = self._wins.get(view_id)
        if not w:
            return
        if selected_ids:
            # ставим фокус на первый выбранный источник — удобно при первом выборе
            w.apply_view_source(selected_ids[0])
        else:
            w.apply_view_source(None)

    def _on_view_renamed(self, view_id: str, new_name: str):
        if view_id in self._wins:
            self._wins[view_id].setWindowTitle(new_name)
