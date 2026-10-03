"""Public HTTPS only, with DNS validation and TLS connections pinned to validated IPs."""

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit


class DeliveryError(Exception):
    pass


def signing_key(secret):
    try:
        if not isinstance(secret, str) or not secret.startswith("whsec_"):
            raise ValueError
        key = base64.b64decode(secret[6:], validate=True)
        if not 24 <= len(key) <= 64:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise ValueError("invalid_signing_secret") from None


def signed_headers(subscription, event_id, body, now=None):
    stamp = str(int(time.time() if now is None else now))
    keys = [subscription["secret"]]
    if subscription.get("rotation_until", 0) > (time.time() if now is None else now):
        keys.append(subscription["previous_secret"])
    message = event_id.encode() + b"." + stamp.encode() + b"." + body
    signatures = [
        "v1,"
        + base64.b64encode(hmac.new(signing_key(key), message, hashlib.sha256).digest()).decode()
        for key in keys
    ]
    return {
        "Content-Type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": stamp,
        "webhook-signature": " ".join(signatures),
        "X-MCP-Subscription-Id": subscription["id"],
    }


def public_addresses(url):
    target = urlsplit(url)
    if (
        target.scheme != "https"
        or not target.hostname
        or target.username
        or target.password
        or target.fragment
        or len(url) > 4096
    ):
        raise DeliveryError("invalid_url")
    try:
        entries = socket.getaddrinfo(target.hostname, target.port or 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(item[4][0] for item in entries))
        if not addresses:
            raise ValueError
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if (
                not ip.is_global
                or ip.is_multicast
                or ip.is_unspecified
                or getattr(ip, "scope_id", None)
            ):
                raise ValueError
            if isinstance(ip, ipaddress.IPv6Address) and (
                ip.ipv4_mapped or ip.sixtofour or ip.teredo
            ):
                raise ValueError
        return target, sorted(addresses, key=lambda item: ipaddress.ip_address(item).version)
    except (OSError, ValueError):
        raise DeliveryError("invalid_url") from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, address):
        super().__init__(host, port, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def public_request(url, method="GET", body=None, headers=None):
    target, addresses = public_addresses(url)
    conn = PinnedHTTPS(target.hostname, target.port or 443, addresses[0])
    try:
        path = target.path or "/"
        if target.query:
            path += "?" + target.query
        conn.request(method, path, body=body, headers=headers or {"Accept": "application/json"})
        response = conn.getresponse()
        content = response.read(65537)
        if len(content) > 65536:
            raise DeliveryError("response_too_large")
        # Redirects are returned as failures, never followed.
        return response.status, content
    except TimeoutError:
        raise DeliveryError("timeout") from None
    except (OSError, http.client.HTTPException):
        raise DeliveryError("transport_failed") from None
    finally:
        conn.close()


def deliver(subscription, event_id, body):
    if len(body) > 262144:
        raise DeliveryError("payload_too_large")
    return public_request(
        subscription["url"], "POST", body, signed_headers(subscription, event_id, body)
    )


def verify_callback(subscription):
    import secrets

    challenge = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"type": "verification", "challenge": challenge}, separators=(",", ":")
    ).encode()
    status, body = deliver(subscription, "verify_" + secrets.token_hex(16), payload)
    try:
        echoed = json.loads(body).get("challenge", "")
        valid = isinstance(echoed, str) and hmac.compare_digest(echoed.encode(), challenge.encode())
    except (ValueError, AttributeError):
        valid = False
    if not 200 <= status < 300 or not valid:
        raise DeliveryError("challenge_failed")
