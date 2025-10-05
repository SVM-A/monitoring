# app/video/roi.py

import cv2
import numpy as np


def apply_roi(frame, roi_conf):
    """Возвращает кадр после применения ROI (crop или mask)"""
    if not roi_conf:
        return frame
    t = roi_conf.get("type")
    if t == "rect":
        x, y, w, h = roi_conf.get("rect", [0,0,frame.shape[1], frame.shape[0]])
        return frame[y:y+h, x:x+w]
    elif t == "poly":
        poly = np.array(roi_conf.get("poly", [[0,0],[frame.shape[1],0],[frame.shape[1],frame.shape[0]],[0,frame.shape[0]]]))
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [poly], 255)
        masked = cv2.bitwise_and(frame, frame, mask=mask)
        return masked
    else:
        return frame
