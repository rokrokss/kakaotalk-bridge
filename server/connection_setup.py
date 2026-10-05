"""Shared, dependency-free input contract for the finite host setup service."""

import re
from urllib.parse import urlsplit

METHODS = {"none", "stdio", "https", "tailscale", "openai-tunnel", "check"}


def validate(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("method"), str)
        or data["method"] not in METHODS
    ):
        raise ValueError("Choose a supported connection method.")
    allowed = {"method", "request_id"} | {
        "https": {"url"},
        "tailscale": {"install_tailscale"},
        "openai-tunnel": {"tunnel_id", "api_key", "approve"},
    }.get(data["method"], set())
    if set(data) - allowed or not re.fullmatch(
        r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(data.get("request_id", ""))
    ):
        raise ValueError("Invalid setup request. Reload the page and try again.")
    if data["method"] == "https":
        value = data.get("url")
        if not isinstance(value, str) or len(value) > 253:
            raise ValueError("Enter your public HTTPS origin.")
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
            or (url.port is not None and not 1 <= url.port <= 65535)
            or not re.fullmatch(r"https://[a-z0-9.-]+(?::[0-9]{1,5})?", value)
        ):
            raise ValueError("Use an HTTPS origin without a path or trailing slash.")
    if data["method"] == "tailscale" and data.get("install_tailscale") is not True:
        raise ValueError("Allow Tailscale setup and public Funnel access to continue.")
    if data["method"] == "openai-tunnel":
        if not re.fullmatch(r"tunnel_[a-z0-9]{32}", str(data.get("tunnel_id", ""))):
            raise ValueError("Enter the tunnel ID issued by OpenAI.")
        if data.get("approve") is not True:
            raise ValueError("Allow this personal tunnel to access collected messages.")
        key = data.get("api_key", "")
        if not isinstance(key, str) or (key and not re.fullmatch(r"[A-Za-z0-9_-]{20,512}", key)):
            raise ValueError("Enter a valid runtime API key.")
    return dict(data)
