"""Local OAuth UI fixture with disposable state and no collector or event worker."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

from cryptography.fernet import Fernet
from fastapi.responses import HTMLResponse, RedirectResponse

from dot_plugin.app import create_app
from dot_plugin.config import SCOPES, Config
from dot_plugin.pages import page


def create_preview():
    directory = TemporaryDirectory(prefix="kakao-oauth-preview-")
    base = "https://localhost:20443"
    config = Config(
        base,
        str(Path(directory.name) / "dot.db"),
        "preview-only-key-" + "0" * 32,
        Fernet.generate_key(),
        approval_mode="key",
    )
    # No API URL, real credentials or message source is used by this fixture.
    app = create_app(config, collector=object(), worker=False)
    app.state.preview_directory = directory
    redirect = base + "/test/callback"

    @app.get("/test/start")
    def start():
        client = app.state.oauth.register(
            {"redirect_uris": [redirect], "client_name": "Preview client"}
        )
        query = urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": redirect,
                "resource": config.resource,
                "scope": SCOPES,
                "response_type": "code",
                "code_challenge_method": "S256",
                "code_challenge": "a" * 43,
            }
        )
        return RedirectResponse("/authorize?" + query)

    @app.get("/test/callback")
    def callback():
        return HTMLResponse(
            page("Preview complete", "<h1>Form submitted</h1><p>No real account was connected.</p>")
        )

    return app
