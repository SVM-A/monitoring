# =============================== app/monitoring/utils/regexes.py ===============================
from __future__ import annotations
import re
from typing import Optional, Tuple

# Обновлённые шаблоны: регион 2–3 цифры, кириллица AВЕКМНОРСТУХ
PLATE_PATTERNS = dict(
    civil=r"^[АВЕКМНОРСТУХ]{1}\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$",
    taxi=r"^[АВЕКМНОРСТУХ]{1}\d{3}ТХ\d{2,3}$",
    transport=r"^[АВЕКМНОРСТУХ]{1}\d{3}[ГТБ]{1}\d{2,3}$",
    motorcycle=r"^[АВЕКМНОРСТУХ]{1}\d{3}Х\d{2,3}$",
    military=r"^М\d{4}[АВЕКМНОРСТУХ]{2}$",
    diplomatic=r"^\d{3,4} [АВЕКМНОРСТУХ]{2}$",
    transit=r"^Т\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$",
    foreign=r"^[A-Z]{2}\d{4}[A-Z]{2}$",
)

# Нормализация: латинские в похожие кириллические (A->А, B->В, E->Е, K->К, M->М, H->Н, O->О, P->Р, C->С, T->Т, X->Х)
LAT_TO_CYR = str.maketrans({
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О", "P": "Р", "C": "С", "T": "Т", "X": "Х",
})


def normalize_plate(s: str) -> str:
    s = s.upper().replace(" ", "")
    return s.translate(LAT_TO_CYR)


def classify_plate(text: str) -> Optional[Tuple[str, str]]:
    t = normalize_plate(text)
    for k, patt in PLATE_PATTERNS.items():
        if re.match(patt, t):
            return k, t
    return None
