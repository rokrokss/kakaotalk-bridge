"""Loopback-only synthetic onboarding fixture; no ADB, Tailscale or real accounts."""

from unittest.mock import Mock

from tests.browser_tls import serve
from tests.webui_preview import FakeAndroid
from webui.app import create_app


class SetupAndroid(FakeAndroid):
    def __init__(self):
        super().__init__()
        self.setup = {"state": "needs_setup", "locale": "en-US"}

    def setup_status(self):
        return dict(self.setup)

    def prepare(self):
        self.calls.append(("prepare", ()))
        self.setup.update(aurora_installed=True, locale="ko-KR")
        return True

    def configure(self):
        if not self.setup.get("kakao_installed"):
            raise RuntimeError("kakao_not_installed")
        self.calls.append(("configure", ()))
        self.setup["enrolled"] = True
        return True


def preview():
    android = SetupAndroid()
    connections = Mock()
    connections.call.return_value = {
        "pending": [],
        "grants": [],
        "resource": "https://example.invalid/mcp",
        "approval_mode": "passkey",
    }
    app = create_app(
        "preview-only-key-" + "0" * 32,
        android,
        lambda: {"state": "needs_attention", "warnings": []},
        auth_mode="local",
        connections=connections,
    )

    @app.post("/test/install-kakao")
    def install():
        android.setup["kakao_installed"] = True
        return {"ok": True}

    @app.post("/test/sign-in")
    def sign_in():
        android.logged_in = True
        return {"ok": True}

    @app.get("/test/calls")
    def calls():
        return [name for name, _ in android.calls]

    return app


if __name__ == "__main__":
    serve(preview(), 19449)
