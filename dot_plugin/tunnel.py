"""Private, single-owner MCP listener. The public listener never accepts this credential."""

import hmac
import re

from dot_plugin.auth import AuthError, OAuth
from dot_plugin.config import Config
from dot_plugin.storage import State
from server.config import secret


class TunnelAuth(OAuth):
    transport = "tunnel"

    def __init__(self, config, state, authorization, passkeys=None):
        if not config.tunnel_id or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43,}", authorization):
            raise ValueError("Configure the personal tunnel and its private credential first")
        super().__init__(config, state, passkeys)
        self.authorization = authorization

    def principal(self, authorization, *, discovery=False):
        if not hmac.compare_digest((authorization or "").encode(), self.authorization.encode()):
            raise AuthError("invalid_token", 401)
        if discovery:
            # The sidecar probes before owner approval. Metadata has no data access.
            return {}
        identity = self.state.get("settings", "tunnel_grant", "")
        grant = self.active_grant(identity)
        if not grant or grant.get("transport") != "tunnel":
            raise AuthError("tunnel_not_approved_or_expired", 403)
        return {**grant, "grant_id": identity}


def create_app(config=None, state=None, authorization=None, passkeys=None, **kwargs):
    from dot_plugin.app import create_app as mcp_app

    config = config or Config.from_env()
    state = state or State(config.database, config.storage_key)
    auth = TunnelAuth(config, state, authorization or secret("MCP_TUNNEL_AUTHORIZATION"), passkeys)
    # dot-plugin owns the single event worker for both connection modes.
    return mcp_app(config=config, state=state, auth=auth, worker=False, **kwargs)
