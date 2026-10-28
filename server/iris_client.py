"""Call the iris-collector sidecar. Failures stay stable reason codes."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CODE = re.compile(r"[a-z_]{3,64}")


class IrisError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class IrisClient:
    def __init__(self, base_url, token, opener=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.opener = opener or urlopen

    def attachment(self, *, log_id, database_id, enrollment_epoch):
        return self._json(
            "/internal/attachment",
            {
                "log_id": str(log_id),
                "database_id": database_id,
                "enrollment_epoch": enrollment_epoch,
            },
            timeout=20,
            limit=96 * 1024,
        )

    def media(self, url, kind):
        _status, headers, body = self._request(
            "/internal/media",
            {"url": url, "kind": kind},
            timeout=35,
            limit=2 * 1024 * 1024 + 1,
        )
        if len(body) > 2 * 1024 * 1024:
            raise IrisError("download_too_large")
        return (
            body,
            headers.get("x-bridge-mime") or "application/octet-stream",
            _header_int(headers.get("x-bridge-width")),
            _header_int(headers.get("x-bridge-height")),
        )

    def _json(self, path, payload, timeout, limit):
        _status, _headers, body = self._request(path, payload, timeout, limit)
        try:
            value = json.loads(body)
        except ValueError:
            raise IrisError("attachment_unavailable") from None
        if not isinstance(value, dict):
            raise IrisError("attachment_unavailable")
        return value

    def _request(self, path, payload, timeout, limit):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener(request, timeout=timeout) as response:
                body = response.read(limit + 1)
                headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            raise IrisError(_error_code(exc) or "attachment_unavailable") from None
        except (TimeoutError, OSError, URLError, ValueError):
            raise IrisError("attachment_unavailable") from None
        if len(body) > limit:
            raise IrisError("download_too_large")
        return 200, headers, body


def _header_int(value):
    if isinstance(value, str) and value.isdigit() and int(value) < 100000:
        return int(value)
    return None


def _error_code(exc):
    try:
        payload = json.loads(exc.read(4096))
    except (OSError, ValueError, AttributeError):
        return None
    reason = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(reason, str) and CODE.fullmatch(reason):
        return reason
    return None
