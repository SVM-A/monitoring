# app/util/mask.py

# Утилита для маскировки логинов/паролей в RTSP-строках при логировании.
def mask_url(u: str) -> str:
    # rtsp://user:pass@host:port/...
    try:
        head, tail = u.split("://", 1)
        if "@" in tail and ":" in tail.split("@", 1)[0]:
            creds, rest = tail.split("@", 1)
            user, _ = creds.split(":", 1)
            return f"{head}://{user}:***@{rest}"
    except Exception:
        pass
    return u