# app/core/signals.py

import signal

from app.core.cam_configs.config_loader import reload_roi_from


def handle_sighup(signum, frame):
    global GLOBAL_ROI
    print("SIGHUP received — reloading ROI config")
    GLOBAL_ROI = reload_roi_from()

if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, handle_sighup)