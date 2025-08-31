# =============================== app/monitoring/run_monitor.py ===============================
from __future__ import annotations
import argparse
import yaml
from app.monitoring.pipeline import LPRPipeline, CameraConfig
from app.monitoring.roi.masks import MaskStore
from app.monitoring.config_runtime import RuntimeOptions

"""
Пример запуска:
python -m app.monitoring.run_monitor \
  --cameras config/cameras.yaml \
  --camera falcone_resiver_cam2 \
  --det-model models/plate_yolov5s.onnx

Перед этим подготовь cameras.yaml и модель.
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", type=str, default="config/cameras.yaml")
    ap.add_argument("--camera", type=str, required=True)
    ap.add_argument("--det-model", type=str, default="models/plate_yolov5s.onnx")
    args = ap.parse_args()

    with open(args.cameras, "r", encoding="utf-8") as f:
        cams = yaml.safe_load(f)

    cam_cfg = cams["cameras"][args.camera]
    cam = CameraConfig(
        name=args.camera,
        rtsp_url=cam_cfg["rtsp"],
        mask_name=args.camera,
        show_window=bool(cam_cfg.get("debug_window", False)),
    )

    masks = MaskStore(args.cameras)
    rt = RuntimeOptions.from_env()

    pipe = LPRPipeline(cam=cam, masks=masks, rt=rt, detector_model=args.det_model)
    pipe.run_forever()

if __name__ == "__main__":
    main()
