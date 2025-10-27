import re
from urllib.parse import urlsplit, urlunsplit


def mask_url(u: str) -> str:
    """Скрывает логин/пароль в URL."""
    try:
        parts = urlsplit(u)
        netloc = parts.netloc
        if "@" in netloc:
            # user:pass@host -> ***:***@host
            host = netloc.split("@", 1)[1]
            netloc = f"***:***@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return u

def mask_text_urls(s: str) -> str:
    """
    Маскирует user:pass во всех http(s)/rtsp URL внутри произвольного текста.
    """
    if not s:
        return s
    # Ищем любые схемы http/https/rtsp и передаём каждый URL в mask_url
    url_rx = re.compile(r'(?i)\b((?:rtsp|http|https)://[^\s\'"]+)')
    def _repl(m):
        try:
            return mask_url(m.group(1))
        except Exception:
            return m.group(1)
    return url_rx.sub(_repl, s)