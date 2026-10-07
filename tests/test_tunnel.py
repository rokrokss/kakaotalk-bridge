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
from tests.test_dot_plugin import BASE, Source, call, enable_events, link, rpc, subscription

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


def test_actual_tool_activity_is_separate_from_approval_and_discovery(bridge):
    private, public, control, state, _, source, *_ = bridge
    approve(control)
    for method in ("initialize", "tools/list", "ping"):
        assert "result" in rpc(private, method)
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] is None
    assert state.all("connection_activity") == []
    assert "error" in call(private, "unknown_tool")
    assert state.all("connection_activity") == []
    assert "result" in call(private, "get_collector_status")
    observed = control.get("/connections").json()["tunnel"]["last_tool_at"]
    assert observed > 0
    assert "error" in call(private, "get_collector_status", unexpected="private-value")
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] == observed
    original_get = source.get

    def unavailable(*args, **kwargs):
        raise RuntimeError("private collector error")

    source.get = unavailable
    assert "error" in call(private, "get_collector_status")
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] == observed
    source.get = original_get
    assert list(state.all("connection_activity")[0][1]) == ["last_tool_at"]
    approve(control, False)
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] is None
    approve(control)
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] is None

    _, form = link(public)
    access = public.post("/token", data=form).json()["access_token"]
    public.headers["Authorization"] = "Bearer " + access
    assert control.get("/connections").json()["grants"][0]["last_tool_at"] is None
    assert "result" in call(public, "get_collector_status")
    assert control.get("/connections").json()["grants"][0]["last_tool_at"] > 0
    assert control.get("/connections").json()["tunnel"]["last_tool_at"] is None


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
    assert len(actual) == 10
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


@pytest.mark.parametrize("reason", ["revoke", "expired", "policy", "tunnel_change"])
def test_connection_lifecycle_fails_closed(bridge, reason):
    private, _, control, state, keys, _, _, config = bridge
    approve(control)
    identity = state.get("settings", "tunnel_grant")
    assert "result" in call(private, "get_profile")
    if reason == "revoke":
        approve(control, False)
    elif reason == "expired":
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


def test_permanent_approval_survives_time_cleanup_and_restart(bridge, monkeypatch):
    _, public, control, state, keys, source, delivered, config = bridge
    approve(control)
    enable_events(state, source, "room-a")
    identity = state.get("settings", "tunnel_grant")
    assert state.get("grant", identity)["expires"] is None
    _, form = link(public)
    tokens = public.post("/token", data=form).json()
    public.headers["Authorization"] = "Bearer " + tokens["access_token"]
    oauth_id, oauth_grant = next(
        (key, row) for key, row in state.all("grant") if row.get("transport", "oauth") == "oauth"
    )
    assert time.time() < oauth_grant["expires"] <= time.time() + 30 * 86400
    connections = control.get("/connections").json()
    assert len(connections["grants"]) == 1
    assert connections["tunnel"]["approved"]
    assert connections["tunnel"]["expires"] is None

    future = time.time() + 2 * 365 * 86400
    monkeypatch.setattr(time, "time", lambda: future)
    public.app.state.oauth.cleanup()
    assert state.get("grant", oauth_id) is None
    assert state.get("grant", identity)["expires"] is None
    assert public.post("/mcp", json={}).status_code == 401
    restarted = TestClient(
        tunnel_app(
            config,
            State(config.database, config.storage_key),
            AUTHORIZATION,
            keys,
            collector=source,
            verifier=lambda sub: None,
        )
    )
    restarted.headers["X-Bridge-Tunnel-Authorization"] = AUTHORIZATION
    assert "result" in call(restarted, "get_profile")
    assert "result" in rpc(restarted, "events/subscribe", subscription())
    source.add("after restart")
    public.app.state.events.tick()
    assert len(delivered) == 1
    assert public.app.state.oauth.active_grant(identity)
    approve(control, False)
    assert (
        restarted.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call"}).status_code
        == 403
    )


def test_repeated_approval_keeps_the_grant_and_its_subscriptions(bridge):
    private, _, control, state, *_ = bridge
    approve(control)
    identity = state.get("settings", "tunnel_grant")
    assert "result" in rpc(private, "events/subscribe", subscription())
    subscriptions = state.all("subscription")
    approve(control)
    assert state.get("settings", "tunnel_grant") == identity
    assert state.get("grant", identity)["expires"] is None
    assert state.all("subscription") == subscriptions
    assert control.get("/connections").json()["tunnel"]["expires"] is None


