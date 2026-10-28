"""Download one Kakao CDN object. Bytes are not stored or logged."""

import http.client
import ipaddress
import re
import socket
import ssl
from io import BytesIO
from urllib.parse import urljoin, urlsplit

from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 24_000_000

IMAGE_INPUT_MAX = 8 * 1024 * 1024
IMAGE_OUTPUT_MAX = 2 * 1024 * 1024
FILE_MAX = 2 * 1024 * 1024
# Kakao photo/emoticon/profile CDNs, plus the talk download hosts Iris-era clients use.
DOWNLOAD_HOSTS = {"dn-m.talk.kakao.com", "dn.talk.kakao.com", "mud-kage.kakao.com"}
EXPIRED = {401, 403, 404, 410, 451}
REDIRECTS = {301, 302, 303, 307, 308}


class MediaError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def host_allowed(host):
    host = (host or "").lower().rstrip(".")
    return host == "kakaocdn.net" or host.endswith(".kakaocdn.net") or host in DOWNLOAD_HOSTS


def validate_url(url):
    if not isinstance(url, str) or len(url) > 2048:
        raise MediaError("host_not_allowed")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.fragment
        or parts.port not in (None, 443)
        or not re.fullmatch(r"[a-z0-9.-]{1,253}", host)
        or not host_allowed(host)
    ):
        raise MediaError("host_not_allowed")
    return parts


def _public(host):
    try:
        entries = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise MediaError("image_unavailable") from None
    addresses = []
    for entry in entries:
        try:
            ip = ipaddress.ip_address(entry[4][0])
        except ValueError:
            raise MediaError("image_unavailable") from None
        if (
            not ip.is_global
            or ip.is_multicast
            or ip.is_unspecified
            or getattr(ip, "scope_id", None)
            or (
                isinstance(ip, ipaddress.IPv6Address)
                and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)
            )
        ):
            raise MediaError("image_unavailable")
        addresses.append(str(ip))
    if not addresses:
        raise MediaError("image_unavailable")
    return addresses[0]


class _Pinned(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, 443, timeout=20, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        raw = socket.create_connection((self._address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _https(url, limit):
    parts = validate_url(url)
    address = _public(parts.hostname)
    conn = _Pinned(parts.hostname, address)
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "kakaotalk-bridge/attachment",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.1",
            },
        )
        response = conn.getresponse()
        status = response.status
        if status in REDIRECTS:
            body = response.read(4096)
        else:
            announced = response.getheader("Content-Length")
            if announced and announced.isdigit() and int(announced) > limit:
                response.close()
                raise MediaError("download_too_large")
            body = response.read(limit + 1)
        headers = {key.lower(): value for key, value in response.getheaders()}
        return status, headers, body
    except MediaError:
        raise
    except (TimeoutError, OSError, http.client.HTTPException):
        raise MediaError("image_unavailable") from None
    finally:
        conn.close()


def _sniff(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg(image, edge, quality):
    frame = image.copy()
    frame.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    if frame.mode != "RGB":
        frame = frame.convert("RGB")
    buffer = BytesIO()
    frame.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue(), frame.size


def prepare_image(data, output_max=IMAGE_OUTPUT_MAX, edge=1600):
    """Return original bytes when they already fit; otherwise a smaller JPEG."""
    mime = _sniff(data)
    if not mime:
        raise MediaError("image_unavailable")
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            width, height = image.size
            frames = getattr(image, "n_frames", 1)
            if len(data) <= output_max and max(width, height) <= edge and frames == 1:
                return data, mime, width, height
            frame = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        raise MediaError("image_unavailable") from None
    quality, limit = 85, edge
    blob, (width, height) = _jpeg(frame, limit, quality)
    while len(blob) > output_max and (quality > 40 or limit > 320):
        if quality > 40:
            quality -= 15
        else:
            limit = max(320, int(limit * 0.75))
        blob, (width, height) = _jpeg(frame, limit, quality)
    if len(blob) > output_max:
        raise MediaError("image_too_large")
    return blob, "image/jpeg", width, height


def safe_file_mime(value):
    if not isinstance(value, str):
        return "application/octet-stream"
    mime = value.split(";", 1)[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}", mime):
        return "application/octet-stream"
    if mime in {"text/html", "image/svg+xml", "application/xhtml+xml"}:
        return "application/octet-stream"
    return mime


def fetch(url, kind, transport=None):
    try:
        return _fetch(url, kind, transport)
    except MediaError as exc:
        if exc.reason == "download_too_large":
            raise MediaError("image_too_large" if kind == "image" else "file_too_large") from None
        if kind == "file" and exc.reason == "image_unavailable":
            raise MediaError("file_unavailable") from None
        raise


def _fetch(url, kind, transport):
    if kind not in {"image", "file"}:
        raise MediaError("image_unavailable")
    limit = IMAGE_INPUT_MAX if kind == "image" else FILE_MAX
    transport = transport or _https
    current = url
    validate_url(current)
    for _ in range(4):
        status, headers, body = transport(current, limit)
        headers = {str(key).lower(): value for key, value in headers.items()}
        if status in REDIRECTS:
            location = headers.get("location")
            if not location:
                raise MediaError("image_unavailable")
            current = urljoin(current, location)
            validate_url(current)
            continue
        if status in EXPIRED:
            raise MediaError("image_expired" if kind == "image" else "file_unavailable")
        if status != 200:
            raise MediaError("image_unavailable" if kind == "image" else "file_unavailable")
        if len(body) > limit:
            raise MediaError("image_too_large" if kind == "image" else "file_too_large")
        if kind == "file":
            return body, safe_file_mime(headers.get("content-type")), None, None
        return prepare_image(body)
    raise MediaError("image_unavailable")
