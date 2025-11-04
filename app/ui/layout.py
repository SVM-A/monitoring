# app/ui/layout.py

from typing import Optional, Dict, Tuple, List

import cv2
import numpy as np


def _blit_clip(canvas: np.ndarray, tile: np.ndarray, x0: int, y0: int) -> tuple[int,int,int,int] | None:
    """
    Кладёт tile на canvas по координатам (x0,y0) с отсечением по границам.
    Возвращает фактический прямоугольник (x0,y0,x1,y1) на canvas или None, если совсем вне экрана.
    """
    H, W = canvas.shape[:2]
    th, tw = tile.shape[:2]

    # целевой прямоугольник на холсте
    dst_x0, dst_y0 = x0, y0
    dst_x1, dst_y1 = x0 + tw, y0 + th

    # полностью вне?
    if dst_x1 <= 0 or dst_y1 <= 0 or dst_x0 >= W or dst_y0 >= H:
        return None

    # видимые границы на холсте
    vis_x0 = max(0, dst_x0); vis_y0 = max(0, dst_y0)
    vis_x1 = min(W, dst_x1); vis_y1 = min(H, dst_y1)

    # соответствующие срезы на источнике
    src_x0 = vis_x0 - dst_x0; src_y0 = vis_y0 - dst_y0
    src_x1 = src_x0 + (vis_x1 - vis_x0); src_y1 = src_y0 + (vis_y1 - vis_y0)

    # если после клиппинга что-то осталось — вставляем
    if vis_x0 < vis_x1 and vis_y0 < vis_y1:
        canvas[vis_y0:vis_y1, vis_x0:vis_x1] = tile[src_y0:src_y1, src_x0:src_x1]
        return (vis_x0, vis_y0, vis_x1, vis_y1)
    return None


def pick_grid(n: int) -> tuple[int, int]:
    """Подбираем сетку: 1,2 -> 1x2; 3-4 -> 2x2; 5-9 -> 3x3; 10-16 -> 4x4."""
    if n <= 1: return 1, 1
    if n <= 2: return 1, 2
    if n <= 4: return 2, 2
    if n <= 9: return 3, 3
    return 4, 4

