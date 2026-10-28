"""Map a stored message to one on-demand attachment read. Nothing is cached."""

from urllib.parse import quote

from server.attachments import classify, describe, image_target, reference_ids
from server.iris_client import IrisError
from server.media import (
    FILE_MAX,
    IMAGE_OUTPUT_MAX,
    MediaError,
    _sniff,
    safe_file_mime,
    validate_url,
)

LOOKUP = """
SELECT m.message_id, m.device_id, m.epoch, m.database_id, m.conversation_ref,
       m.message_type, c.body, o.source_seq
FROM message_lookup m
JOIN candidates c ON c.id = m.message_id
JOIN observations o ON o.id = c.observation_id
WHERE m.message_id = ?
"""


class AttachmentError(Exception):
    def __init__(self, reason, status):
        super().__init__(reason)
        self.reason = reason
        self.status = status


class Attachments:
    def __init__(self, store, config, iris):
        self.store = store
        self.config = config
        self.iris = iris

    def view(self, message_id):
        row = self._row(message_id)
        attachment, message_type = self._load(row)
        described = self._describe(row, attachment, message_type)
        described["message_id"] = row["message_id"]
        return described

    def image(self, message_id, variant, index):
        view = self.view(message_id)
        try:
            image, url = image_target(view, variant, index)
        except ValueError as exc:
            code = str(exc)
            raise AttachmentError(code, _TARGET.get(code, 409)) from None
        _check_url(url)
        try:
            data, _mime, width, height = self.iris.media(url, "image")
        except IrisError as exc:
            raise AttachmentError(*_map_media(exc.reason, "image")) from None
        if len(data) > IMAGE_OUTPUT_MAX:
            raise AttachmentError("image_too_large", 413)
        sniffed = _sniff(data)
        if not sniffed:
            raise AttachmentError("image_unavailable", 502)
        return {
            "data": data,
            "mime": sniffed,
            "headers": _image_headers(view, image, variant, sniffed, width, height),
        }

    def file(self, message_id):
        view = self.view(message_id)
        info = view.get("file") or {}
        url = info.get("url") if isinstance(info, dict) else None
        if not url:
            raise AttachmentError("not_a_file", 409)
        _check_url(url)
        try:
            data, mime, _width, _height = self.iris.media(url, "file")
        except IrisError as exc:
            raise AttachmentError(*_map_media(exc.reason, "file")) from None
        if len(data) > FILE_MAX:
            raise AttachmentError("file_too_large", 413)
        mime = safe_file_mime(mime)
        name = info.get("name") if isinstance(info.get("name"), str) else None
        return {"data": data, "mime": mime, "headers": _file_headers(name, len(data), mime)}

    def _row(self, message_id):
        with self.store.connect() as db:
            row = db.execute(LOOKUP, (message_id,)).fetchone()
        if row is None:
            raise AttachmentError("message_not_found_or_expired", 404)
        return row

    def _load(self, row):
        try:
            self._require_live(row)
            payload = self.iris.attachment(
                log_id=row["source_seq"],
                database_id=row["database_id"],
                enrollment_epoch=row["epoch"],
            )
        except IrisError as exc:
            if classify(row["message_type"])[0] == "feed":
                return None, row["message_type"]
            raise AttachmentError(*_map_iris(exc.reason)) from None
        if payload.get("database_id") != row["database_id"]:
            raise AttachmentError("attachment_not_in_current_database", 409)
        if str(payload.get("log_id")) != str(row["source_seq"]):
            raise AttachmentError("attachment_not_in_current_database", 409)
        attachment = payload.get("attachment")
        if attachment is not None and not isinstance(attachment, str):
            raise AttachmentError("attachment_decrypt_failed", 409)
        if isinstance(attachment, str) and len(attachment) > 65536:
            raise AttachmentError("attachment_too_large", 413)
        message_type = payload.get("message_type")
        if not isinstance(message_type, str) or not message_type:
            message_type = row["message_type"]
        return attachment, message_type

    def _require_live(self, row):
        bridge = self.store.bridge_status(self.config.heartbeat_timeout)
        offline = (
            not bridge
            or bridge.get("stale")
            or not bridge.get("secondary_login_confirmed")
            or not bridge.get("listener_connected")
        )
        if offline:
            raise IrisError("attachment_unavailable")
        if bridge.get("enrollment_epoch") != row["epoch"]:
            raise IrisError("attachment_not_in_current_database")
        if bridge.get("database_id") not in (None, row["database_id"]):
            raise IrisError("attachment_not_in_current_database")

    def _describe(self, row, attachment, message_type):
        users, logs = reference_ids(attachment, row["body"])
        with self.store.connect() as db:
            names = _names(db, row["conversation_ref"], users)
            message_ids = _message_ids(db, row["device_id"], row["epoch"], logs)
        return describe(
            message_type, attachment, body=row["body"], names=names, message_ids=message_ids
        )


