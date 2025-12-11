# app/camera/onvif_client.py (замена файла)

from __future__ import annotations
import datetime as dt, socket, ssl, re
from dataclasses import dataclass
from typing import Optional, Tuple, Iterable
from urllib.parse import urlunsplit, urlsplit
import http.client, hashlib, base64, os

from app.core.config import get_debug_flags


def _tcp_open(host: str, port: int, use_ssl: bool, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            if use_ssl:
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(sock, server_hostname=host):
                    return True
            return True
    except Exception:
        return False

def _service_url(scheme: str, host: str, port: int, path: str = "/onvif/device_service") -> str:
    return urlunsplit((scheme, f"{host}:{port}", path, "", ""))

def _now_utc() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def _soap_envelope(body_xml: str, username: str, password: str, created: str, nonce_b64: str) -> str:
    digest = hashlib.sha1(base64.b64decode(nonce_b64) + created.encode() + password.encode()).digest()
    digest_b64 = base64.b64encode(digest).decode()
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
            xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <s:Header>
    <wsse:Security s:mustUnderstand="1">
      <wsse:UsernameToken>
        <wsse:Username>{username}</wsse:Username>
        <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest_b64}</wsse:Password>
        <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</wsse:Nonce>
        <wsu:Created>{created}</wsu:Created>
      </wsse:UsernameToken>
    </wsse:Security>
  </s:Header>
  <s:Body>{body_xml}</s:Body>
