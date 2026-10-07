"""Local browser-test fixture; never connected to ADB or a real Kakao account."""

import struct
import time
import zlib

from device.enrollment import Snapshot
from device.session_status import evidence
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
        self.config = {"enrollment_epoch": "preview", "device_id": "personal-tablet"}
        self.logged_in = False

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
        self.config = {"enrollment_epoch": "preview", "device_id": "personal-tablet"}

    def enable_keyboard(self):
        self.calls.append(("keyboard", ()))

    def open_kakao(self):
        self.calls.append(("open-kakao", ()))

    def approve(self, phone_active):
        self.calls.append(("approve", (phone_active,)))
        now = time.time()
        self.config.update(
            approved_user_id="1",
            approved_at=now,
            device_fingerprint="test",
            phone_session_confirmed_at=now,
            phone_session_report="active",
            phone_session_reported_at=now,
        )

    def record_phone(self, active):
        self.calls.append(("phone-active" if active else "phone-lost", ()))
        self.config["phone_session_report"] = "active" if active else "lost"
        self.config["phone_session_reported_at"] = time.time()
        if active:
            self.config["phone_session_confirmed_at"] = time.time()
        else:
            self.config["approved_user_id"] = None

    def snapshot(self):
        return Snapshot(
            config=dict(self.config),
            characteristics="tablet",
            fingerprint="test",
            width=1200,
            height=1920,
            dpi=240,
            kakao_version=1234,
            account_ids=(1,) if self.logged_in else (),
        )

    def approved(self):
        return evidence(self.snapshot())["collection_approval"] == "approved"

    def session_status(self):
        return {
            "checked_at": time.time(),
            "device": "android_ready",
            "screen": {
                "state": "main_screen_observed" if self.logged_in else "login_required",
                "secondary_option": "unknown" if self.logged_in else "selected",
            },
            **evidence(self.snapshot()),
        }


def create_preview():
    android = FakeAndroid()
    app = create_app(
        "preview-only-key-" + "0" * 32,
        android,
        lambda: {
            "state": "collecting_partial" if android.approved() else "needs_attention",
            "warnings": [],
        },
        auth_mode="local",
    )

    @app.get("/test/calls")
    def calls():
        # No input content in this diagnostic output.
        return [name for name, _ in android.calls]

    return app
