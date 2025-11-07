# app/ui/layout.py

from typing import Optional, Dict, Tuple, List

import cv2
import numpy as np


def _blit_clip(canvas: np.ndarray, tile: np.ndarray, x0: int, y0: int) -> tuple[int,int,int,int] | None:
    H, W = canvas.shape[:2]
    th, tw = tile.shape[:2]
    dst_x0, dst_y0 = x0, y0
    dst_x1, dst_y1 = x0 + tw, y0 + th
    if dst_x1 <= 0 or dst_y1 <= 0 or dst_x0 >= W or dst_y0 >= H:
        return None
    vis_x0 = max(0, dst_x0); vis_y0 = max(0, dst_y0)
    vis_x1 = min(W, dst_x1); vis_y1 = min(H, dst_y1)
    src_x0 = vis_x0 - dst_x0; src_y0 = vis_y0 - dst_y0
    src_x1 = src_x0 + (vis_x1 - vis_x0); src_y1 = src_y0 + (vis_y1 - vis_y0)
    if vis_x0 < vis_x1 and vis_y0 < vis_y1:
        canvas[vis_y0:vis_y1, vis_x0:vis_x1] = tile[src_y0:src_y1, src_x0:src_x1]
        return (vis_x0, vis_y0, vis_x1, vis_y1)
    return None


def pick_grid(n: int) -> tuple[int, int]:
    if n <= 1: return 1, 1
    if n <= 2: return 1, 2
    if n <= 4: return 2, 2
    if n <= 9: return 3, 3
    return 4, 4

def fit_into_box(frame: np.ndarray, box_w: int, box_h: int) -> np.ndarray:
    if frame is None or frame.size == 0:
        canvas = np.zeros((box_h, box_w, 3), dtype=np.uint8)
        # тонкая рамка по границе ячейки
        cv2.rectangle(canvas, (0, 0), (box_w - 1, box_h - 1), (70, 70, 78), 1)
        return canvas

    h, w = frame.shape[:2]
    scale = min(box_w / w, box_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.zeros((box_h, box_w, 3), dtype=np.uint8)
    x0 = (box_w - new_w) // 2
    y0 = (box_h - new_h) // 2
    canvas[y0:y0 + new_h, x0:x0 + new_w] = resized

    # тонкая рамка по границе ячейки
    cv2.rectangle(canvas, (0, 0), (box_w - 1, box_h - 1), (70, 70, 78), 1)
    return canvas


def compose_grid(
    frames: Dict[str, Optional[np.ndarray]],
    out_size: Tuple[int, int] = (1920, 1080)
) -> np.ndarray:
    """
    Собирает сетку из frames, УВАЖАЯ порядок ключей в frames (не сортируем).
    """
    out_w, out_h = out_size
    ids = list(frames.keys())
    n = len(ids)
    rows, cols = pick_grid(n)
    cell_w, cell_h = out_w // cols, out_h // rows
    max_slots = rows * cols
    ids = ids[:max_slots]

    canvas = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)

    def annotate(img, its_ok: bool):
        if not its_ok:
            cv2.putText(img, "NO SIGNAL", (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)

    for idx, cam_id in enumerate(ids):
        r, c = divmod(idx, cols)
        frame = frames.get(cam_id)
        fitted = fit_into_box(frame, cell_w, cell_h)
        ok = frame is not None
        annotate(fitted, ok)
        y0, y1 = r * cell_h, (r + 1) * cell_h
        x0, x1 = c * cell_w, (c + 1) * cell_w
        canvas[y0:y1, x0:x1] = fitted

    return canvas





def _apply_rects(frames: Dict[str, Optional[np.ndarray]],
                 rects: List[tuple[float,float,float,float]],
                 out_size: Tuple[int,int]) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]]]:
    out_w, out_h = out_size
    ids = list(frames.keys())
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    boxes: dict[str, tuple[int,int,int,int]] = {}
    slots = rects[:len(ids)]
    for cam_id, (x0n, y0n, x1n, y1n) in zip(ids, slots):
        x0 = int(x0n * out_w); y0 = int(y0n * out_h)
        x1 = int(x1n * out_w); y1 = int(y1n * out_h)
        w = max(1, x1 - x0); h = max(1, y1 - y0)
        fitted = fit_into_box(frames.get(cam_id), w, h)
        placed = _blit_clip(canvas, fitted, x0, y0)
        if placed:
            boxes[cam_id] = placed
    return canvas, boxes

