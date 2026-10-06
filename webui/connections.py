"""Finite client for the backend-only OAuth approval service."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.config import secret


class RequestChanged(Exception):
    pass


class Connections:
    def call(self, method, path, data=None):
        request = Request(
            os.getenv("DOT_CONTROL_URL", "http://dot-control:8788") + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={
                "Authorization": "Bearer " + secret("MCP_APPROVAL_TOKEN"),
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=3) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 409:
                try:
                    detail = json.load(exc).get("detail", "")
                except ValueError:
                    detail = ""
                raise RequestChanged(detail if isinstance(detail, str) else "") from None
            raise
