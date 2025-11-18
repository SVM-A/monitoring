# app/video/roi.py

import cv2
import numpy as np


def _apply_rect(frame, conf):
    x, y, w, h = conf.get("rect", [0, 0, frame.shape[1], frame.shape[0]])
    x = int(max(0, x))
    y = int(max(0, y))
    w = int(max(1, w))
    h = int(max(1, h))
    x2 = min(frame.shape[1], x + w)
    y2 = min(frame.shape[0], y + h)
    return frame[y:y2, x:x2]


def _apply_poly(frame, conf):
    poly = np.array(
        conf.get(
            "poly",
            [
                [0, 0],
                [frame.shape[1], 0],
                [frame.shape[1], frame.shape[0]],
                [0, frame.shape[0]],
            ],
        ),
        dtype=np.int32,
    )
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    masked = cv2.bitwise_and(frame, frame, mask=mask)
    return masked


def apply_roi(frame, roi_conf):
    """
    Возвращает кадр после применения ROI.

    Поддерживаем форматы:
      {
        "type": "rect",
        "rect": [x, y, w, h]
      }

      {
        "type": "poly",
        "poly": [[x1,y1], [x2,y2], ...]
      }

      {
        "type": "multi",
        "zones": [
          {"type": "rect", ...},
          {"type": "poly", ...},
          ...
        ]
      }

    Для multi: строим общую маску по всем зонам и оставляем только их.
    """
    if frame is None or frame.size == 0:
        return frame
    if not roi_conf:
        return frame

    t = roi_conf.get("type")

    # Обычные случаи
    if t == "rect":
        return _apply_rect(frame, roi_conf)
    if t == "poly":
        return _apply_poly(frame, roi_conf)

    # Несколько зон
    if t == "multi":
        zones = roi_conf.get("zones") or []
        if not zones:
            return frame

        mask = np.zeros(frame.shape[:2], dtype=np.uint8)

        for z in zones:
            z_type = z.get("type")
            if z_type == "rect":
                x, y, w, h = z.get("rect", [0, 0, frame.shape[1], frame.shape[0]])
                x = int(max(0, x))
                y = int(max(0, y))
                w = int(max(1, w))
                h = int(max(1, h))
                x2 = min(frame.shape[1], x + w)
                y2 = min(frame.shape[0], y + h)
                cv2.rectangle(mask, (x, y), (x2, y2), 255, thickness=-1)
            elif z_type == "poly":
                poly = np.array(z.get("poly", []), dtype=np.int32)
                if poly.size == 0:
                    continue
                cv2.fillPoly(mask, [poly], 255)

        masked = cv2.bitwise_and(frame, frame, mask=mask)
        return masked

    # На всякий случай – если тип неизвестен
    return frame
