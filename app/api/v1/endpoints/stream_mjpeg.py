# app/api/v1/endpoints/stream_mjpeg.py
import os
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from redis import Redis

stream_video_router = APIRouter(prefix="/stream", tags=["stream"])

def mjpeg_generator(channel: str):
    r = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    ps = r.pubsub()
    ps.subscribe(channel)
    boundary = b"frame"
    try:
        for msg in ps.listen():
            if msg.get("type") != "message":
                continue
            data: bytes = msg["data"]
            # payload: kind|jpg
            sep = data.find(b"|")
            jpg = data[sep+1:] if sep != -1 else data
            yield b"--" + boundary + b"\r\n" + \
                  b"Content-Type: image/jpeg\r\n" + \
                  b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + \
                  jpg + b"\r\n"
    finally:
        try: ps.close()
        except: pass

@stream_video_router.get("/mjpeg/{camera}")
def stream_mjpeg(camera: str):
    channel = f"lpr:{camera}:display"
    return StreamingResponse(
        mjpeg_generator(channel),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
