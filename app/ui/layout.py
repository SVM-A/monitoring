# app/ui/layout.py

from typing import Optional, Dict, Tuple, List

import cv2
import numpy as np


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
) -> tuple[np.ndarray, dict[str, tuple[int,int,int,int]]]:
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
        return grid, rects

    # с фокусом
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    # левая часть под фокус: ~ 2/3 ширины
    left_w = (out_w * 2) // 3
    left_h = out_h
    left = fit_into_box(frames.get(focus_id), left_w, left_h)
    canvas[:, :left_w] = left
    rects[focus_id] = (0, 0, left_w, out_h)

    # правая колонка: фиксированная полоса
    right_x = left_w
    right_w = out_w - left_w
    pad = 12
    thumb_h = 240  # высота миниатюр камер
    thumb_w = right_w - pad * 2

    # сначала — виджеты фиксированным размером
    cur_y = pad
    for wid in widget_ids:
        frame = frames.get(wid)
        w_w, w_h = widget_size
        w = fit_into_box(frame, thumb_w, w_h)
        canvas[cur_y:cur_y + w_h, right_x + pad: right_x + pad + thumb_w] = w
        rects[wid] = (right_x + pad, cur_y, right_x + pad + thumb_w, cur_y + w_h)
        cur_y += w_h + pad

    # затем — миниатюры остальных камер (кроме фокуса и виджетов)
    for cam_id, frame in frames.items():
        if cam_id == focus_id or cam_id in widget_ids:
            continue
        h = min(thumb_h, max(120, (out_h - cur_y) // 3))
        thumb = fit_into_box(frame, thumb_w, h)
        y0, x0 = cur_y, right_x + pad
        y1, x1 = y0 + h, x0 + thumb_w
        if y1 > out_h - pad:
            break
        canvas[y0:y1, x0:x1] = thumb
        rects[cam_id] = (x0, y0, x1, y1)
        cur_y += h + pad

    return canvas, rects


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