def compose_named_layout(
    frames: Dict[str, Optional[np.ndarray]],
    layout_key: str,
    out_size: Tuple[int, int] = (1920, 1080),
) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]]]:
    """
    Рисует по именованному шаблону (layout_key). Если для данного N нет точного описания —
    автоматически откатывается к compose_grid.
    """
    if layout_key == "spotlight":
        n = len(frames)
        if 1 <= n <= 9:
            rects = _spotlight_rects(n)
            return _apply_rects(frames, rects, out_size)

    if layout_key == "spotlight-balanced":
        n = len(frames)
        if 1 <= n <= 9:
            rects = _spotlightL_balanced_rects(n)
            return _apply_rects(frames, rects, out_size)

    if layout_key == "dual-spotlight":
        n = len(frames)
        if 2 <= n <= 10:
            rects = _dual_spotlight_rects(n)
            return _apply_rects(frames, rects, out_size)

    n = len(frames)
    scheme = (LAYOUTS.get(layout_key) or {}).get(n)
    if not scheme:
        # fallback: просто сетка с сохранением порядка
        grid = compose_grid(frames, out_size=out_size)
        # расчёт прямоугольников для хит-теста
        out_w, out_h = out_size
        ids = list(frames.keys())
        rows, cols = pick_grid(len(ids))
        cell_w, cell_h = out_w // cols, out_h // rows
        rects: dict[str, tuple[int,int,int,int]] = {}
        for idx, cam_id in enumerate(ids):
            r, c = divmod(idx, cols)
            x0, y0 = c * cell_w, r * cell_h
            rects[cam_id] = (x0, y0, x0 + cell_w, y0 + cell_h)
        return grid, rects
    return _apply_rects(frames, scheme, out_size)


def compose_focus_layout(
    frames: Dict[str, Optional[np.ndarray]],
    focus_id: str | None,
    widget_ids: List[str],
    out_size: Tuple[int, int] = (1920, 1080),
    widget_size: Tuple[int, int] = (640, 360),
    scroll_offset: int = 0,
) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]], int]:
    out_w, out_h = out_size
    rects: dict[str, tuple[int,int,int,int]] = {}

    # без фокуса — дефолтная сетка по порядку
    if not focus_id:
        grid = compose_grid(frames, out_size=out_size)
        ids = list(frames.keys())  # <<< порядок
        rows, cols = pick_grid(len(ids))
        cell_w, cell_h = out_w // cols, out_h // rows
        for idx, cam_id in enumerate(ids):
            r, c = divmod(idx, cols)
            x0, y0 = c * cell_w, r * cell_h
            rects[cam_id] = (x0, y0, x0 + cell_w, y0 + cell_h)
        return grid, rects, out_h

    # с фокусом
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    left_w = (out_w * 2) // 3
    left_h = out_h
    left = fit_into_box(frames.get(focus_id), left_w, left_h)
    canvas[:, :left_w] = left
    rects[focus_id] = (0, 0, left_w, out_h)

    right_x = left_w
    right_w = out_w - left_w
    pad = 12
    top_pad = 16
    bottom_pad = 24

    thumb_w = right_w - pad * 2
    thumb_h = max(120, int(thumb_w * 9 / 16))  # 16:9

    scroll = max(0, int(scroll_offset))
    cur_y = top_pad

    # виджеты — по порядку, как даны во frames, без дублирования фокуса
    for cid in frames.keys():
        if cid == focus_id:
            continue
        if cid not in widget_ids:
            continue
        frame = frames.get(cid)
        w_h = thumb_h
        w = fit_into_box(frame, thumb_w, w_h)
        y0, x0 = cur_y - scroll, right_x + pad
        y1, x1 = y0 + w_h, x0 + thumb_w
        if y1 >= -thumb_h and y0 <= out_h + thumb_h:
            placed = _blit_clip(canvas, w, x0, y0)
            if placed:
                rects[cid] = placed
        cur_y += w_h + pad

    # камеры (не виджеты), тоже по порядку
    for cid in frames.keys():
        if cid == focus_id:
            continue
        if cid in widget_ids:
            continue
        frame = frames.get(cid)
        thumb = fit_into_box(frame, thumb_w, thumb_h)
        y0, x0 = cur_y - scroll, right_x + pad
        y1, x1 = y0 + thumb_h, x0 + thumb_w
        if y1 >= -thumb_h and y0 <= out_h + thumb_h:
            placed = _blit_clip(canvas, thumb, x0, y0)
            if placed:
                rects[cid] = placed
        cur_y += thumb_h + pad

    content_end = cur_y + bottom_pad
    total_height = max(content_end, out_h)
    return canvas, rects, total_height


