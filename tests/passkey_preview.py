"""Disposable native WebAuthn fixture. Synthetic tablet/data; no production accounts."""

import base64
import hashlib
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from fastapi.responses import RedirectResponse

from dot_plugin.app import create_app as public_app
from dot_plugin.config import SCOPES, Config
from dot_plugin.storage import State
from server.passkeys import Passkeys
from tests.browser_tls import serve
from tests.test_dot_plugin import REDIRECT, VERIFIER, Source
from tests.webui_preview import FakeAndroid
from webui.app import create_app

ADMIN = "https://localhost:19446"
PUBLIC = "https://localhost:19447"


def previews(folder):
    passkeys = Passkeys(State(str(Path(folder) / "passkeys.db"), Fernet.generate_key()))
    passkeys.configure(ADMIN, PUBLIC)
    android = FakeAndroid()
    android.setup_status = lambda: {"state": "ready", "kakao_installed": True, "enrolled": True}
    connections = Mock()
    connections.call.return_value = {"pending": [], "grants": [], "resource": PUBLIC + "/mcp"}
    admin = create_app(
        "synthetic-" + "a" * 43,
        android,
        dict,
        auth_mode="passkey",
        passkeys=passkeys,
        connections=connections,
    )
    config = Config(
        PUBLIC, str(Path(folder) / "dot.db"), "", Fernet.generate_key(), approval_mode="passkey"
    )
    public = public_app(config, Source(), worker=False, passkeys=passkeys)

    @admin.post("/test/enroll")
    def enroll():
        return {"url": ADMIN + "/admin/#passkey-setup=" + passkeys.issue_enrollment()}

    @public.get("/test/start")
    def start():
        client = public.state.oauth.register(
            {"redirect_uris": [REDIRECT], "client_name": "ChatGPT test"}
        )
        return RedirectResponse(
            "/authorize?"
            + urlencode(
                {
                    "client_id": client["client_id"],
                    "redirect_uri": REDIRECT,
                    "resource": config.resource,
                    "scope": SCOPES,
                    "response_type": "code",
                    "code_challenge_method": "S256",
                    "state": "passkey-test",
                    "code_challenge": base64.urlsafe_b64encode(
                        hashlib.sha256(VERIFIER.encode()).digest()
                    )
                    .decode()
                    .rstrip("="),
                }
            )
        )

    return admin, public


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="passkey-browser-") as folder:
        admin, public = previews(folder)
        threading.Thread(target=serve, args=(public, 19447), daemon=True).start()
        serve(admin, 19446)
