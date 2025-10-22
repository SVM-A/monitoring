# app/widgets/widgets.py

import time as _time
from typing import Optional

import numpy as np

from app.widgets.base import WidgetBase


class CalendarWidget(WidgetBase):
    """Только 2 календаря (текущий + следующий). Обновляется раз в 30 сек."""

    def run(self) -> None:
        def _render():
            return self.render_calendar_two_months()

        # Тихая частота: перерисовываем раз в 30 сек, чтобы часы в заголовке не мельтешили
        while not self.stop_event.is_set():
            self.push_frame(_render())
            for _ in range(30):
                if self.stop_event.is_set():
                    break
                _time.sleep(1)


class ClockWidget(WidgetBase):
    """Компактные цифровые часы."""

    def run(self) -> None:
        self.run_loop(lambda: self.render_digital_clock(), tick_seconds=1.0)


class HolidaysWidget(WidgetBase):
    """Блок «Праздники (14 дней)», кэш обновляется раз в 15 минут."""

    def run(self) -> None:
        last = 0.0
        cache_img: Optional[np.ndarray] = None
        while not self.stop_event.is_set():
            now = _time.time()
            if now - last > 900:  # 15 минут
                try:
                    cache_img = self.render_holidays_box()
                except Exception:
                    cache_img = self.render_holidays_box()  # фолбэк всё равно отрисует «нет праздников»
                last = now
            if cache_img is not None:
                self.push_frame(cache_img)
            _time.sleep(1)


class CalClockWidget(WidgetBase):
    """Комбинированная панель: 2 календаря + информер по флагам + аналоговые часы с цифровыми."""

    def run(self) -> None:
        self.run_loop(lambda: self.render_calendar_plus_clock(), tick_seconds=1.0)


class CaClockWeatherWidget(WidgetBase):
    """Комбинированная панель: 4 недели календаря (Пн-Вс) с погодой + часы + подробная погода на сегодня."""
    def run(self) -> None:
        self.run_loop(lambda: self.render_calendar_clock_weather_4w(W=1920, H=1080), tick_seconds=1.0)



