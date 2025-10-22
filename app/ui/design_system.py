# app/ui/design_system.py
from dataclasses import dataclass
from pathlib import Path

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
