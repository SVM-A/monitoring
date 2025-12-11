# app/ui/designs.py
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from io import BytesIO
import cairosvg
import os
from typing import Optional
from PIL import ImageFont, ImageDraw, Image
from PyQt6 import QtCore

from app.core.config_cams import COLOR_TEXT


# --design_system--

@dataclass(frozen=True)
class Typography:
    # Базовые кегли — меняешь тут и они применяются везде
    xs: int = 12
    sm: int = 14
    md: int = 16
    lg: int = 18
    xl: int = 22
    xxl: int = 28
    h: int = 32  # заголовки

@dataclass(frozen=True)
class Radii:
    sm: int = 6
    md: int = 10
    lg: int = 14

@dataclass(frozen=True)
class Spacing:
    xxs: int = 4
    xs: int = 6
    sm: int = 8
    md: int = 12
    lg: int = 16

@dataclass(frozen=True)
class Palette:
    # Контрасты — взяты из твоих констант, но собраны в одном месте
    alert=(255,170,60)
    ok=(140,210,120)

    clock_normal=(28,28,34)
    clock_weekend=(34,34,48)
    clock_holiday=(60,22,28)

    bg=(18,22,28)
    grid=(55,60,70)
    text=(230,235,242)
    sub=(170,175,185)
    temp=(240,205,150)
    cell=(32,36,44)
    weekend=(38,42,52)
    holiday=(58,31,38)
    today=(32,54,84)

    badge_bg=(48,52,62)
    badge_text=(220,220,230)
    badge_rain=(120,160,220)
    badge_rain_high=(90,150,230)
    badge_wind=(230,160,160)

    panel=(26,30,38)


@dataclass(frozen=True)
class CalendarStyle:
    day_stroke=(0, 0, 0)          # обводка для числа дня
    day_stroke_width:int = 2
    weather_icon:int = 26         # размер иконки внизу ячейки
    weather_gap:int = 10           # зазор между “чипами” погоды
    weather_font:int = 20         # кегль цифр в чипах
    month_label_case:str = "full"  # "short" -> «янв», "full" -> «Январь»

@dataclass(frozen=True)
class DS:
    typo: Typography = Typography()
    radii: Radii = Radii()
    gap: Spacing = Spacing()
    color: Palette = Palette()
    calendar: CalendarStyle = CalendarStyle()
    assets_root: Path = Path(__file__).resolve().parent / "icons"

DS = DS()


# --icons--

# Базовое соответствие ключ -> файл (в папке app/ui/icons)
_ICON_MAP = {
    "rain": "rain.svg",
    "rain-heavy": "heavy-rain.svg",
    "light-rain": "light-rain.svg",
    "cloud-sleet": "cloud-sleet.svg",
    "rain-snow": "rain-snow.svg",
    "rain-thunder": "rain-thunder.svg",
    "drizzle": "drizzle.svg",
    "hail": "hail.svg",
    "snow": "snow.svg",
    "cloudy": "cloudy.svg",
    "day-sunny": "day-sunny.svg",
    "mostly-cloudy": "mostly-cloudy.svg",
    "night": "night.svg",
    "overcast": "overcast.svg",
    "partly-cloudy": "partly-cloudy.svg",
    "storm": "storm.svg",
    "strong-wind-2": "strong-wind-2.svg",
    "windy": "windy.svg",
    "sunny-day": "sunny-day.svg",
    "sunrise": "sunrise.svg",
    "sunset": "sunset.svg",
    "temperature-low": "temperature-low.svg",
    "temperature-snow": "temperature-snow.svg",
    "temperature-sun": "temperature-sun.svg",
    "sky-night": "sky-night.svg",
    "sky-sun": "sky-sun.svg",
}