def _grid_rects(cols: int, rows: int, count: int) -> list[tuple[float, float, float, float]]:
    """Нормированные прямоугольники для grid (слева-направо, сверху-вниз),
    возвращает первые count слотов."""
    rects = []
    cw = 1.0 / cols
    rh = 1.0 / rows
    total = min(count, cols * rows)
    for idx in range(total):
        r, c = divmod(idx, cols)
        x0, y0 = c * cw, r * rh
        x1, y1 = x0 + cw, y0 + rh
        rects.append((x0, y0, x1, y1))
    return rects


def _spotlight_rects(n: int) -> list[tuple[float, float, float, float]]:
    """
    1 крупная плитка, остальные — мелкие по правой колонке и внизу.
    Подходит для n=2..9 (1+8).
    Схема:
      - big: (0..2/3, 0..2/3)
      - right column: x in [2/3..1], делим по вертикали
      - bottom strip: y in [2/3..1], x in [0..2/3], делим по горизонтали
    """
    n = max(1, min(n, 9))
    rects = []
    # 1) большая
    rects.append((0.0, 0.0, 2/3, 2/3))
    if n == 1:
        return rects

    small = n - 1
    # правую колонку стараемся заполнять до 5 ячеек
    right_cnt = min(small, 5)
    bottom_cnt = small - right_cnt
    # правая колонка
    if right_cnt > 0:
        rh = 1.0 / right_cnt
        for i in range(right_cnt):
            y0, y1 = i * rh, (i + 1) * rh
            rects.append((2/3, y0, 1.0, y1))
    # нижняя полоса (до 3 ячеек)
    if bottom_cnt > 0:
        bottom_cnt = min(bottom_cnt, 3)
        cw = (2/3) / bottom_cnt
        for i in range(bottom_cnt):
            x0, x1 = i * cw, (i + 1) * cw
            rects.append((x0, 2/3, x1, 1.0))
    return rects

