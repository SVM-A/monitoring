# app/monitoring/display/publisher.py
import os, time, cv2
from typing import Optional
from redis import Redis

class DisplayPublisher:
    def __init__(self, channel: str, fps_limit: int = 10, redis_url: Optional[str] = None):
        self.channel = channel
        self.period = 1.0 / max(1, fps_limit)
        self.redis = Redis.from_url(redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        self._last = 0.0

    def maybe_publish(self, frame, kind: str = "raw"):
        now = time.time()
        if now - self._last < self.period:
            return
        self._last = now
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            # payload: kind|jpg_bytes
            self.redis.publish(self.channel, kind.encode() + b"|" + jpg.tobytes())
