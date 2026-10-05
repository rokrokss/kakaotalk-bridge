"""Finite read API access for the admin conversation selector; no message bodies."""

import os
from types import SimpleNamespace

from dot_plugin.collector import Collector
from server.config import secret


class EventSource:
    def collector(self):
        return Collector(
            SimpleNamespace(
                api_url=os.getenv("API_URL", "http://api:8000"), read_token=secret("READ_TOKEN")
            )
        )

    def conversations(self, q=None, cursor=None):
        return self.collector().get("/v2/conversations", q=q, cursor=cursor, limit=30)

    def checkpoint(self):
        return self.collector().checkpoint()
