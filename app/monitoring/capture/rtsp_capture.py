# =============================== app/monitoring/capture/rtsp_capture.py ===============================
from multiprocessing import Process, Queue
from dataclasses import dataclass
import time
import cv2

@dataclass
class FramePacket:
    frame: any
    ts: float
    src_name: str

class RTSPCaptureProcess(Process):
    def __init__(self, name: str, rtsp_url: str, out_queue: Queue, queue_size: int = 5, drop_newest: bool = True):
        super().__init__(daemon=True)
        self.name = name
        self.rtsp_url = rtsp_url
        self.out_queue = out_queue
        self.queue_size = queue_size
        self.drop_newest = drop_newest
        self._stopping = False

    def run(self):
        cap = None
        try:
            # Ускорители для RTSP (меньше задержки)
            cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FPS, 25)
            if not cap.isOpened():
                print(f"[Capture:{self.name}] Не удалось открыть поток")
                return
            while not self._stopping:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                pkt = FramePacket(frame=frame, ts=time.time(), src_name=self.name)
                # Стратегия очереди: если занято — выкидываем старое
                if self.out_queue.qsize() >= self.queue_size:
                    if self.drop_newest:
                        try:
                            self.out_queue.get_nowait()
                        except Exception:
                            pass
                    else:
                        # просто пропускаем кадр
                        continue
                try:
                    self.out_queue.put_nowait(pkt)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Capture:{self.name}] Ошибка: {e}")
        finally:
            if cap is not None:
                cap.release()