def fit_into_box(frame: np.ndarray, box_w: int, box_h: int) -> np.ndarray:
    """Масштабирует кадр с сохранением пропорций, дополняя полями (чёрными) до box_w x box_h."""
    if frame is None or frame.size == 0:
        return np.zeros((box_h, box_w, 3), dtype=np.uint8)
    h, w = frame.shape[:2]
    scale = min(box_w / w, box_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((box_h, box_w, 3), dtype=np.uint8)
    x0 = (box_w - new_w) // 2
    y0 = (box_h - new_h) // 2
    canvas[y0:y0+new_h, x0:x0+new_w] = resized
    return canvas


def compose_grid(
    frames: Dict[str, Optional[np.ndarray]],
    out_size: Tuple[int, int] = (1920, 1080)
) -> np.ndarray:
    """Собирает сетку из frames по алфавиту ключей (camera_id) в 16:9 холст."""
    out_w, out_h = out_size
    ids = sorted(frames.keys())
    n = len(ids)
    rows, cols = pick_grid(n)
    cell_w, cell_h = out_w // cols, out_h // rows

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

    # если кадров меньше, чем ячеек — оставшиеся остаются чёрными
    return canvas

def compose_focus_layout(
    frames: Dict[str, Optional[np.ndarray]],
    focus_id: str | None,
    widget_ids: List[str],
    out_size: Tuple[int, int] = (1920, 1080),
    widget_size: Tuple[int, int] = (640, 360),
    scroll_offset: int = 0,
) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]], int]:
    """
    Возвращает (canvas, rects), где rects[cam_id] = (x0,y0,x1,y1) — для хит-тестов мыши.
    Если focus_id задан, показываем крупно эту камеру слева, а справа — колонка миниатюр и виджета.
    Если фокуса нет — рисуем обычную сетку.
    Виджеты всегда рисуются в фиксированном размере widget_size.
    """
    out_w, out_h = out_size
    rects: dict[str, tuple[int,int,int,int]] = {}

    # если нет фокуса — используем стандартную сетку
    if not focus_id:
        grid = compose_grid(frames, out_size=out_size)
        # Проставим прямоугольники ячеек для кликов по текущей сетке
        ids = sorted(frames.keys())
        rows, cols = pick_grid(len(ids))
        cell_w, cell_h = out_w // cols, out_h // rows
        for idx, cam_id in enumerate(ids):
            r, c = divmod(idx, cols)
            x0, y0 = c * cell_w, r * cell_h
            rects[cam_id] = (x0, y0, x0 + cell_w, y0 + cell_h)
        return grid, rects, out_h

    # с фокусом
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # левая часть под фокус: ~ 2/3 ширины
    left_w = (out_w * 2) // 3
    left_h = out_h
    left = fit_into_box(frames.get(focus_id), left_w, left_h)
    canvas[:, :left_w] = left
    rects[focus_id] = (0, 0, left_w, out_h)

    # правая колонка
    right_x = left_w
    right_w = out_w - left_w
    pad = 12
    top_pad = 16
    bottom_pad = 24

    thumb_w = right_w - pad * 2
    thumb_h = max(120, int(thumb_w * 9 / 16))  # 16:9

    # ВАЖНО:
    # - 'cur_y' накапливает ЛОГИЧЕСКУЮ высоту контента (без скролла)
    # - 'scroll' используем только при фактической отрисовке (y0 = cur_y - scroll)
    scroll = max(0, int(scroll_offset))
    cur_y = top_pad  # логическая верхняя граница контента

    # 1) виджеты фиксированным размером, НО без дублирования фокуса
    for wid in widget_ids:
        if wid == focus_id:
            continue
        frame = frames.get(wid)
        w_h = thumb_h
        w = fit_into_box(frame, thumb_w, w_h)

        y0, x0 = cur_y - scroll, right_x + pad
        y1, x1 = y0 + w_h, x0 + thumb_w
        # клиппинг внутри _blit_clip; чуть расширяем условие видимости
        if y1 >= -thumb_h and y0 <= out_h + thumb_h:
            placed = _blit_clip(canvas, w, x0, y0)
            if placed:
                rects[wid] = placed

        cur_y += w_h + pad  # логический приращение высоты контента

    # 2) миниатюры камер (кроме фокуса и виджетов), все одинаковой высоты thumb_h
    other_cam_ids = sorted([cid for cid in frames.keys() if cid != focus_id and cid not in widget_ids])
    for cam_id in other_cam_ids:
        frame = frames.get(cam_id)
        thumb = fit_into_box(frame, thumb_w, thumb_h)

        y0, x0 = cur_y - scroll, right_x + pad
        y1, x1 = y0 + thumb_h, x0 + thumb_w
        if y1 >= -thumb_h and y0 <= out_h + thumb_h:
            placed = _blit_clip(canvas, thumb, x0, y0)
            if placed:
                rects[cam_id] = placed

        cur_y += thumb_h + pad

    # Итоговая логическая высота контента (без скролла)
    content_end = cur_y + bottom_pad
    total_height = max(content_end, out_h)

    return canvas, rects, total_height

def compose_two_panel(
    left_frame: Optional[np.ndarray],
    right_frame: Optional[np.ndarray],
    out_size: Tuple[int, int] = (1280, 720),
    left_label: str = "cam_1",
    right_label: str = "cam_2",
) -> np.ndarray:
    """Собирает общее окно 16:9, пополам: левая/правая половины."""
    out_w, out_h = out_size
    # каждая половина — out_w//2 x out_h (соотношение 8:9)
    half_w = out_w // 2
    left = fit_into_box(left_frame, half_w, out_h)
    right = fit_into_box(right_frame, half_w, out_h)

    # подписи/плашки
    def annotate(img, text: str, ok: bool):
        if not ok:
            # NO SIGNAL
            cv2.putText(img, "NO SIGNAL", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)
        cv2.putText(img, text, (20, out_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)

    left_ok = left_frame is not None
    right_ok = right_frame is not None
    annotate(left, left_label, left_ok)
    annotate(right, right_label, right_ok)

    return np.hstack([left, right])
