# app/ui/text.py
import os
from typing import Optional
from PIL import ImageFont, ImageDraw
from app.core.constants import COLOR_TEXT
from app.ui.design_system import DS


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