# Алиасы: привычные короткие имена -> реальные ключи из _ICON_MAP
_ALIASES = {
    # прежнее
    "rain_heavy": "rain-heavy",
    "heavy_rain": "rain-heavy",
    "light_rain": "light-rain",
    "wind": "windy",
    "strong_wind": "strong-wind-2",
    "dry": "cloudy",
    "sun": "day-sunny",
    "sky_night": "sky-night",
    "sky_sun": "sky-sun",

    # осадки / состояния
    "snow": "snow",
    "sleet": "cloud-sleet",
    "rain_snow": "rain-snow",
    "thunder": "rain-thunder",
    "rain_thunder": "rain-thunder",
    "drizzle": "drizzle",
    "hail": "hail",

    # облачность/небо
    "cloudy": "cloudy",
    "overcast": "overcast",
    "partly_cloudy": "partly-cloudy",
    "mostly_cloudy": "mostly-cloudy",
    "storm": "storm",
    "sunny": "day-sunny",
}

def _resolve_icon_key(name: str) -> Optional[str]:
    if not name:
        return None
    n = name.strip().lower()
    k = _ALIASES.get(n, n)
    return k if k in _ICON_MAP else None

def _render_svg_to_rgba(svg_path: str, size: int) -> Image.Image:
    png_bytes = cairosvg.svg2png(
        url=svg_path,
        output_width=size,
        output_height=size,
        background_color='transparent'  # <<< ключевая строка
    )
    im = Image.open(BytesIO(png_bytes)).convert('RGBA')
    return im

@lru_cache()
def get_icon(name: str, size: int = 18) -> Optional[Image.Image]:
    key = _resolve_icon_key(name)
    if not key:
        return None
    path: Path = DS.assets_root / _ICON_MAP[key]
    if not path.exists():
        return None
    try:
        if path.suffix.lower() == ".svg":
            im = _render_svg_to_rgba(str(path), size=size)
        else:
            im = Image.open(path).convert("RGBA")
            if im.size != (size, size):
                im = im.resize((size, size), Image.Resampling.LANCZOS)
        return im
    except Exception:
        return None


# --text--


def _font_path_candidates():
    return [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]

def load_font(size: int) -> ImageFont.FreeTypeFont:
    for p in _font_path_candidates():
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

# ===== Фикс масштаба =====
# Можно задать через окружение: export FONT_SCALE=1.35
def _get_font_scale() -> float:
    raw = os.environ.get("FONT_SCALE", "1.1")  # по умолчанию делаем «крупнее»
    try:
        val = float(raw)
    except ValueError:
        val = 1.0
    # защитимся от нулей/минусов/слишком больших значений
    return max(0.5, min(val, 3.0))

FONT_SCALE = _get_font_scale()

def _scaled(px: int) -> int:
    return max(6, int(round(px * FONT_SCALE)))

# Готовые размеры (масштабируются одной ручкой)
FONT12 = load_font(DS.typo.xs)
FONT14 = load_font(DS.typo.sm)
FONT16 = load_font(DS.typo.md)
FONT18 = load_font(DS.typo.lg)
FONT20 = load_font(20)
FONT22 = load_font(DS.typo.xl)
FONT24 = load_font(24)
FONT28 = load_font(DS.typo.xxl)
FONT32 = load_font(DS.typo.h)
FONT36 = load_font(36)
FONT40 = load_font(40)
FONT48 = load_font(48)

def draw_wrapped_text(draw: ImageDraw.ImageDraw, xy, text: str, max_width: int, line_height: int, font) -> int:
    x, y = xy
    for paragraph in text.split("\n"):
        if not paragraph:
            y += line_height
            continue
        words, line = paragraph.split(" "), ""
        for w in words:
            test = (line + " " + w).strip()
            if draw.textlength(test, font=font) <= max_width:
                line = test
            else:
                draw.text((x, y), line, fill=COLOR_TEXT, font=font)
                y += line_height
                line = w
        if line:
            draw.text((x, y), line, fill=COLOR_TEXT, font=font)
            y += line_height
    return y


# --theme--


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
