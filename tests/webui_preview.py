"""Local browser-test fixture; never connected to ADB or a real Kakao account."""

import struct
import time
import zlib

from device.session_status import enrollment_evidence
from webui.app import create_app


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png():
    width, height = 360, 640
    raw = b"".join(b"\0" + bytes((234, 237, 231)) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeAndroid:
    def __init__(self):
        self.calls = []
        self.config = {}

    def screenshot(self):
        return png(), 360, 640

    def tap(self, *args):
        self.calls.append(("tap", args))

    def swipe(self, *args):
        self.calls.append(("swipe", args))

    def key(self, *args):
        self.calls.append(("key", args))

    def text(self, *args):
        self.calls.append(("text", args))

    def bootstrap(self):
        self.calls.append(("bootstrap", ()))

    def enable_keyboard(self):
        self.calls.append(("keyboard", ()))

    def open_kakao(self):
        self.calls.append(("open-kakao", ()))

    def login_check(self):
        self.calls.append(("login-check", ()))

    def confirm(self, *args):
        self.calls.append(("confirm", args))
        self.config = {
            "collector_mode": "iris",
            "secondary_login_version": 1234,
            "device_fingerprint": "test",
            "phone_session_confirmed_at": time.time(),
        }

    def record_phone(self, active):
        self.calls.append(("phone-active" if active else "phone-lost", ()))
        self.config["phone_session_report"] = "active" if active else "lost"
        self.config["phone_session_reported_at"] = time.time()
        if active:
            self.config["phone_session_confirmed_at"] = time.time()
        else:
            self.config["secondary_login_version"] = 0

    def session_status(self):
        return {
            "checked_at": time.time(),
            "device": "android_ready",
            "screen": {"state": "unknown", "secondary_option": "unknown"},
            **enrollment_evidence(self.config, {}, {"kakao_version": 1234, "fingerprint": "test"}),
        }


def create_preview():
    android = FakeAndroid()
    app = create_app(
        "preview-only-key-" + "0" * 32,
        android,
        lambda: {"state": "needs_attention", "warnings": []},
    )

    @app.get("/test/calls")
    def calls():
        # No input content in this diagnostic output.
        return [name for name, _ in android.calls]

    return app