def _spotlightL_balanced_rects(n: int) -> list[tuple[float,float,float,float]]:
    """
    Улучшенный L-спотлайт: 1 крупная (2/3 × 2/3), мелкие равномерно делятся
    между правой колонкой и нижней полосой так, чтобы площадь мелких была максимальной.
    Рабочий диапазон: n = 1..9 (1 большая + до 8 мелких).
    """
    n = max(1, min(n, 9))
    rects: list[tuple[float,float,float,float]] = []
    # большая — слева-сверху
    rects.append((0.0, 0.0, 2/3, 2/3))
    if n == 1:
        return rects

    small = n - 1
    # оптимальный расклад: половину вправо, половину вниз, но не более 4 на каждую сторону
    # (4 — чтобы у нижних/правых слотов были разумные размеры)
    right_cnt = min((small + 1) // 2, 4)
    bottom_cnt = min(small - right_cnt, 4)
    # если «низ» пуст, но мелких >4 — докинем в низ
    if bottom_cnt == 0 and small > 4:
        move = min(small - 4, 4)
        right_cnt = 4
        bottom_cnt = move

    # правая колонка (x: 2/3..1)
    if right_cnt > 0:
        rh = 1.0 / right_cnt
        for i in range(right_cnt):
            y0, y1 = i * rh, (i + 1) * rh
            rects.append((2/3, y0, 1.0, y1))

    # нижняя полоса (y: 2/3..1; x: 0..2/3)
    if bottom_cnt > 0:
        cw = (2/3) / bottom_cnt
        for i in range(bottom_cnt):
            x0, x1 = i * cw, (i + 1) * cw
            rects.append((x0, 2/3, x1, 1.0))

    return rects


def _dual_spotlight_rects(n: int) -> list[tuple[float,float,float,float]]:
    """
    «Две большие + мелкие»: две крупные плитки сверху (левая/правая, по 1/2 ширины, 2/3 высоты),
    оставшиеся мелкие — внизу в одну строку. Диапазон: n = 2..10.
    """
    n = max(2, min(n, 10))
    rects: list[tuple[float,float,float,float]] = []
    # две большие сверху
    rects.append((0.0,   0.0, 0.5, 2/3))  # big-left
    rects.append((0.5,   0.0, 1.0, 2/3))  # big-right
    small = n - 2
    if small <= 0:
        return rects

    # нижняя полоса на всю ширину (y: 2/3..1)
    cols = small
    cw = 1.0 / cols
    for i in range(cols):
        x0, x1 = i * cw, (i + 1) * cw
        rects.append((x0, 2/3, x1, 1.0))
    return rects


# ====== Реестр готовых разметок ======
# Шаблоны описываются нормированными прямоугольниками (x0,y0,x1,y1) в долях (0..1)
# Кол-во прямоугольников — это число слотов. Берём кадры в порядке frames и раскладываем в слоты слева-направо.
LAYOUTS: dict[str, dict[int, list[tuple[float,float,float,float]]]] = {
    "2x2": {
        1: [(0,0,1,1)],
        2: [(0,0,0.5,1), (0.5,0,1,1)],
        3: [(0,0,0.5,0.5),(0.5,0,1,0.5),(0,0.5,0.5,1)],
        4: [(0,0,0.5,0.5),(0.5,0,1,0.5),(0,0.5,0.5,1),(0.5,0.5,1,1)],
    },
    "2x3": {  # до 6 источников
        1: _grid_rects(3, 2, 1),
        2: _grid_rects(3, 2, 2),
        3: _grid_rects(3, 2, 3),
        4: _grid_rects(3, 2, 4),
        5: _grid_rects(3, 2, 5),
        6: _grid_rects(3, 2, 6),
    },
    "2x4": {  # до 8 источников
        1: _grid_rects(4, 2, 1),
        2: _grid_rects(4, 2, 2),
        3: _grid_rects(4, 2, 3),
        4: _grid_rects(4, 2, 4),
        5: _grid_rects(4, 2, 5),
        6: _grid_rects(4, 2, 6),
        7: _grid_rects(4, 2, 7),
        8: _grid_rects(4, 2, 8),
    },
    "3x3": {  # 1–9
        1: _grid_rects(3, 3, 1),
        2: _grid_rects(3, 3, 2),
        3: _grid_rects(3, 3, 3),
        4: _grid_rects(3, 3, 4),
        5: _grid_rects(3, 3, 5),
        6: _grid_rects(3, 3, 6),
        7: _grid_rects(3, 3, 7),
        8: _grid_rects(3, 3, 8),
        9: _grid_rects(3, 3, 9),
    },
    "4x4": {  # 1–16
        1:  _grid_rects(4, 4, 1),
        2:  _grid_rects(4, 4, 2),
        3:  _grid_rects(4, 4, 3),
        4:  _grid_rects(4, 4, 4),
        5:  _grid_rects(4, 4, 5),
        6:  _grid_rects(4, 4, 6),
        7:  _grid_rects(4, 4, 7),
        8:  _grid_rects(4, 4, 8),
        9:  _grid_rects(4, 4, 9),
        10: _grid_rects(4, 4, 10),
        11: _grid_rects(4, 4, 11),
        12: _grid_rects(4, 4, 12),
        13: _grid_rects(4, 4, 13),
        14: _grid_rects(4, 4, 14),
        15: _grid_rects(4, 4, 15),
        16: _grid_rects(4, 4, 16),
    },
    # спец: слева — большой, справа/снизу — мелкие (2..9)
    "spotlight": {
        1: _spotlight_rects(1),
        2: _spotlight_rects(2),
        3: _spotlight_rects(3),
        4: _spotlight_rects(4),
        5: _spotlight_rects(5),
        6: _spotlight_rects(6),  # классическое «1+5»
        7: _spotlight_rects(7),
        8: _spotlight_rects(8),  # «1+7»
        9: _spotlight_rects(9),  # «1+8»
    },
    "spotlight-balanced": {
        1: _spotlightL_balanced_rects(1),
        2: _spotlightL_balanced_rects(2),
        3: _spotlightL_balanced_rects(3),
        4: _spotlightL_balanced_rects(4),
        5: _spotlightL_balanced_rects(5),
        6: _spotlightL_balanced_rects(6),
        7: _spotlightL_balanced_rects(7),
        8: _spotlightL_balanced_rects(8),
        9: _spotlightL_balanced_rects(9),
    },
    "dual-spotlight": {
        2: _dual_spotlight_rects(2),
        3: _dual_spotlight_rects(3),
        4: _dual_spotlight_rects(4),
        5: _dual_spotlight_rects(5),
        6: _dual_spotlight_rects(6),
        7: _dual_spotlight_rects(7),
        8: _dual_spotlight_rects(8),
        9: _dual_spotlight_rects(9),
        10: _dual_spotlight_rects(10),
    },
    # ранее добавленный кастом
    "1L-2S-bottom-1R": {
        1: [(0,0,2/3,1)],
        2: [(0,0,2/3,1),(2/3,0,1,1)],
        3: [(0,0,2/3,2/3),(0,2/3,1/3,1),(1/3,2/3,2/3,1)],
        4: [(0,0,2/3,2/3),(0,2/3,1/3,1),(1/3,2/3,2/3,1),(2/3,0,1,1)],
    },
}
