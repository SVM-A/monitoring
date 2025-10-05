# app/ui/layout.py

from typing import Optional

from PIL import ImageDraw, ImageFont

from app.core.constants import COLOR_TEXT


def _find_font() -> Optional[ImageFont.FreeTypeFont]:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, 24)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

FONT24 = _find_font()
try:
    FONT32 = ImageFont.truetype(getattr(FONT24, "path", ""), 32) if hasattr(FONT24, "path") else FONT24
except Exception:
    FONT32 = FONT24


def draw_wrapped_text(draw: ImageDraw.ImageDraw, xy, text: str, max_width: int, line_height: int, font) -> int:
    """Рисует многострочный текст с переносами по ширине max_width. Возвращает нижнюю Y-координату."""
    x, y = xy
    for paragraph in text.split("\n"):
        if not paragraph:
            y += line_height
            continue
        words = paragraph.split(" ")
        line = ""
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
