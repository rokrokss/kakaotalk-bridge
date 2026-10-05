import json
import time
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dot_plugin.app import create_app as public_app
from dot_plugin.app import tool_definitions
from dot_plugin.config import Config
from dot_plugin.control import create_app as control_app
from dot_plugin.storage import State
from dot_plugin.tunnel import create_app as tunnel_app
from tests.test_dot_plugin import BASE, Source, call, link, rpc, subscription

TUNNEL = "tunnel_" + "a" * 32
AUTHORIZATION = "Bearer " + "t" * 43
CONTROL = "c" * 43


class Passkeys:
    policy = "passkey:one"

    def call(self, role, operation, body=None):
        assert operation == "info"
        return {"policy": self.policy, "registered": True}


class Queries(Source):
    def get(self, path, **params):
        if path == "/v2/conversations":
            return {"items": [{"ref": "room-a"}], "next_cursor": None, "has_more": False}
        if path == "/v2/context":
            return {"items": self.rows}
        return super().get(path, **params)


@pytest.fixture
def bridge(tmp_path):
    config = Config(
        BASE,
        str(tmp_path / "dot.db"),
        "L" * 43,
        Fernet.generate_key(),
        approval_mode="key",
        tunnel_id=TUNNEL,
    )
    state = State(config.database, config.storage_key)
    keys, source, delivered = Passkeys(), Queries(), []

    def send(*args):
        delivered.append(args)
        return 200, b"{}"

    public = TestClient(
        public_app(
            config,
            source,
            state,
            worker=False,
            passkeys=keys,
            verifier=lambda sub: None,
            sender=send,
        ),
        base_url=BASE,
    )
    private = TestClient(
        tunnel_app(config, state, AUTHORIZATION, keys, collector=source, verifier=lambda sub: None),
        base_url="http://private",
    )
    private.headers["X-Bridge-Tunnel-Authorization"] = AUTHORIZATION
    control = TestClient(control_app(config, state, CONTROL, keys, "v" * 43))
    control.headers["Authorization"] = "Bearer " + CONTROL
    return private, public, control, state, keys, source, delivered, config


def approve(control, allow=True):
    response = control.post("/tunnel/decision", json={"tunnel_id": TUNNEL, "approve": allow})
    assert response.status_code == 200, response.text


