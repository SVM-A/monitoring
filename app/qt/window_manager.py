# app/qt/window_manager.py — главное окно и цикл опроса ui_queue
from __future__ import annotations
from typing import Dict, Optional, List
import numpy as np
from PyQt6 import QtCore, QtWidgets, QtGui

from app.qt.widgets.canvas import CanvasWidget
from app.video.ffproxy import FFProxyManager, ProxyParams
from app.core.config_cams import CAM_SOURCES
from app.util.mask import mask_url
from app.qt.widgets.right_sidebar import RightSidebarDock
from app.qt.runtime import load_views, ViewSpec, FrameBus
from app.video.recording import RecordingManager
from app.qt.widgets.gate_control import GateControlDock

class MainWindow(QtWidgets.QMainWindow):
    viewChanged = QtCore.pyqtSignal(str)  # если уже есть — ок
    recordStartRequested = QtCore.pyqtSignal(str)
    recordStopRequested = QtCore.pyqtSignal(str)

    def __init__(self, ui_queue, stop_event_threads, stop_event_proc, grabbers: List, proc,
                 window_id: str = "view-1", selected_id: Optional[str] = None,
                 frame_bus: Optional[FrameBus] = None):
        super().__init__()
        self.window_id = window_id
        self.setWindowTitle("Кожевническая 18")
        self.resize(1920, 1080)

        # Хранилище последних кадров
        self.latest: Dict[str, Optional[np.ndarray]] = {cid: None for cid in CAM_SOURCES.keys()}

        # Канвас (поддерживает фокус и правую колонку миниатюр)  :contentReference[oaicite:3]{index=3}
        self.canvas = CanvasWidget(self.latest)
        self.setCentralWidget(self.canvas)

        # Очереди/сервисные объекты
        self.ui_queue = ui_queue  # оставим если где-то ещё нужно, но не читаем её здесь
        self.frame_bus = frame_bus  # общий брокер кадров
        if self.frame_bus:
            self.frame_bus.frameReady.connect(self._on_frame_ready)
        self.stop_event_threads = stop_event_threads
        self.stop_event_proc = stop_event_proc
        self.grabbers = grabbers
        self._gmap = {g.camera_id: g for g in grabbers if hasattr(g, "camera_id")}
        self._proxy = FFProxyManager()
        self.proc = proc

        # == Единая правая панель (табы «Окна» / «Видео») ==
        self.sidebar = RightSidebarDock(self)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.sidebar)
        # --- Отдельное окно «Шлагбаум» ---
        self.gateDock = GateControlDock(self)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.gateDock)

        # Размещаем под основной правой панелью (вертикальный сплит)
        try:
            self.splitDockWidget(self.sidebar, self.gateDock, QtCore.Qt.Orientation.Vertical)
        except Exception:
            # на всякий случай, если splitDockWidget недоступен/ругается — просто игнорируем
            pass

        # >>> совместимость со старым кодом (window_manager ожидает .viewsDock)
        self.viewsDock = self.sidebar.views_dock()

        ctrl = self.sidebar.camera_controls()
        ctrl.applyRequested.connect(self._on_apply_video)
        ctrl.streamSwitchRequested.connect(self._on_switch_stream)
        ctrl.recordStartRequested.connect(self._on_record_start)
        ctrl.recordStopRequested.connect(self._on_record_stop)

        # Привяжем панель «Окна» именно к нашему window_id
        try:
            self.viewsDock.set_active_view(self.window_id)
        except Exception:
            pass

        # Подписки на события «Окна»
        self.sidebar.viewSourceChanged.connect(self._apply_views_to_canvas)
        self.sidebar.viewAdded.connect(self._apply_views_to_canvas)
        self.sidebar.viewRemoved.connect(self._apply_views_to_canvas)
        self.sidebar.viewRenamed.connect(lambda *_: None)
        self.sidebar.viewSelected.connect(lambda *_: None)

        # Видео-кнопки (изнутри вкладки «Видео»)
        self.sidebar.camera_controls().applyRequested.connect(self._on_apply_video)
        self.sidebar.camera_controls().streamSwitchRequested.connect(self._on_switch_stream)

        # Следить за показом/скрытием панели — для хэндла
        self.sidebar.visibilityChanged.connect(self._on_sidebar_visibility)
          # --- узкая кнопка-«хэндл» на левой грани док-панели ---
        self._dock_handle = QtWidgets.QToolButton(self)
        self._dock_handle.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._dock_handle.setAutoRaise(True)
        self._dock_handle.setFixedSize(16, 48)
        self._dock_handle.setStyleSheet("""
            QToolButton {
                background: rgba(0,0,0,80);
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border: 1px solid rgba(255,255,255,40);
            }
        """)
        self._dock_handle.setText("◀")
        self._dock_handle.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._dock_handle.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoMousePropagation, True)
        self._dock_handle.clicked.connect(self.toggle_controls)

        # следим за геометрией единственной панели
        self.sidebar.installEventFilter(self)
        self._reposition_dock_handle()
        self._setup_menu()

        # === Начальное ограничение канваса выбранными "окнами" ===
        self._apply_views_to_canvas()


        # Горячие клавиши + статусбар — как было
        self._setup_shortcuts()
        self.statusBar().showMessage("Ready")

        # Настройки окна — уникальные per-window
        self._settings = QtCore.QSettings("MonitoringBazy", "CameraUI")
        geo_key = f"{self.window_id}/geometry"
        st_key = f"{self.window_id}/state"
        if (geo := self._settings.value(geo_key)):
            self.restoreGeometry(geo)
        if (state := self._settings.value(st_key)):
            self.restoreState(state)

        # Применим выбранный источник, если задан
        if selected_id:
            self.apply_view_source(selected_id)

    @QtCore.pyqtSlot(bool)
    def _on_sidebar_visibility(self, _vis: bool):
        # Когда панель показывается/скрывается, просто обновляем позицию хэндла.
        # Слот как bound-method корректно авто-отключится при удалении окна.
        try:
            self._reposition_dock_handle()
        except RuntimeError:
            # окно уже утилизировано — игнорируем
            pass


    def _on_record_start(self, cam_id: str):
        # пробрасываем сигнал менеджеру + можно показать статусбар
        self.recordStartRequested.emit(cam_id)
        try:
            self.statusBar().showMessage(f"{cam_id}: запись начата", 3000)
        except Exception:
            pass

    def _on_record_stop(self, cam_id: str):
        self.recordStopRequested.emit(cam_id)
        try:
            self.statusBar().showMessage(f"{cam_id}: запись остановлена", 3000)
        except Exception:
            pass

    def _on_frame_ready(self, cam_id: str, frame):
        # локальное хранилище — своя dict, чтобы не трогать других
        self.latest[cam_id] = frame if frame is None else frame.copy()
        self.canvas.update()


    def _setup_menu(self):
        menu_view = self.menuBar().addMenu("Вид")

        # Боковая панель
        act_sidebar = QtGui.QAction("Показать боковую панель", self)
        act_sidebar.triggered.connect(self._ensure_sidebar_visible)
        menu_view.addAction(act_sidebar)

        # Отдельная панель шлагбаума
        self._act_gate = QtGui.QAction("Панель шлагбаума", self)
        self._act_gate.setCheckable(True)
        self._act_gate.setChecked(True)  # по умолчанию показана
        self._act_gate.triggered.connect(self._toggle_gate_dock)
        menu_view.addAction(self._act_gate)

    def apply_view_source(self, cid: Optional[str]):
        """Применить выбранный источник в это окно: камера/виджет в фокус слева."""
        if cid:
            self.canvas.set_focus(cid)   # канвас сам нарисует фокус + правую колонку
        else:
            self.canvas.set_focus(None)

    def _toggle_gate_dock(self, checked: bool) -> None:
        """Показ/скрытие окна шлагбаума из меню «Вид»."""
        dock = getattr(self, "gateDock", None)
        if dock is None:
            return
        if checked:
            dock.show()
        else:
            dock.hide()

    def _apply_views_to_canvas(self, *args):
        """
        Берём актуальный список выбранных источников и выбранную сетку для ТЕКУЩЕГО window_id.
        """
        try:
            vs = load_views()
            cur = next((v for v in vs if v.id == self.window_id), None)
            selected_ids = list(cur.selected_ids or []) if cur else []
            layout_key = (cur.layout if cur else "auto") or "auto"
        except Exception:
            selected_ids = []
            layout_key = "auto"
        try:
            self.canvas.set_allowed_ids(selected_ids)
            self.canvas.set_layout_key(layout_key)
        except Exception:
            pass

    # === Сигналы панели «Окна» ===
    def _on_view_selected(self, view_id: str):
        # ничего не делаем локально: смена активного окна — для многооконного менеджера
        pass

    def _on_view_renamed(self, view_id: str, new_name: str):
        # локальное окно не обязано реагировать
        pass

    def _on_view_source(self, view_id: str, selected_ids: list):
        w = self._wins.get(view_id)
        if not w:
            return
        # Раньше мы ставили фокус на selected_ids[0].
        # Уберём это: только обновляем список в канвасе, фокус пусть остаётся как был.
        w._apply_views_to_canvas()

    def _on_view_added(self, view_id: str):
        # менеджер окон создаст экземпляр. Здесь ничего.
        pass

    def _on_view_removed(self, view_id: str):
        # если удалили нас — закрываемся
        if view_id == self.window_id:
            self.close()

    def closeEvent(self, event):
        # сохраняем геометрию/state per-window
        try:
            self._settings.setValue(f"{self.window_id}/geometry", self.saveGeometry())
            self._settings.setValue(f"{self.window_id}/state", self.saveState())
        except Exception:
            pass
        return super().closeEvent(event)

    def eventFilter(self, obj, ev):
        if obj is self.sidebar and ev.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Move,
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Hide
        ):
            self._reposition_dock_handle()
        return super().eventFilter(obj, ev)

    def _reposition_dock_handle(self):
        if self.sidebar.is_open():
            g = self.sidebar.geometry()
            x = g.left() - self._dock_handle.width() + 1
            y = g.top() + (g.height() - self._dock_handle.height()) // 2
            self._dock_handle.move(max(0, x), max(0, y))
            self._dock_handle.setText("▶")  # открыта → предлагаем свернуть
            self._dock_handle.show()
        else:
            margin = 6
            x = max(0, self.width() - self._dock_handle.width() - margin)
            y = max(0, (self.height() - self._dock_handle.height()) // 2)
            self._dock_handle.move(x, y)
            self._dock_handle.setText("◀")  # закрыта → предлагаем открыть
            self._dock_handle.show()

    def resizeEvent(self, e: QtGui.QResizeEvent):
        super().resizeEvent(e)
        self._reposition_dock_handle()

    def toggle_controls(self):
        # Если вдруг окно в полноэкранном режиме — просто вернём в нормальный
        if self.windowState() & QtCore.Qt.WindowState.WindowFullScreen:
            self.showNormal()

        if self.sidebar.is_open():
            self.sidebar.animate_close(self)
        else:
            self.sidebar.animate_open(self)
        self._reposition_dock_handle()

    def _ensure_sidebar_visible(self):
        self.sidebar.ensure_visible()
        self._reposition_dock_handle()

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


class WindowManager(QtWidgets.QWidget):
    """
    Простой менеджер: держит ссылку на все MainWindow и следит за списком ViewSpec.
    """
    def __init__(self, ui_queue, stop_event_threads, stop_event_proc, grabbers, proc):
        super().__init__()
        self.ui_queue = ui_queue
        self.frame_bus = FrameBus(self.ui_queue, parent=self)

        # новый менеджер записей
        self.rec_mgr = RecordingManager()
        self.frame_bus.frameReady.connect(self.rec_mgr.on_frame)

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

        # записи: пробрасываем из окна в глобальный менеджер
        w.recordStartRequested.connect(self.rec_mgr.start_recording)
        w.recordStopRequested.connect(self.rec_mgr.stop_recording)

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

