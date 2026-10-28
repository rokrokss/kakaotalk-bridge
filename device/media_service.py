"""Token-protected attachment proxy. Binds inside iris-collector, not on the host."""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CODE = re.compile(r"[a-z_]{3,64}")
PUBLIC = {
    "invalid_request",
    "body_too_large",
    "not_found",
    "decrypt_failed",
    "metadata_unreadable",
    "attachment_too_large",
    "attachment_not_in_current_database",
    "attachment_unavailable",
    "host_not_allowed",
    "image_expired",
    "image_unavailable",
    "image_too_large",
    "file_unavailable",
    "file_too_large",
}
STATUS = {
    "invalid_request": 422,
    "body_too_large": 413,
    "not_found": 404,
    "decrypt_failed": 409,
    "metadata_unreadable": 409,
    "attachment_too_large": 413,
    "attachment_not_in_current_database": 409,
    "attachment_unavailable": 503,
    "host_not_allowed": 400,
    "image_expired": 410,
    "image_unavailable": 502,
    "image_too_large": 413,
    "file_unavailable": 502,
    "file_too_large": 413,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def log_request(self, code="-", size="-"):
        return

    def log_error(self, fmt, *args):
        return

    def do_POST(self):
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or not 1 <= int(length) <= 8192:
            code = "body_too_large" if length.isdigit() else "invalid_request"
            return self._json(413 if code == "body_too_large" else 422, {"error": code})
        try:
            payload = json.loads(self.rfile.read(int(length)))
        except ValueError:
            return self._json(422, {"error": "invalid_request"})
        path = self.path.split("?", 1)[0]
        try:
            if path == "/internal/attachment":
                return self._json(200, self.server.attachment(payload))
            if path == "/internal/media":
                data, mime, width, height = self.server.fetch(payload)
                return self._bytes(data, mime, width, height)
        except Exception as exc:  # noqa: BLE001 — response is a stable code, never the traceback
            reason = _public_reason(exc, path)
            return self._json(STATUS.get(reason, 503), {"error": reason})
        return self._json(404, {"error": "attachment_unavailable"})

    def _authorized(self):
        import hmac

        expected = "Bearer " + self.server.token
        presented = self.headers.get("Authorization", "")
        if len(presented) != len(expected):
            return False
        return hmac.compare_digest(presented.encode(), expected.encode())

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, mime, width, height):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        safe_mime = mime if isinstance(mime, str) else "application/octet-stream"
        self.send_header("X-Bridge-Mime", safe_mime)
        if isinstance(width, int):
            self.send_header("X-Bridge-Width", str(width))
        if isinstance(height, int):
            self.send_header("X-Bridge-Height", str(height))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def _public_reason(exc, path):
    reason = str(exc)
    if CODE.fullmatch(reason) and reason in PUBLIC:
        return reason
    if path == "/internal/media":
        return "image_unavailable"
    return "attachment_unavailable"


def read_attachment(payload):
    from device import enrollment
    from device.iris import BUILD, attachment_request, ensure_started, identity

    if not isinstance(payload, dict):
        raise RuntimeError("invalid_request")  # noqa: TRY004 — HTTP clients see this code
    log_id = str(payload.get("log_id", ""))
    database_id = payload.get("database_id")
    epoch = payload.get("enrollment_epoch")
    if not re.fullmatch(r"[1-9][0-9]{0,18}", log_id):
        raise RuntimeError("invalid_request")
    if not isinstance(database_id, str) or not re.fullmatch(r"[0-9A-Za-z:._-]{1,128}", database_id):
        raise RuntimeError("invalid_request")
    uuid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    if not isinstance(epoch, str) or not re.fullmatch(uuid, epoch):
        raise RuntimeError("invalid_request")
    config = enrollment.require_approved().config
    if identity(config) != epoch:
        raise RuntimeError("attachment_not_in_current_database")
    token = ensure_started(config["enrollment_epoch"])
    result = attachment_request(log_id, token)
    if (
        result.get("build") != BUILD
        or result.get("enrollment_epoch") != config["enrollment_epoch"]
        or result.get("database_id") != database_id
        or str(result.get("log_id")) != log_id
    ):
        raise RuntimeError("attachment_not_in_current_database")
    attachment = result.get("attachment")
    if attachment is not None and not isinstance(attachment, str):
        raise RuntimeError("attachment_unavailable")
    if isinstance(attachment, str) and len(attachment) > 65536:
        raise RuntimeError("attachment_too_large")
    message_type = result.get("message_type")
    return {
        "log_id": log_id,
        "database_id": database_id,
        "message_type": message_type if isinstance(message_type, str) else "",
        "attachment": attachment,
    }


def fetch_media(payload):
    from server.media import MediaError, fetch

    if not isinstance(payload, dict):
        raise RuntimeError("invalid_request")  # noqa: TRY004 — HTTP clients see this code
    kind = payload.get("kind")
    url = payload.get("url")
    if kind not in {"image", "file"} or not isinstance(url, str):
        raise RuntimeError("invalid_request")
    try:
        return fetch(url, kind)
    except MediaError as exc:
        raise RuntimeError(exc.reason) from None


def serve(port=None):
    token = Path(os.getenv("INGEST_TOKEN_FILE", "/run/secrets/ingest_token")).read_text().strip()
    if len(token) < 32:
        raise RuntimeError("attachment_unavailable")
    bind = int(port or os.getenv("IRIS_HTTP_PORT", "3010"))
    httpd = ThreadingHTTPServer(("0.0.0.0", bind), Handler)
    httpd.token = token
    httpd.attachment = read_attachment
    httpd.fetch = fetch_media
    threading.Thread(target=httpd.serve_forever, name="iris-media", daemon=True).start()
    return httpd
