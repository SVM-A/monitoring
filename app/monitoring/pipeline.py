# =============================== app/monitoring/pipeline.py ===============================
from __future__ import annotations
from multiprocessing import Queue
from dataclasses import dataclass
from typing import Optional
import cv2
import numpy as np
import yaml

from app.monitoring.capture.rtsp_capture import RTSPCaptureProcess, FramePacket
from app.monitoring.detection.plate_detector import PlateDetector
from app.monitoring.recognition.ocr_recognizer import OCRWorker, OCRTask
from app.monitoring.display.publisher import DisplayPublisher
from app.monitoring.roi.masks import MaskStore, apply_mask
from app.monitoring.utils.regexes import classify_plate
from app.monitoring.config_runtime import RuntimeOptions

@dataclass
class CameraConfig:
    name: str
    rtsp_url: str
    mask_name: str
    show_window: bool = False

class LPRPipeline:
    def __init__(self, cam: CameraConfig, masks: MaskStore, rt: RuntimeOptions, detector_model: Optional[str] = None):
        self.cam = cam
        self.masks = masks
        self.rt = rt
        self.detector = PlateDetector(rt, model_path_onnx=detector_model)
        # Очереди
        self.q_frames = Queue(maxsize=rt.capture_queue_size)
        self.q_ocr_in = Queue(maxsize=rt.detect_queue_size)
        self.q_ocr_out = Queue(maxsize=rt.detect_queue_size)
        # Процессы
        self.capture = RTSPCaptureProcess(name=cam.name, rtsp_url=cam.rtsp_url, out_queue=self.q_frames,
                                          queue_size=rt.capture_queue_size, drop_newest=True)
        self.ocr_workers = [OCRWorker(self.q_ocr_in, self.q_ocr_out, rt) for _ in range(rt.ocr_workers)]

        cam_node = yaml.safe_load(open(self.masks_path, "r", encoding="utf-8"))["cameras"][self.cam.name]
        disp_cfg = cam_node.get("display", {}) if isinstance(cam_node, dict) else {}
        self.display = None
        if disp_cfg.get("enabled", False):
            self.display = DisplayPublisher(
                channel=disp_cfg.get("channel", f"lpr:{self.cam.name}:display"),
                fps_limit=int(disp_cfg.get("fps_limit", 10)),
            )

    def start(self):
        self.capture.start()
        for w in self.ocr_workers:
            w.start()

    def stop(self):
        # процессы как демоны завершатся при выходе
        pass

    def run_forever(self):
        self.start()
        mask_cfg = self.masks.get(self.cam.mask_name)
        win_name = f"LPR:{self.cam.name}"
        while True:
            pkt = self.q_frames.get(timeout=0.5)
            frame = pkt.frame

            # 1) ДИСПЛЕЙ: публикуем полный кадр (без вырезов)
            if self.display:
                self.display.maybe_publish(frame, kind="raw")

            # 2) АНАЛИЗ: применяем маску только для анализа
            roi = apply_mask(frame, mask_cfg, mode="analysis")

            boxes = self.detector.detect(roi)
            for b in boxes:
                x1, y1, x2, y2 = b.xyxy
                crop = roi[y1:y2, x1:x2].copy()
                if crop.size == 0:
                    continue
                # отправляем на OCR
                self.q_ocr_in.put(OCRTask(crop=crop, src_name=self.cam.name, bbox=b.xyxy))

            # Читаем готовые OCR-ответы без блокировок
            while not self.q_ocr_out.empty():
                res = self.q_ocr_out.get()
                if res.conf < self.rt.ocr_conf_threshold:
                    continue
                cls = classify_plate(res.text)
                if cls:
                    ptype, plate = cls
                    print(f"[{self.cam.name}] {ptype} → {plate} (conf={res.conf:.2f})")
                    # здесь же можно дернуть шлагбаум/логирование/БД и т.д.

            # Отладочное окно при необходимости
            if self.cam.show_window or self.rt.show_debug_windows:
                dbg = roi.copy()
                for b in boxes:
                    x1, y1, x2, y2 = b.xyxy
                    cv2.rectangle(dbg, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.imshow(win_name, dbg)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        cv2.destroyAllWindows()