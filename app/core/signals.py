# app/core/signals.py

import signal
from app.core.cam_configs.config_loader import reload_roi_from
import app.core.constants as consts

def handle_sighup(signum, frame):
    print("SIGHUP received — reloading ROI config")
    consts.GLOBAL_ROI = reload_roi_from()

if hasattr(signal, "SIGHUP"):
    signal.signal(signal.SIGHUP, handle_sighup)
