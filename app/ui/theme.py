# app/ui/theme.py — настройки HiDPI и загрузка QSS (PyQt6-safe)
from __future__ import annotations
from pathlib import Path
from PyQt6 import QtCore

def setup_hidpi():
    """
    Qt6: HiDPI включён по умолчанию. Делаем мягкие настройки без падений,
    если какие-то атрибуты в сборке отсутствуют.
    """
    # Включаем HiDPI-пиксмапы, если атрибут доступен в этой версии Qt
    try:
        attr = getattr(QtCore.Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps", None)
        if attr is not None:
            QtCore.QCoreApplication.setAttribute(attr)
    except Exception:
        pass

    # Политика округления масштаба — помогает избежать «мыла» на некоторых конфигурациях
    try:
        QtCore.QCoreApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        # метод может отсутствовать в более старых минорных версиях Qt6 — игнорируем
        pass


_QSS_CACHE = None

def load_qss() -> str:
    """Читает QSS-тему из styles.qss один раз и кэширует."""
    global _QSS_CACHE
    if _QSS_CACHE is not None:
        return _QSS_CACHE
    qss_path = Path(__file__).resolve().parent / "styles.qss"
    _QSS_CACHE = qss_path.read_text(encoding="utf-8") if qss_path.exists() else ""
    return _QSS_CACHE
