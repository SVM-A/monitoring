# app/qt/widgets/gate_control.py
from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets


# Через сколько секунд ожидания без подтверждения/номера начинаем «орать».
# TODO: если понадобится – вынести в конфиг.
ALARM_WAIT_SECONDS: int = 10


class GateControlWidget(QtWidgets.QWidget):
    """
    Панель управления шлагбаумом и подтверждения номера.

    Разбита на 2 секции: «Въезд» и «Выезд».
    Сейчас реально используется только «Въезд», секция «Выезд» заранее
    подготовлена и по умолчанию выключена.

    Сигналы:
        plateConfirmed(direction, plate_text, source):
            - direction: "entry" или "exit"
            - plate_text: подтверждённый номер
            - source: "auto" (распознан) или "manual" (введён охранником)

        trainingSampleRequested(direction, plate_text):
            - запрос сохранить кадр + текст для дообучения (direction сейчас "entry")

        gateOpenRequested(direction, plate_text):
            - запрос открыть шлагбаум (заглушка).
            - plate_text может быть пустой строкой, если открыли «вручную без номера».

        alarmMutedChanged(is_muted):
            - включение/отключение звукового оповещения.
    """

    plateConfirmed = QtCore.pyqtSignal(str, str, str)  # direction, plate_text, source
    trainingSampleRequested = QtCore.pyqtSignal(str, str)  # direction, plate_text
    gateOpenRequested = QtCore.pyqtSignal(str, str)  # direction, plate_text_or_empty
    alarmMutedChanged = QtCore.pyqtSignal(bool)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._alarm_muted: bool = False
        self._entry_wait_elapsed: int = 0
        self._entry_alarm_fired: bool = False

        # Таймер, который отсчитывает время ожидания подтверждения/номера
        self._entry_wait_timer = QtCore.QTimer(self)
        self._entry_wait_timer.setInterval(1000)  # 1 секунда
        self._entry_wait_timer.timeout.connect(self._on_entry_wait_tick)

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # --- Секция "Въезд" ---
        self._entry_group = QtWidgets.QGroupBox("Въезд", self)
        entry_layout = QtWidgets.QVBoxLayout(self._entry_group)
        entry_layout.setSpacing(6)

        # Статус
        self._entry_status = QtWidgets.QLabel("Ожидание автомобиля", self._entry_group)
        self._entry_status.setWordWrap(True)
        entry_layout.addWidget(self._entry_status)

        # Текущий распознанный номер (только для чтения)
        plate_row = QtWidgets.QHBoxLayout()
        lbl_plate = QtWidgets.QLabel("Распознанный номер:", self._entry_group)
        self._entry_plate = QtWidgets.QLineEdit(self._entry_group)
        self._entry_plate.setReadOnly(True)
        self._entry_plate.setPlaceholderText("— пока нет распознанного номера —")
        plate_row.addWidget(lbl_plate)
        plate_row.addWidget(self._entry_plate)
        entry_layout.addLayout(plate_row)

        # Поле для ручного ввода номера
        manual_row = QtWidgets.QHBoxLayout()
        lbl_manual = QtWidgets.QLabel("Исправить номер:", self._entry_group)
        self._entry_manual = QtWidgets.QLineEdit(self._entry_group)
        self._entry_manual.setPlaceholderText("ввести номер вручную…")
        manual_row.addWidget(lbl_manual)
        manual_row.addWidget(self._entry_manual)
        entry_layout.addLayout(manual_row)

        # Кнопки действий
        btn_row1 = QtWidgets.QHBoxLayout()
        self._btn_entry_confirm = QtWidgets.QPushButton("Подтвердить номер", self._entry_group)
        self._btn_entry_manual_apply = QtWidgets.QPushButton(
            "Применить ввод и открыть", self._entry_group
        )
        btn_row1.addWidget(self._btn_entry_confirm)
        btn_row1.addWidget(self._btn_entry_manual_apply)
        entry_layout.addLayout(btn_row1)

        btn_row2 = QtWidgets.QHBoxLayout()
        self._btn_entry_open = QtWidgets.QPushButton("Открыть шлагбаум", self._entry_group)
        btn_row2.addWidget(self._btn_entry_open)
        entry_layout.addLayout(btn_row2)

        # Лог последних событий по въезду
        self._entry_log = QtWidgets.QPlainTextEdit(self._entry_group)
        self._entry_log.setReadOnly(True)
        self._entry_log.setMaximumBlockCount(200)
        self._entry_log.setPlaceholderText("Здесь будут появляться события: движение, "
                                           "попытки распознавания, подтверждения и т.д.")
        entry_layout.addWidget(self._entry_log)

        root.addWidget(self._entry_group)

        # --- Секция "Выезд" (пока заготовка) ---
        self._exit_group = QtWidgets.QGroupBox("Выезд (на будущее)", self)
        self._exit_group.setEnabled(False)
        exit_layout = QtWidgets.QVBoxLayout(self._exit_group)
        exit_hint = QtWidgets.QLabel(
            "Секция для камеры выезда.\n"
            "Сейчас работает только въезд, здесь просто задел под будущее.",
            self._exit_group,
        )
        exit_hint.setWordWrap(True)
        exit_layout.addWidget(exit_hint)
        root.addWidget(self._exit_group)

        # --- Общие настройки (звук) ---
        sound_row = QtWidgets.QHBoxLayout()
        self._chk_mute = QtWidgets.QCheckBox("Отключить звуковое оповещение", self)
        sound_row.addWidget(self._chk_mute)
        sound_row.addStretch(1)
        root.addLayout(sound_row)

        root.addStretch(1)

        # Подключаем слоты
        self._btn_entry_confirm.clicked.connect(self._on_entry_confirm_clicked)
        self._btn_entry_manual_apply.clicked.connect(self._on_entry_manual_apply_clicked)
        self._btn_entry_open.clicked.connect(self._on_entry_open_clicked)
        self._chk_mute.toggled.connect(self._on_mute_changed)

    # ------------------------------------------------------------------ Публичные методы для обновления состояния (вызывать из пайплайна/воркера позже)

    def set_entry_motion_state(self, has_motion: bool) -> None:
        """
        Обновить факт наличия движения в зоне въездной камеры.

        Ожидается вызов внешним кодом (воркер/пайплайн по motion-gate).
        """
        if has_motion:
            self._set_entry_status("Движение в зоне въезда — ищем номер…")
            self._append_entry_log("Движение обнаружено, ожидаем распознавание номера.")
        else:
            self._set_entry_status("Ожидание автомобиля")
            self._append_entry_log("Движение пропало, сбрасываем ожидание.")
            self._stop_entry_wait_timer()

    def set_entry_plate_candidate(self, plate_text: str) -> None:
        """
        Записать распознанный номер (кандидат) для въезда.

        Внешний код вызывает это, когда пайплайн вернул некоторый номер.
        """
        plate_text = (plate_text or "").strip()
        self._entry_plate.setText(plate_text)
        if plate_text:
            self._set_entry_status(f"Номер распознан: {plate_text}. Ожидаем подтверждения.")
            self._append_entry_log(f"Распознан номер: {plate_text}. Ждём действия охранника.")
            self._start_entry_wait_timer()
        else:
            self._set_entry_status("Не удалось распознать номер. Ожидаем действий.")
            self._append_entry_log("Распознавание номера не удалось.")
            self._start_entry_wait_timer()

    def reset_entry_state(self) -> None:
        """
        Сброс состояния по въезду (например, после полного завершения сценария
        «машина проехала»).
        """
        self._entry_plate.clear()
        self._entry_manual.clear()
        self._set_entry_status("Ожидание автомобиля")
        self._stop_entry_wait_timer()

    # ------------------------------------------------------------------ Внутренние слоты кнопок

    def _on_entry_confirm_clicked(self) -> None:
        """
        Охранник подтверждает распознанный номер.
        """
        plate = self._entry_plate.text().strip()
        if not plate:
            self._append_entry_log("Нечего подтверждать: распознанный номер пустой.")
            self._set_entry_status("Нет распознанного номера для подтверждения.")
            return

        self._append_entry_log(f"Подтверждён номер (auto): {plate}. Открываем шлагбаум.")
        self._set_entry_status(f"Номер {plate} подтверждён. Открываем шлагбаум.")
        self._stop_entry_wait_timer()

        # уведомляем мир
        self.plateConfirmed.emit("entry", plate, "auto")
        self.gateOpenRequested.emit("entry", plate)

    def _on_entry_manual_apply_clicked(self) -> None:
        """
        Охранник вводит номер вручную, мы:
        - сохраняем этот номер как трениговый пример;
        - сразу открываем шлагбаум.
        """
        manual_plate = self._entry_manual.text().strip()
        if not manual_plate:
            self._append_entry_log("Ввод номера пустой — ничего не делаем.")
            self._set_entry_status("Введите номер вручную, если распознавание ошиблось.")
            return

        self._append_entry_log(
            f"Ручной ввод номера: {manual_plate}. Сохраняем в датасет и открываем шлагбаум."
        )
        self._set_entry_status(
            f"Ручной номер {manual_plate} принят. Открываем шлагбаум."
        )
        self._stop_entry_wait_timer()

        # уведомляем мир
        self.trainingSampleRequested.emit("entry", manual_plate)
        self.plateConfirmed.emit("entry", manual_plate, "manual")
        self.gateOpenRequested.emit("entry", manual_plate)

    def _on_entry_open_clicked(self) -> None:
        """
        Принудительное (ручное) открытие шлагбаума без привязки к номеру.
        """
        self._append_entry_log("Ручное открытие шлагбаума (без номера).")
        self._set_entry_status("Ручное открытие шлагбаума.")
        self._stop_entry_wait_timer()

        # В plate_text отправляем пустую строку
        self.gateOpenRequested.emit("entry", "")

    def _on_mute_changed(self, muted: bool) -> None:
        self._alarm_muted = muted
        self.alarmMutedChanged.emit(muted)
        if muted and self._entry_alarm_fired:
            # если выключили звук — считаем, что тревогу сбросили
            self._entry_alarm_fired = False
        self._append_entry_log(
            "Звуковое оповещение отключено." if muted else "Звуковое оповещение включено."
        )

    # ------------------------------------------------------------------ Логика ожидания и «сирены»

    def _start_entry_wait_timer(self) -> None:
        """
        Запуск отсчёта времени ожидания подтверждения/номера.
        """
        self._entry_wait_elapsed = 0
        self._entry_alarm_fired = False
        if not self._entry_wait_timer.isActive():
            self._entry_wait_timer.start()

    def _stop_entry_wait_timer(self) -> None:
        if self._entry_wait_timer.isActive():
            self._entry_wait_timer.stop()
        self._entry_wait_elapsed = 0
        self._entry_alarm_fired = False

    def _on_entry_wait_tick(self) -> None:
        """
        Раз в секунду проверяем, не пора ли поднять тревогу:
        - номер так и не подтверждён;
        - охранник ничего не сделал;
        - машина, по сути, «зависла» под шлагбаумом.
        """
        self._entry_wait_elapsed += 1

        # Можно в будущем показывать это в статусе/лайбле.
        # Сейчас — просто аккуратный лог раз в несколько секунд.
        if self._entry_wait_elapsed % 5 == 0:
            self._append_entry_log(
                f"Ожидание действия охранника: {self._entry_wait_elapsed} с."
            )

        if (
            not self._entry_alarm_fired
            and self._entry_wait_elapsed >= ALARM_WAIT_SECONDS
        ):
            self._entry_alarm_fired = True
            self._on_entry_alarm_timeout()

    def _on_entry_alarm_timeout(self) -> None:
        """
        Срабатывает, когда машина «зависла» дольше ALARM_WAIT_SECONDS.
        Здесь только логика уровня UI, звук – в отдельном слое.
        """
        self._set_entry_status(
            "ВНИМАНИЕ: нет подтверждения номера более "
            f"{ALARM_WAIT_SECONDS} секунд."
        )
        self._append_entry_log(
            f"⚠ Нет подтверждения номера/действия охранника более {ALARM_WAIT_SECONDS} с."
        )
        if not self._alarm_muted:
            self._play_alarm_sound_stub()

    def _play_alarm_sound_stub(self) -> None:
        """
        Заглушка под звуковое оповещение.

        TODO:
            - подключить QtMultimedia.QSoundEffect / QMediaPlayer;
            - хранить короткий WAV/OGG рядом с приложением;
            - здесь запускать/останавливать звук.
        """
        # Сейчас не делаем реальный звук, только лог.
        self._append_entry_log("Звуковое оповещение (заглушка): сигнал тревоги.")

    # ------------------------------------------------------------------ Вспомогательные методы

    def _set_entry_status(self, text: str) -> None:
        self._entry_status.setText(text)

    def _append_entry_log(self, text: str) -> None:
        self._entry_log.appendPlainText(text)
        # авто-прокрутка вниз
        cursor = self._entry_log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._entry_log.setTextCursor(cursor)


class GateControlDock(QtWidgets.QDockWidget):
    """
    Отдельное окно (док) для панели управления шлагбаумом.

    - Можно пристыковать справа/слева.
    - Есть свой крестик «закрыть».
    - Показывается/скрывается через меню «Вид».
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__("Шлагбаум", parent)
        self.setObjectName("GateControlDock")

        # Разрешаем только правую/левую стороны, чтобы не уезжало вниз
        self.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea
            | QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        self._widget = GateControlWidget(self)
        self.setWidget(self._widget)

    def gate_widget(self) -> GateControlWidget:
        """Удобный доступ к самому виджету (с сигналами и логикой)."""
        return self._widget
