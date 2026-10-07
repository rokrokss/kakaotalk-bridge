"""Public HTTPS through Tailscale Serve and Funnel."""

import argparse
import json
import os
import platform
import re
import shutil
from pathlib import Path

from ops import access, cli, lima
from ops.errors import BridgeError


def tailscale_binary():
    installed = shutil.which("tailscale")
    app = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    return installed or (str(app) if platform.system() == "Darwin" and app.is_file() else None)


def expose(args):
    tailscale = tailscale_binary()
    if not tailscale:
        raise BridgeError("Tailscale을 설치하고 로그인한 뒤 kakaotalk-bridge expose를 다시 실행하세요.")
    tailscale = (["sudo"] if platform.system() == "Linux" and os.geteuid() != 0 else []) + [
        tailscale
    ]
    status = json.loads(cli.run([*tailscale, "status", "--json"], capture=True))
    hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if status.get("BackendState") != "Running" or not re.fullmatch(
        r"[a-z0-9.-]+\.ts\.net", hostname
    ):
        raise BridgeError("Tailscale에 로그인하고 MagicDNS를 켠 뒤 다시 실행하세요.")
    existing = json.loads(cli.run([*tailscale, "serve", "status", "--json"], capture=True))
    record_path = cli.ROOT / ".bridge/expose.json"
    owned = json.loads(record_path.read_text()) if record_path.exists() else None
    if existing and (
        not owned or owned.get("hostname") != hostname or owned.get("config") != existing
    ):
        raise BridgeError("Tailscale이 이미 다른 앱을 공개하고 있습니다. 기존 설정은 그대로 두었습니다. 고급 설치 안내의 수동 포트 설정을 따르세요.")
    if platform.system() == "Darwin" and not args.local:
        config = json.loads((cli.ROOT / ".bridge/mac.json").read_text())
        local = argparse.Namespace(command="connect", url="https://" + hostname)
        lima.mac(local)
    else:
        access.connect("https://" + hostname)

    def record_routes():
        current = json.loads(cli.run([*tailscale, "serve", "status", "--json"], capture=True))
        cli.atomic(record_path, json.dumps({"hostname": hostname, "config": current}))

    mcp_port = (
        config.get("mcp_port", 18787)
        if platform.system() == "Darwin" and not args.local
        else int(cli.read_env().get("DOT_HTTP_PORT", "18787"))
    )
    cli.run([*tailscale, "funnel", "--bg", "--https=443", f"http://127.0.0.1:{mcp_port}"])
    record_routes()
    # Migrate only the old route whose complete configuration we verified above.
    # Record each successful step so a failed migration can be retried safely.
    if existing.get("Web", {}).get(hostname + ":8443"):
        cli.run([*tailscale, "serve", "--https=8443", "off"])
        record_routes()
    saved_admin = cli.ROOT / ".bridge/admin-url"
    admin_url = (
        saved_admin.read_text().strip().removesuffix("/admin/")
        if saved_admin.exists()
        else "https://" + hostname
    )
    cli.atomic(saved_admin, admin_url)
    cli.atomic(cli.ROOT / ".bridge/public-url", "https://" + hostname)
    print(
        f"관리 화면: {admin_url}/admin/\nMCP: https://{hostname}/mcp\nkakaotalk-bridge passkey-login으로 OAuth 승인을 설정하세요."
    )