</s:Envelope>""".strip()

def _http_post(url: str, payload: str, timeout: float = 4.0) -> Tuple[int, str]:
    parts = urlsplit(url)
    is_https = parts.scheme == "https"
    ConnCls = http.client.HTTPSConnection if is_https else http.client.HTTPConnection
    kwargs = {"timeout": timeout}
    if is_https:
        kwargs["context"] = ssl._create_unverified_context()
    conn = ConnCls(parts.hostname, parts.port, **kwargs)
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    try:
        conn.request("POST", parts.path or "/onvif/device_service", payload.encode("utf-8"), headers)
        resp = conn.getresponse()
        data = resp.read().decode(errors="ignore")
        return resp.status, data
    finally:
        try: conn.close()
        except Exception: pass

@dataclass
class OnvifAuth:
    host: str
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    use_https: Optional[bool] = None
    path: str = "/onvif/device_service"
    PORT_CANDIDATES: Tuple[int, ...] = (80, 8080, 8899, 8999, 8000, 2020, 443)

    def candidates(self) -> Iterable[Tuple[str, int]]:
        schemes = ("http", "https") if self.use_https is None else ( "https" if self.use_https else "http", )
        ports = (self.port,) if self.port else self.PORT_CANDIDATES
        for s in schemes:
            for p in ports:
                yield s, p

class OnvifClient:
    def __init__(self, auth: OnvifAuth, log: bool = True):
        self.auth = auth
        self._service_url: Optional[str] = None
        self._time_delta: dt.timedelta = dt.timedelta(0)
        self._log = log
        self._debug = get_debug_flags().ONVIF_DEBUG

    def _log_info(self, msg: str):
        if self._log:
            print(f"[onvif] {msg}")

    def _soap_call(self, url: str, body_xml: str) -> str:
        if not self.auth.user or not self.auth.password:
            raise RuntimeError("ONVIF credentials are required")
        created_dt = _now_utc() + self._time_delta
        created = created_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        nonce_b64 = base64.b64encode(os.urandom(16)).decode()
        status, data = _http_post(url, _soap_envelope(body_xml, self.auth.user, self.auth.password, created, nonce_b64))
        if self._debug:
            snippet = data[:600].replace("\n", " ")
            self._log_info(f"HTTP {status}, SOAP snippet: {snippet[:600]}...")
        if status >= 400 or "<Fault>" in data:
            fault = "SOAP Fault" if "<Fault>" in data else f"HTTP {status}"
            # вытащим короткое описание <Reason> или <Text>
            m = re.search(r"<Reason>.*?<Text[^>]*>(.*?)</Text>.*?</Reason>", data, re.S)
            reason = (" — " + m.group(1).strip()) if m else ""
            raise RuntimeError(f"ONVIF call failed: {fault}{reason}")
        return data

    def resolve_service(self) -> str:
        if self._service_url:
            return self._service_url
        user_mask = "***" if self.auth.user else "(none)"
        self._log_info(f"auth user={user_mask} host={self.auth.host}")
        for scheme, port in self.auth.candidates():
            if not _tcp_open(self.auth.host, port, use_ssl=(scheme == "https")):
                continue
            url = _service_url(scheme, self.auth.host, port, self.auth.path)
            self._log_info(f"probe service at {url}")
            try:
                self._sync_time(url)
                self._service_url = url
                self._log_info(f"service resolved: {url}")
                return url
            except Exception as e:
                self._log_info(f"probe failed on {url}: {e}")
        raise RuntimeError("ONVIF device_service not found on known ports/schemes")

    def _sync_time(self, url: str) -> None:
        resp = self._soap_call(url, '<tds:GetSystemDateAndTime xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>')
        def _pick(tag: str) -> Optional[int]:
            m = re.search(fr"<{tag}>(\d+)</{tag}>", resp)
            return int(m.group(1)) if m else None
        y, mo, d = _pick("Year"), _pick("Month"), _pick("Day")
        h, mi, s = _pick("Hour"), _pick("Minute"), _pick("Second")
        if all(v is not None for v in (y, mo, d, h, mi, s)):
            cam_time = dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc)
            self._time_delta = cam_time - _now_utc()
            self._log_info(f"time sync delta: {self._time_delta}")

    def list_profiles(self):
        media_url, is_v2 = self.resolve_media_service()
        ns = "tr2" if is_v2 else "trt"
        wsdl = "http://www.onvif.org/ver20/media/wsdl" if is_v2 else "http://www.onvif.org/ver10/media/wsdl"
        body = f'<{ns}:GetProfiles xmlns:{ns}="{wsdl}"/>'
        xml = self._soap_call(media_url, body)

        # Парсим как tr2:, так и trt: (некоторые камеры миксуют теги)
        profs = re.findall(
            r'<(?:trt|tr2):Profiles[^>]*\s?token="([^"]+)"[^>]*>\s*<tt:Name>(.*?)</tt:Name>(.*?)</(?:trt|tr2):Profiles>',
            xml, re.S
        )
        out = []
        for prof_token, name, inner in profs:
            m = re.search(r'<tt:VideoEncoderConfiguration[^>]*\s?token="([^"]+)"', inner)
            venc_token = m.group(1) if m else None
            out.append({"profile_token": prof_token, "name": name.strip(), "video_enc_token": venc_token})

        # Fallback: если вдруг ответ пустой — попробуем альтернативный стек (Media1 vs Media2)
        if not out:
            alt_url, alt_v2 = (self.resolve_media_service()[0], not is_v2)
            ns2 = "tr2" if alt_v2 else "trt"
            wsdl2 = "http://www.onvif.org/ver20/media/wsdl" if alt_v2 else "http://www.onvif.org/ver10/media/wsdl"
            xml2 = self._soap_call(alt_url, f'<{ns2}:GetProfiles xmlns:{ns2}="{wsdl2}"/>')
            profs2 = re.findall(
                r'<(?:trt|tr2):Profiles[^>]*\s?token="([^"]+)"[^>]*>\s*<tt:Name>(.*?)</tt:Name>(.*?)</(?:trt|tr2):Profiles>',
                xml2, re.S
            )
            for prof_token, name, inner in profs2:
                m = re.search(r'<tt:VideoEncoderConfiguration[^>]*\s?token="([^"]+)"', inner)
                venc_token = m.group(1) if m else None
                out.append({"profile_token": prof_token, "name": name.strip(), "video_enc_token": venc_token})

        self._log_info("profiles: " + (", ".join(
            [f"{p['name']} (prof={p['profile_token']}, venc={p['video_enc_token']})" for p in out]) if out else "none"))
        return out

    def _resolve_video_enc_token(self, token: str) -> str:
        """Принимает либо video-encoder-token, либо profile-token → возвращает video-encoder-token."""
        # Эвристика: токены профилей у многих в стиле 'Profile_*'
        if token and token.lower().startswith("profile_"):
            profs = self.list_profiles()
            # 1) точное совпадение по profile_token
            for p in profs:
                if p["profile_token"] == token and p["video_enc_token"]:
                    return p["video_enc_token"]
            # 2) если точного нет — берём первый с video_enc_token
            for p in profs:
                if p["video_enc_token"]:
                    return p["video_enc_token"]
            raise RuntimeError("No VideoEncoderConfiguration token found for given profile token")
        # Иначе считаем, что нам уже дали video-encoder-token
        return token

    def set_video_encoder(self, profile_or_venc_token: str, width: int, height: int, bitrate_kbps: int,
                          fps: Optional[int] = None) -> None:
        media_url, is_v2 = self.resolve_media_service()
        venc_token = self._resolve_video_enc_token(profile_or_venc_token)
        fps_xml = f"<tt:FrameRate>{fps}</tt:FrameRate>" if fps else ""
        ns = "tr2" if is_v2 else "trt"
        wsdl = "http://www.onvif.org/ver20/media/wsdl" if is_v2 else "http://www.onvif.org/ver10/media/wsdl"
        body = f"""
        <{ns}:SetVideoEncoderConfiguration xmlns:{ns}="{wsdl}" xmlns:tt="http://www.onvif.org/ver10/schema">
          <{ns}:Configuration token="{venc_token}">
            <tt:Resolution><tt:Width>{width}</tt:Width><tt:Height>{height}</tt:Height></tt:Resolution>
            <tt:RateControl><tt:BitrateLimit>{bitrate_kbps}</tt:BitrateLimit>{fps_xml}</tt:RateControl>
          </{ns}:Configuration>
          <{ns}:ForcePersistence>true</{ns}:ForcePersistence>
        </{ns}:SetVideoEncoderConfiguration>
        """.strip()
        self._soap_call(media_url, body)
        self._log_info(f"encoder applied: {width}x{height}@{bitrate_kbps}kbps{(' fps=' + str(fps)) if fps else ''}")

    def _get_services(self) -> list[tuple[str, str]]:
        """Вернёт список (Namespace, XAddr) всех сервисов устройства с device_service."""
        url = self.resolve_service()
        body = """
        <tds:GetServices xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
          <tds:IncludeCapability>false</tds:IncludeCapability>
        </tds:GetServices>
        """.strip()
        xml = self._soap_call(url, body)
        pairs = re.findall(r"<tds:Namespace>(.*?)</tds:Namespace>.*?<tds:XAddr>(.*?)</tds:XAddr>", xml, re.S)
        if self._debug:
            self._log_info("services: " + " | ".join([f"{ns} -> {x}" for ns, x in pairs]) or "none")
        return pairs

    def resolve_media_service(self) -> tuple[str, bool]:
        """
        Возвращает (media_url, is_v2). Сначала пробуем Media2 (ver20), потом Media1 (ver10).
        Если не нашли — на крайний случай используем device_service.
        """
        services = self._get_services()
        med2 = next((x for ns, x in services if "ver20/media/wsdl" in ns), None)
        if med2:
            self._log_info(f"media service v2: {med2}")
            return med2, True
        med1 = next((x for ns, x in services if "ver10/media/wsdl" in ns), None)
        if med1:
            self._log_info(f"media service v1: {med1}")
            return med1, False
        self._log_info("media service not advertised, fallback to device_service")
        return self.resolve_service(), False
