"""Exact HTTPS origin validation for the single-owner authentication services."""

import re
from urllib.parse import urlsplit


def validate_admin_origin(value):
    # WebAuthn permits localhost as a secure context. Never extend this exception
    # to LAN addresses or arbitrary HTTP hosts.
    if (
        isinstance(value, str)
        and re.fullmatch(r"http://localhost:[0-9]{1,5}", value)
        and 1024 <= urlsplit(value).port <= 65535
    ):
        return
    validate_origin(value)


def validate_origin(value):
    if not isinstance(value, str):
        raise TypeError("Use the exact HTTPS origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", value)
        or (parsed.port is not None and not 1 <= parsed.port <= 65535)
    ):
        raise ValueError("Use the exact HTTPS origin, without a trailing slash")
