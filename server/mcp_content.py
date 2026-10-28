"""MCP content blocks for one fetched image or file. No CDN URLs."""

import base64
import json
from urllib.parse import unquote


def image_summary(message_id, variant, index, headers):
    return {
        "message_id": message_id,
        "variant": variant,
        "index": index,
        "mime": headers.get("x-bridge-mime"),
        "width": _num(headers.get("x-bridge-width")),
        "height": _num(headers.get("x-bridge-height")),
        "count": _num(headers.get("x-bridge-count")),
        "role": headers.get("x-bridge-role"),
        "attachment_type": headers.get("x-bridge-attachment-type"),
    }


def file_summary(message_id, headers, size):
    encoded = headers.get("x-bridge-file-name")
    name = unquote(encoded) if isinstance(encoded, str) else None
    if name and any(ord(ch) < 32 for ch in name):
        name = None
    return {
        "message_id": message_id,
        "name": (name or "file")[:180],
        "mime": headers.get("x-bridge-mime") or "application/octet-stream",
        "size": size,
    }


def image_result(summary, data, mime):
    return {
        "content": [
            {"type": "text", "text": json.dumps(summary, ensure_ascii=False)},
            {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": mime},
        ],
        "isError": False,
    }


def file_result(summary, data, mime, message_id):
    return {
        "content": [
            {"type": "text", "text": json.dumps(summary, ensure_ascii=False)},
            {
                "type": "resource",
                "resource": {
                    "uri": f"https://kakaotalk-bridge.invalid/messages/{int(message_id)}/file",
                    "mimeType": mime,
                    "blob": base64.b64encode(data).decode(),
                },
            },
        ],
        "isError": False,
    }


def _num(value):
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
