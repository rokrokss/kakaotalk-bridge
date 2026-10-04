"""Finite RPC client for the private passkey authority."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.config import secret


class PasskeyClient:
    def __init__(self, role):
        self.role = role

    def call(self, role, operation, data=None):
        if role != self.role:
            raise ValueError("invalid_passkey_role")
        token = secret("MCP_APPROVAL_TOKEN" if role == "admin" else "MCP_PASSKEY_TOKEN")
        request = Request(
            os.getenv("DOT_CONTROL_URL", "http://dot-control:8788")
            + "/passkeys/"
            + role
            + "/"
            + operation,
            data=json.dumps(data or {}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 400:
                raise ValueError("passkey_verification_failed") from None
            raise
