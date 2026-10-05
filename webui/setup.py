"""Admin-only client for the finite Unix-socket setup service."""

import http.client
import json
import os
import socket


class SetupBusy(Exception):
    pass


class SetupClient:
    def call(self, method="GET", data=None):
        connection = http.client.HTTPConnection("localhost", timeout=5)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(5)
        try:
            connection.sock.connect(os.getenv("SETUP_AGENT_SOCKET", "/run/bridge-setup/agent.sock"))
            connection.request(
                method,
                "/jobs" if method == "POST" else "/status",
                body=json.dumps(data) if data is not None else None,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status == 409:
                raise SetupBusy
            if response.status not in (200, 202):
                raise OSError("Setup service rejected the request")
            body = response.read(32769)
            if len(body) > 32768:
                raise ValueError("Setup response too large")
            return json.loads(body)
        except http.client.HTTPException:
            raise OSError("Setup service is unavailable") from None
        finally:
            connection.close()