def _check_url(url):
    try:
        validate_url(url)
    except MediaError as exc:
        raise AttachmentError(exc.reason, 400) from None


def _map_iris(reason):
    mapped = {
        "not_found": ("attachment_not_in_device_database", 409),
        "decrypt_failed": ("attachment_decrypt_failed", 409),
        "metadata_unreadable": ("attachment_decrypt_failed", 409),
        "attachment_too_large": ("attachment_too_large", 413),
        "attachment_not_in_current_database": ("attachment_not_in_current_database", 409),
        "download_too_large": ("attachment_too_large", 413),
    }
    return mapped.get(reason, ("attachment_unavailable", 503))


def _map_media(reason, kind):
    if reason == "download_too_large":
        return ("image_too_large" if kind == "image" else "file_too_large", 413)
    if reason == "image_expired" and kind == "file":
        return ("file_unavailable", 410)
    if reason == "image_unavailable" and kind == "file":
        return ("file_unavailable", 502)
    mapped = {
        "host_not_allowed": 400,
        "image_expired": 410,
        "image_unavailable": 502,
        "image_too_large": 413,
        "file_unavailable": 502,
        "file_too_large": 413,
        "attachment_unavailable": 503,
    }
    if reason in mapped:
        return reason, mapped[reason]
    fallback = "image_unavailable" if kind == "image" else "file_unavailable"
    return fallback, 502


_TARGET = {
    "not_an_image": 409,
    "index_out_of_range": 400,
    "video_not_downloaded": 409,
    "thumbnail_unavailable": 409,
    "image_unavailable": 409,
}


def _names(db, conversation_ref, users):
    wanted = set(list(users)[:40])
    if not wanted or not conversation_ref:
        return {}
    rows = db.execute(
        "SELECT sender_ref, name FROM identities WHERE conversation_ref=? AND status='resolved'",
        (conversation_ref,),
    ).fetchall()
    names = {}
    for row in rows:
        user = (row["sender_ref"] or "").rsplit(":", 1)[-1]
        if user in wanted and row["name"]:
            names[user] = row["name"]
    return names


def _message_ids(db, device_id, epoch, logs):
    wanted = []
    for value in list(logs)[:40]:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 0 < number <= 9223372036854775807:
            wanted.append(number)
    if not wanted:
        return {}
    marks = ",".join("?" * len(wanted))
    rows = db.execute(
        f"""SELECT o.source_seq AS source_seq, c.id AS id
            FROM observations o JOIN candidates c ON c.observation_id = o.id
            WHERE o.device_id=? AND o.epoch=? AND o.source_seq IN ({marks})""",
        (device_id, epoch, *wanted),
    ).fetchall()
    return {str(row["source_seq"]): row["id"] for row in rows}


def _ascii(value, fallback):
    clean = "".join(ch for ch in str(value or "") if 32 <= ord(ch) < 127)
    return (clean or fallback)[:64]


def _image_headers(view, image, variant, mime, width, height):
    headers = {
        "X-Bridge-Count": str(len(view.get("images") or [])),
        "X-Bridge-Index": str(image.get("index") or 0),
        "X-Bridge-Role": _ascii(image.get("role"), "photo"),
        "X-Bridge-Variant": variant,
        "X-Bridge-Attachment-Type": _ascii(view.get("attachment_type"), "unknown"),
        "X-Bridge-Mime": mime,
        "Cache-Control": "no-store",
    }
    if width is not None:
        headers["X-Bridge-Width"] = str(width)
    if height is not None:
        headers["X-Bridge-Height"] = str(height)
    return headers


def _file_headers(name, size, mime):
    raw = name or "file"
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in raw)
    ascii_name = (ascii_name.strip() or "file")[:80]
    encoded = quote(raw, safe="")[:1800]
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
    return {
        "Content-Disposition": disposition,
        "X-Bridge-File-Name": encoded,
        "X-Bridge-Size": str(size),
        "X-Bridge-Mime": mime,
        "Cache-Control": "no-store",
    }
