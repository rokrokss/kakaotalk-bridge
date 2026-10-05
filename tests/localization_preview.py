"""Synthetic Korean UI preview and README capture; no accounts or device access."""

import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

from fastapi.staticfiles import StaticFiles

from tests.browser_tls import serve
from tests.webui_preview import FakeAndroid
from webui.app import create_app


class PreviewAndroid(FakeAndroid):
    def __init__(self):
        super().__init__()
        self.confirm(True, True)

    def setup_status(self):
        return {"state": "ready", "enrolled": True, "kakao_installed": True}


def preview():
    now = time.time()
    connections = Mock()
    connections.call.return_value = {
        "pending": [],
        "grants": [],
        "resource": "https://example.invalid/mcp",
        "approval_mode": "passkey",
        "tunnel": {
            "configured": True,
            "approved": True,
            "tunnel_id": "tunnel_" + "a" * 32,
            "expires": None,
            "last_tool_at": now - 60,
        },
    }
    setup = Mock()
    setup.call.return_value = {
        "available": True,
        "job": {"state": "idle"},
        "tunnel_configured": True,
        "tunnel_id": "tunnel_" + "a" * 32,
        "runtime_key_saved": True,
        "preferred_method": "openai-tunnel",
        "stdio": {"mcpServers": {"kakaotalk": {"command": "bridge", "args": ["mcp"]}}},
    }
    app = create_app(
        "preview-only-key-" + "0" * 32,
        PreviewAndroid(),
        lambda: {
            "state": "collecting_partial",
            "warnings": [],
            "last_observation_received_at": datetime.fromtimestamp(now - 300, UTC).isoformat(),
        },
        auth_mode="local",
        connections=connections,
        setup_client=setup,
    )
    app.mount("/preview-assets", StaticFiles(directory=Path(__file__).parents[1] / "docs/assets"))
    return app


if __name__ == "__main__":
    serve(preview(), 19450)
