import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class QueryError(ValueError):
    pass


ATTACHMENT_ERRORS = {
    "message_not_found_or_expired",
    "attachment_not_in_device_database",
    "attachment_decrypt_failed",
    "attachment_too_large",
    "attachment_not_in_current_database",
    "attachment_unavailable",
    "not_an_image",
    "index_out_of_range",
    "video_not_downloaded",
    "thumbnail_unavailable",
    "image_expired",
    "image_unavailable",
    "image_too_large",
    "host_not_allowed",
    "not_a_file",
    "file_too_large",
    "file_unavailable",
}


class Collector:
    def __init__(self, config):
        self.config = config

    def get(self, path, **params):
        request = Request(
            self.config.api_url.rstrip("/")
            + path
            + "?"
            + urlencode(
                {
                    k: str(v).lower() if isinstance(v, bool) else v
                    for k, v in params.items()
                    if v is not None
                }
            ),
            headers={"Authorization": "Bearer " + self.config.read_token},
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError
                return json.loads(data)
        except HTTPError as exc:
            if exc.code == 400:
                raise QueryError("invalid_query_or_expired_cursor") from None
            raise RuntimeError("collector_unavailable") from None
        except (OSError, ValueError):
            raise RuntimeError("collector_unavailable") from None

    def checkpoint(self):
        return self.get("/v1/checkpoint")

    def attachment(self, message_id):
        return self._json("/v2/attachments", 25, 1024 * 1024, message_id=message_id)

    def image(self, message_id, variant, index):
        return self._bytes(
            "/v2/attachments/image", message_id=message_id, variant=variant, index=index
        )

    def file(self, message_id):
        return self._bytes("/v2/attachments/file", message_id=message_id)

    def _json(self, path, timeout, limit, **params):
        _status, _headers, body = self._open(path, timeout, limit, **params)
        try:
            return json.loads(body)
        except ValueError:
            raise RuntimeError("collector_unavailable") from None

    def _bytes(self, path, **params):
        _status, headers, body = self._open(path, 35, 2 * 1024 * 1024, **params)
        return body, headers

    def _open(self, path, timeout, limit, **params):
        request = Request(
            self.config.api_url.rstrip("/")
            + path
            + "?"
            + urlencode({k: v for k, v in params.items() if v is not None}),
            headers={"Authorization": "Bearer " + self.config.read_token},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(limit + 1)
                headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            _raise_attachment(exc)
        except (OSError, ValueError):
            raise RuntimeError("collector_unavailable") from None
        if len(body) > limit:
            if path.endswith("/file"):
                raise QueryError("file_too_large")
            if path.endswith("/image"):
                raise QueryError("image_too_large")
            raise QueryError("attachment_too_large")
        return 200, headers, body

    def outgoing(self, request_id=None, body=None):
        if not self.config.send_token:
            raise QueryError("sending_not_configured")
        request = Request(
            self.config.api_url.rstrip("/")
            + "/v1/outgoing"
            + ("/" + request_id if request_id else ""),
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.config.send_token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code in {400, 404, 409, 422, 423, 429, 503}:
                # API errors are bounded codes, never user content.
                try:
                    reason = json.loads(exc.read(4096)).get("error")
                except (OSError, ValueError, AttributeError):
                    reason = None
                allowed = {
                    "request_id_conflict",
                    "conversation_not_in_current_enrollment",
                    "sending_unavailable_confirm_login_and_upgrade_iris",
                    "sending_unavailable_until_kakaotalk_notification",
                    "send_rate_limited",
                    "send_request_not_found",
                    "sending_not_configured",
                }
                raise QueryError(
                    reason
                    if isinstance(reason, str) and reason in allowed
                    else "send_request_rejected_check_status_and_collector"
                ) from None
            raise RuntimeError("collector_unavailable") from None
        except (OSError, ValueError):
            raise RuntimeError("send_result_unavailable_reuse_request_id") from None

    def messages(self, after, limit=50):
        return self.get("/v1/messages", after=after, limit=limit)


def _raise_attachment(exc):
    try:
        reason = json.loads(exc.read(4096)).get("error")
    except (OSError, ValueError, AttributeError):
        reason = None
    if isinstance(reason, str) and reason in ATTACHMENT_ERRORS:
        raise QueryError(reason) from None
    raise RuntimeError("collector_unavailable") from None