def test_private_credential_is_not_public_oauth_and_browser_routes_are_absent(bridge):
    private, public, control, state, *_ = bridge
    assert (
        private.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_profile"},
            },
        ).status_code
        == 403
    )
    assert (
        private.post(
            "/mcp", json={}, headers={"X-Bridge-Tunnel-Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    approve(control)
    assert rpc(private, "server/discover")["result"]["supportedVersions"] == ["2026-07-28"]
    for path in (
        "/authorize",
        "/register",
        "/connections",
        "/admin/",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
    ):
        assert private.get(path).status_code == 404
    assert public.post("/mcp", json={}, headers={"Authorization": AUTHORIZATION}).status_code == 401
    assert public.post("/tunnel/decision", json={}).status_code == 404
    response = control.post(
        "/tunnel/decision",
        json={"tunnel_id": TUNNEL, "approve": True},
        headers={"Authorization": "Bearer " + "v" * 43},
    )
    assert response.status_code == 401
    assert "t" * 43 not in json.dumps(state.all("grant"))


def test_oauth_still_works_and_all_tools_are_shared(bridge):
    private, public, control, _, _, source, _, _ = bridge
    approve(control)
    _, form = link(public)
    access = public.post("/token", data=form).json()["access_token"]
    public.headers["Authorization"] = "Bearer " + access
    assert (
        private.post(
            "/mcp", json={}, headers={"X-Bridge-Tunnel-Authorization": "Bearer " + access}
        ).status_code
        == 401
    )
    actual = rpc(private, "tools/list")["result"]["tools"]
    expected = tool_definitions()
    assert len(actual) == 8
    for a, e in zip(actual, expected, strict=True):
        assert a.pop("securitySchemes") == [{"type": "noauth"}]
        assert e.pop("securitySchemes")[0]["type"] == "oauth2"
        assert a == e
    source.add("tunnel test")
    for name, args in (
        ("get_recent_messages", {}),
        ("search_messages", {"q": "tunnel"}),
        ("list_conversations", {}),
        ("get_conversation_context", {"message_id": 1}),
        ("get_profile", {}),
    ):
        assert call(private, name, **args)["result"] == call(public, name, **args)["result"]
    assert "result" in call(private, "get_collector_status")
    approve(control, False)
    assert "result" in call(public, "get_recent_messages")


@pytest.mark.parametrize("reason", ["revoke", "expiry", "policy", "tunnel_change"])
def test_connection_lifecycle_fails_closed(bridge, reason):
    private, _, control, state, keys, _, _, config = bridge
    approve(control)
    identity = state.get("settings", "tunnel_grant")
    assert "result" in call(private, "get_profile")
    if reason == "revoke":
        approve(control, False)
    elif reason == "expiry":
        row = state.get("grant", identity)
        row["expires"] = time.time() - 1
        state.put("grant", identity, row)
    elif reason == "policy":
        keys.policy = "passkey:changed"
    else:
        private = TestClient(
            tunnel_app(
                replace(config, tunnel_id="tunnel_" + "b" * 32),
                state,
                AUTHORIZATION,
                keys,
                collector=Queries(),
            )
        )
        private.headers["X-Bridge-Tunnel-Authorization"] = AUTHORIZATION
    assert (
        private.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_profile"},
            },
        ).status_code
        == 403
    )


def test_allow_is_idempotent_and_scopes_are_enforced(bridge):
    private, _, control, state, *_ = bridge
    approve(control)
    identity = state.get("settings", "tunnel_grant")
    approve(control)
    assert state.get("settings", "tunnel_grant") == identity
    row = state.get("grant", identity)
    row["scope"] = "kakao.read"
    state.put("grant", identity, row)
    assert rpc(private, "events/list")["error"]["message"] == "insufficient_scope"
    assert call(private, "get_pending_messages")["error"]["message"] == "insufficient_scope"
    assert "result" in call(private, "search_messages", q="test")


def test_event_worker_preserves_pending_ack_and_stops_after_revoke(bridge):
    private, public, control, state, _, source, delivered, _ = bridge
    approve(control)
    assert state.all("subscription") == []  # Approval never auto-subscribes.
    assert "result" in rpc(private, "events/subscribe", subscription())
    source.add("after subscription")
    public.app.state.events.tick()
    assert len(delivered) == 1
    pending = call(private, "get_pending_messages")["result"]["structuredContent"]
    assert len(pending["items"]) == 1
    assert "result" in call(
        private,
        "acknowledge_messages",
        through_cursor=pending["next_cursor"],
        cursor_epoch=pending["cursor_epoch"],
    )
    assert call(private, "get_pending_messages")["result"]["structuredContent"]["items"] == []
    approve(control, False)
    source.add("must not deliver")
    public.app.state.events.tick()
    assert len(delivered) == 1
    assert state.all("subscription")[0][1]["stopped_reason"] == "expired_or_revoked"


def test_status_contains_only_metadata_and_wrong_tunnel_cannot_be_approved(bridge):
    _, _, control, _, *_ = bridge
    before = control.get("/connections").json()["tunnel"]
    assert before == {"configured": True, "approved": False, "tunnel_id": TUNNEL, "expires": None}
    assert (
        control.post(
            "/tunnel/decision", json={"tunnel_id": "tunnel_" + "b" * 32, "approve": True}
        ).status_code
        == 409
    )
    approve(control)
    result = control.get("/connections").json()
    assert result["tunnel"]["approved"]
    assert result["grants"] == []
    assert AUTHORIZATION not in json.dumps(result)


@pytest.mark.parametrize("version", ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"])
def test_sidecar_probe_before_approval_and_legacy_tool_calls(bridge, version):
    private, public, control, *_ = bridge
    private.headers["MCP-Protocol-Version"] = version
    # Connector OAuth headers cannot replace local service authentication.
    private.headers["Authorization"] = "Bearer connector-forwarded-token"
    initialized = rpc(private, "initialize", {"protocolVersion": version})["result"]
    assert initialized["protocolVersion"] == version
    assert initialized["capabilities"] == {"tools": {}}
    assert "resultType" not in initialized
    assert len(rpc(private, "tools/list")["result"]["tools"]) == 8
    assert private.get("/mcp").status_code == 405
    for method in ("tools/call", "events/list", "events/subscribe"):
        response = private.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method})
        assert response.status_code == 403
    assert (
        private.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        ).status_code
        == 202
    )
    approve(control)
    assert call(private, "get_profile")["result"]["structuredContent"]["id"]
    del private.headers["X-Bridge-Tunnel-Authorization"]
    assert (
        private.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}).status_code
        == 401
    )
    # The public protocol contract is unchanged.
    _, form = link(public)
    public.headers["Authorization"] = (
        "Bearer " + public.post("/token", data=form).json()["access_token"]
    )
    assert rpc(public, "initialize", {"protocolVersion": version})["error"]["code"] == -32022


def test_official_python_mcp_client_can_initialize_list_and_call(bridge):
    import anyio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    private, _, control, *_ = bridge

    async def connect():
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=private.app),
                headers={"X-Bridge-Tunnel-Authorization": AUTHORIZATION},
            ) as http,
            streamable_http_client("http://private/mcp", http_client=http) as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as session,
        ):
            result = await session.initialize()
            assert result.serverInfo.name == "kakaotalk-bridge"
            assert len((await session.list_tools()).tools) == 8
            approve(control)
            result = await session.call_tool("get_profile", {})
            assert not result.isError
            assert result.structuredContent["id"]

    anyio.run(connect)
