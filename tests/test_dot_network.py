import base64
import hashlib
import hmac
import json
import socket

import pytest

from dot_plugin import network


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.29.87.3",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "2001:db8::1",
        "2002:7f00:1::",
    ],
)
def test_callback_private_and_special_addresses_blocked(monkeypatch, ip):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (ip, 443))]
    )
    with pytest.raises(network.DeliveryError, match="invalid_url"):
        network.public_addresses("https://receiver.example/callback")


def test_mixed_dns_and_dns_changes_blocked(monkeypatch):
    answers = ["8.8.8.8"]
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, (ip, 443)) for ip in answers],
    )
    assert network.public_addresses("https://receiver.example/callback")[1] == answers
    answers.append("127.0.0.1")
    with pytest.raises(network.DeliveryError):
        network.public_addresses("https://receiver.example/callback")


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example/",
        "https://user:pass@public.example/",
        "https://public.example/#fragment",
        "file:///etc/passwd",
    ],
)
def test_invalid_callback_urls_blocked(url):
    with pytest.raises(network.DeliveryError):
        network.public_addresses(url)


def test_standard_webhooks_signature_exact_bytes_and_challenge(monkeypatch):
    secret = "whsec_" + base64.b64encode(b"x" * 32).decode()
    sub = {"id": "sub_1", "secret": secret, "url": "https://receiver.example/hook"}
    body = '{"value":"안녕"}'.encode()
    headers = network.signed_headers(sub, "evt_1", body, now=123)
    expected = base64.b64encode(
        hmac.new(b"x" * 32, b"evt_1.123." + body, hashlib.sha256).digest()
    ).decode()
    assert headers["webhook-signature"] == "v1," + expected
    assert headers["X-MCP-Subscription-Id"] == "sub_1"

    def echo(subscription, event_id, payload):
        value = json.loads(payload)
        assert value["type"] == "verification"
        assert event_id.startswith("verify_")
        return 200, json.dumps({"challenge": value["challenge"]}).encode()

    monkeypatch.setattr(network, "deliver", echo)
    network.verify_callback(sub)
    monkeypatch.setattr(network, "deliver", lambda *args: (200, b'{"challenge":"wrong"}'))
    with pytest.raises(network.DeliveryError, match="challenge_failed"):
        network.verify_callback(sub)


def test_https_uses_validated_address_and_never_follows_redirect(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("8.8.8.8", 443))]
    )
    calls = []

    class Connection:
        def __init__(self, host, port, address):
            calls.append((host, port, address))

        def request(self, *args, **kwargs):
            calls.append(args)

        def getresponse(self):
            return type("Response", (), {"status": 302, "read": lambda self, size: b""})()

        def close(self):
            pass

    monkeypatch.setattr(network, "PinnedHTTPS", Connection)
    assert network.public_request("https://receiver.example/path")[0] == 302
    assert calls == [("receiver.example", 443, "8.8.8.8"), ("GET", "/path")]