def test_missing_oauth_expiry_never_becomes_permanent(bridge):
    _, public, control, state, *_ = bridge
    _, form = link(public)
    tokens = public.post("/token", data=form).json()
    identity, row = state.all("grant")[0]
    row["expires"] = None
    state.put("grant", identity, row)
    public.headers["Authorization"] = "Bearer " + tokens["access_token"]
    assert public.post("/mcp", json={}).status_code == 401
    assert control.get("/connections").json()["grants"] == []
    public.app.state.oauth.cleanup()
    assert state.get("grant", identity) is None


def test_event_worker_preserves_pending_ack_and_stops_after_revoke(bridge):
    private, public, control, state, _, source, delivered, _ = bridge
    approve(control)
    enable_events(state, source, "room-a")
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


def test_admin_conversation_switch_applies_to_tunnel_events(bridge):
    private, public, control, _state, _, source, delivered, _ = bridge
    approve(control)
    assert "result" in rpc(private, "events/subscribe", subscription())
    source.add("default off")
    public.app.state.events.tick()
    assert delivered == []
    assert (
        control.post(
            "/events/settings",
            json={
                "conversation_ref": "room-a",
                "enabled": True,
                "cursor_epoch": source.epoch,
                "after_cursor": len(source.rows),
            },
        ).status_code
        == 200
    )
    source.add("allowed")
    source.add("blocked", "room-b")
    public.app.state.events.tick()
    assert len(delivered) == 1
    page = call(private, "get_pending_messages")["result"]["structuredContent"]
    assert [r["body"] for r in page["items"]] == ["allowed"]
    assert (
        control.post(
            "/events/settings",
            json={
                "conversation_ref": "room-a",
                "enabled": False,
            },
        ).status_code
        == 200
    )
    assert call(private, "get_pending_messages")["result"]["structuredContent"]["items"] == []
    assert len(call(private, "get_recent_messages")["result"]["structuredContent"]["items"]) == 3


def test_status_contains_only_metadata_and_wrong_tunnel_cannot_be_approved(bridge):
    _, _, control, _, *_ = bridge
    before = control.get("/connections").json()["tunnel"]
    assert before == {
        "configured": True,
        "approved": False,
        "allow_send": False,
        "tunnel_id": TUNNEL,
        "expires": None,
        "last_tool_at": None,
    }
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
def test_sidecar_probe_before_approval_and_tool_calls_on_every_protocol(bridge, version):
    private, public, control, *_ = bridge
    private.headers["MCP-Protocol-Version"] = version
    # Connector OAuth headers cannot replace local service authentication.
    private.headers["Authorization"] = "Bearer connector-forwarded-token"
    initialized = rpc(private, "initialize", {"protocolVersion": version})["result"]
    assert initialized["protocolVersion"] == version
    assert initialized["capabilities"] == {"tools": {}}
    assert "resultType" not in initialized
    assert len(rpc(private, "tools/list")["result"]["tools"]) == 10
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
            assert len((await session.list_tools()).tools) == 10
            approve(control)
            result = await session.call_tool("get_profile", {})
            assert not result.isError
            assert result.structuredContent["id"]

    anyio.run(connect)


def test_send_permission_is_explicit_and_survives_restart(bridge, monkeypatch):
    private, _, control, state, _, source, *_ = bridge
    approve(control)
    calls = []
    monkeypatch.setattr(
        source,
        "outgoing",
        lambda **kwargs: calls.append(kwargs) or {"status": "queued"},
        raising=False,
    )
    args = {
        "request_id": "01234567-1234-1234-1234-123456789012",
        "conversation_ref": "room-a",
        "text": "hello",
    }
    assert call(private, "send_message", **args)["error"]["message"] == "insufficient_scope"
    grant = state.get("settings", "tunnel_grant")
    assert (
        control.post(
            "/tunnel/decision", json={"tunnel_id": TUNNEL, "approve": True, "allow_send": True}
        ).status_code
        == 200
    )
    assert state.get("settings", "tunnel_grant") == grant
    assert (
        call(private, "send_message", **args)["result"]["structuredContent"]["status"] == "queued"
    )
    approve(control)  # Repeated approval does not silently remove existing send consent.
    assert "kakao.send" in state.get("grant", grant)["scope"].split()
    assert (
        control.post(
            "/tunnel/decision", json={"tunnel_id": TUNNEL, "approve": True, "allow_send": False}
        ).status_code
        == 200
    )
    assert call(private, "send_message", **args)["error"]["message"] == "insufficient_scope"
    assert len(calls) == 1


def test_revoked_send_permission_is_not_restored_by_basic_approval(bridge):
    _, _, control, state, *_ = bridge
    response = control.post(
        "/tunnel/decision", json={"tunnel_id": TUNNEL, "approve": True, "allow_send": True}
    )
    assert response.status_code == 200
    approve(control, allow=False)
    approve(control)
    grant = state.get("grant", state.get("settings", "tunnel_grant"))
    assert grant["scope"] == "kakao.read kakao.events"
