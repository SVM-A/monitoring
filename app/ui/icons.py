# app/ui/icons.py
from __future__ import annotations

from functools import lru_cache
from typing import Optional
from pathlib import Path
from io import BytesIO
import cairosvg

from PIL import Image
from .design_system import DS


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
    "rain_heavy": "rain-heavy",
    "heavy_rain": "rain-heavy",
    "wind": "windy",
    "dry": "cloudy",
    "sun": "day-sunny",
    "sky_night": "sky-night",
    "sky_sun": "sky-sun",
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
            if cairosvg is None:
                return None
            png = cairosvg.svg2png(url=str(path), output_width=size, output_height=size)
            im = Image.open(BytesIO(png)).convert("RGBA")
        else:
            im = Image.open(path).convert("RGBA")
            if im.size != (size, size):
                im = im.resize((size, size), Image.Resampling.LANCZOS)
        return im
    except Exception:
        return None
