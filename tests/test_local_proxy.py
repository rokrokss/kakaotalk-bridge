"""Exercise the shipped Caddy routes using disposable loopback listeners."""

import http.client
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["local", "public"])
def test_proxy_routes_and_cookie_boundaries(tmp_path, kind):
    caddy = shutil.which("caddy")
    if not caddy:
        pytest.skip("caddy is not installed")

    class Admin(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            for name in (
                "kakao-admin-local-18789",
                "passkey-admin-local-18789",
                "__Secure-kakao-admin-v2",
                "__Host-kakao-link",
            ):
                self.send_header("Set-Cookie", name + "=synthetic; Path=/")
            self.end_headers()
            self.wfile.write(json.dumps(self.headers.get_all("Cookie", [])).encode())

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Admin) as upstream:
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = (Path(__file__).resolve().parents[1] / f"docker/Caddyfile.{kind}").read_text()
        config = config.replace(":8785" if kind == "local" else ":8786", f":{port}").replace(
            "admin:8080", f"127.0.0.1:{upstream.server_port}"
        )
        config = config.replace("dot-plugin:8787", f"127.0.0.1:{upstream.server_port}")
        config = config.replace(f":{port} {{", f":{port} {{\n    bind 127.0.0.1")
        path = tmp_path / "Caddyfile"
        path.write_text(config)
        process = subprocess.Popen(
            [caddy, "run", "--config", str(path), "--adapter", "caddyfile"],
            env={**os.environ, "ADMIN_LOCAL_HOST": f"localhost:{port}"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    if process.poll() is not None:
                        pytest.fail("Caddy failed to start")
                    time.sleep(0.02)
            if kind == "public":
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    connection.request(
                        "GET",
                        "/authorize",
                        headers={
                            "Cookie": "kakao-admin-local-18789=private; passkey-admin-local-18789=private; "
                            "__Secure-kakao-admin-v2=private; __Host-kakao-link=keep"
                        },
                    )
                    response = connection.getresponse()
                    assert response.status == 200
                    forwarded = response.read().decode()
                    assert "private" not in forwarded
                    assert "__Host-kakao-link=keep" in forwarded
                    cookies = [
                        value
                        for name, value in response.getheaders()
                        if name.lower() == "set-cookie" and value
                    ]
                    assert cookies == ["__Host-kakao-link=synthetic; Path=/"]
                finally:
                    connection.close()
                return
            for host, route, expected in (
                (f"localhost:{port}", "/admin/", 200),
                (f"localhost:{port}", "/", 302),
                (f"localhost:{port}", "/mcp", 404),
                (f"localhost:{port}", "/v1/status", 404),
                (f"localhost:{port}", "/passkeys/admin/info", 404),
                ("evil.test", "/admin/", 403),
                (f"localhost:{port + 1}", "/admin/", 403),
                (f"127.0.0.1:{port}", "/admin/", 403),
            ):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    connection.request("GET", route, headers={"Host": host})
                    response = connection.getresponse()
                    assert response.status == expected, (host, route, response.status)
                    response.read()
                finally:
                    connection.close()
        finally:
            process.terminate()
            process.wait(timeout=5)
            upstream.shutdown()
