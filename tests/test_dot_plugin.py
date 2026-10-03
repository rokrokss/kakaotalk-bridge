import base64
import hashlib
import json
import re
import time
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dot_plugin.app import create_app
from dot_plugin.config import EVENT, SCOPES, Config
from dot_plugin.events import Events
from dot_plugin.network import DeliveryError, signed_headers
from dot_plugin.storage import State

BASE = "https://dot.example.test"
SECRET = "whsec_" + base64.b64encode(b"s" * 32).decode()
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
VERIFIER = "v" * 64


class Source:
    def __init__(self):
        self.rows = []
        self.epoch = "source-epoch"
        self.floor = 0

    def add(self, text="안녕", conversation="room-a", mine=True):
        self.rows.append(
            {
                "id": len(self.rows) + 1,
                "body": text,
                "source": "iris_db",
                "conversation_ref": conversation,
                "received_at": "2026-10-04T01:00:00Z",
                "database_ref": {"is_mine": mine},
            }
        )

    def checkpoint(self):
        return {
            "cursor": len(self.rows),
            "cursor_epoch": self.epoch,
            "pruned_through_cursor": self.floor,
        }

    def messages(self, after, limit=50, conversation_ref=None):
        rows = [
            r
            for r in self.rows
            if r["id"] > after
            and (not conversation_ref or r["conversation_ref"] == conversation_ref)
        ]
        selected = deepcopy(rows[:limit])
        return {
            "items": selected,
            "next_cursor": selected[-1]["id"] if selected else after,
            "has_more": len(rows) > limit,
            "coverage": {"cursor_epoch": self.epoch, "complete": False},
        }

    def get(self, path, **params):
        if path == "/v1/status":
            return {"state": "collecting_partial", "warnings": []}
        if path == "/v1/conversations":
            return {
                "items": [{"conversation_ref": "room-a"}],
                "next_cursor": len(self.rows),
                "has_more": False,
            }
        if path == "/v1/search":
            return {"items": [r for r in self.rows if params["q"] in r["body"]]}
        raise AssertionError(path)


def begin_link(client, method="none"):
    response = client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "Test ChatGPT",
            "token_endpoint_auth_method": method,
        },
    )
    assert response.status_code == 201, response.text
    registration = response.json()
    query = {
        "response_type": "code",
        "client_id": registration["client_id"],
        "redirect_uri": REDIRECT,
        "resource": BASE + "/mcp",
        "scope": SCOPES,
        "state": "state-value",
        "code_challenge_method": "S256",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
        .decode()
        .rstrip("="),
    }
    page = client.get("/authorize", params=query)
    assert page.status_code == 200, page.text
    assert page.headers["referrer-policy"] == "same-origin"
    assert "form-action 'self' https://chatgpt.com;" in page.headers["content-security-policy"]
    ticket = re.search(r'name="ticket" value="([^"]+)"', page.text)[1]
    return registration, ticket


def link(client, method="none"):
    registration, ticket = begin_link(client, method)
    approval = client.post(
        "/authorize",
        data={"ticket": ticket, "link_key": "L" * 43},
        headers={"Origin": BASE},
        follow_redirects=False,
    )
    assert approval.status_code == 303, approval.text
    assert approval.headers["referrer-policy"] == "no-referrer"
    assert "form-action 'self' https://chatgpt.com;" in approval.headers["content-security-policy"]
    redirect = parse_qs(urlsplit(approval.headers["location"]).query)
    assert redirect["iss"] == [BASE] and redirect["state"] == ["state-value"]
    form = {
        "grant_type": "authorization_code",
        "code": redirect["code"][0],
        "redirect_uri": REDIRECT,
        "client_id": registration["client_id"],
        "resource": BASE + "/mcp",
        "code_verifier": VERIFIER,
    }
    return registration, form


@pytest.fixture
def plugin(tmp_path):
    config = Config(BASE, str(tmp_path / "dot.db"), "L" * 43, Fernet.generate_key())
    source = Source()
    source.add("history before subscription")
    verified, delivered = [], []

    def verify(sub):
        verified.append(deepcopy(sub))

    def send(sub, event_id, body):
        headers = signed_headers(sub, event_id, body)
        delivered.append((deepcopy(sub), event_id, json.loads(body), headers))
        return 200, b"{}"

    app = create_app(config, source, verifier=verify, sender=send, worker=False)
    with TestClient(app, base_url=BASE) as client:
        registration, form = link(client)
        tokens = client.post("/token", data=form).json()
        assert "access_token" in tokens, tokens
        client.headers["Authorization"] = "Bearer " + tokens["access_token"]
        yield client, app, source, registration, tokens, verified, delivered, config


def rpc(client, method, params=None):
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    )
    assert response.status_code == 200, response.text
    return response.json()


def call(client, name, **args):
    return rpc(client, "tools/call", {"name": name, "arguments": args})


def subscription(consumer="dot", **args):
    return {
        "name": EVENT,
        "arguments": {"consumer_id": consumer, **args},
        "delivery": {
            "mode": "webhook",
            "url": "https://receiver.example/callback",
            "secret": SECRET,
        },
        "cursor": None,
    }


def test_discovery_401_oauth_metadata_and_complete_results(plugin):
    client, app, *_ = plugin
    with TestClient(app, base_url=BASE) as anonymous:
        response = anonymous.get("/mcp")
        assert response.status_code == 401
        assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]
        assert anonymous.post("/mcp", json={}).status_code == 401
        assert anonymous.get("/.well-known/openid-configuration").status_code == 404
        assert anonymous.get("/.well-known/oauth-authorization-server").json()[
            "code_challenge_methods_supported"
        ] == ["S256"]
    assert client.get("/mcp").status_code == 405
    discovery = rpc(client, "server/discover")["result"]
    assert discovery["resultType"] == "complete"
    assert discovery["supportedVersions"] == ["2026-07-28"]
    assert discovery["capabilities"]["events"] == {}
    tools = rpc(client, "tools/list")["result"]["tools"]
    assert len(tools) == 7
    assert not any("send" in t["name"] for t in tools)
    assert next(t for t in tools if t["name"] == "get_profile")["_meta"]["openai/profile"] is True
    assert rpc(client, "events/list")["result"]["events"][0]["name"] == EVENT
    assert "error" in rpc(client, "initialize")
    assert "error" in call(client, "get_recent_messages", limit=True)
    assert "error" in call(client, "get_recent_messages", arbitrary_command="private")


@pytest.mark.parametrize(
    "redirect",
    ["https://ok.example;script-src.unsafe-inline/cb", "https://ok.example/\ncb", "https://ok.example:abc/cb"],
)
def test_dcr_rejects_redirects_that_cannot_form_safe_csp_sources(plugin, redirect):
    client, *_ = plugin
    assert client.post("/register", json={"redirect_uris": [redirect]}).status_code == 400


@pytest.mark.parametrize("origin", [None, "null", "https://foreign.example", BASE + ".evil.example"])
def test_approval_requires_exact_origin_even_with_valid_ticket_cookie_and_key(plugin, origin):
    client, *_ = plugin
    _, ticket = begin_link(client)
    data = {"ticket": ticket, "link_key": "L" * 43}
    headers = {"Referer": BASE + "/authorize"}
    if origin is not None:
        headers["Origin"] = origin
    denied = client.post("/authorize", data=data, headers=headers, follow_redirects=False)
    assert denied.status_code == 403
    assert denied.json() == {"error": "invalid_origin"}
    assert denied.headers["referrer-policy"] == "no-referrer"
    # Rejection must not consume the valid browser-bound approval.
    approved = client.post(
        "/authorize", data=data, headers={"Origin": BASE}, follow_redirects=False
    )
    assert approved.status_code == 303


def test_non_approval_responses_do_not_send_referrers(plugin):
    client, *_ = plugin
    for path in ["/", "/health/live", "/.well-known/oauth-authorization-server", "/authorize"]:
        assert client.get(path).headers["referrer-policy"] == "no-referrer"


def test_signal_then_read_ack_and_restart_without_payload(plugin):
    client, app, source, _, _, verified, delivered, config = plugin
    first = rpc(client, "events/subscribe", subscription())["result"]
    second = rpc(client, "events/subscribe", subscription())["result"]
    assert first["id"] == second["id"] and len(verified) == 1
    assert not call(client, "get_pending_messages")["result"]["structuredContent"]["items"]
    source.add("안녕 · actual new message")
    app.state.events.tick()
    assert len(delivered) == 1
    event = delivered[0][2]
    assert event["name"] == EVENT and event["cursor"] is None
    assert "actual new message" not in json.dumps(event)
    pending = call(client, "get_pending_messages")["result"]["structuredContent"]
    assert pending["items"][0]["body"] == "안녕 · actual new message"
    # Reading doesn't acknowledge: a dot can recover after a failed run.
    assert call(client, "get_pending_messages")["result"]["structuredContent"] == pending
    assert "error" in call(
        client, "acknowledge_messages", through_cursor=99, cursor_epoch=source.epoch
    )
    ack = call(
        client,
        "acknowledge_messages",
        through_cursor=pending["next_cursor"],
        cursor_epoch=pending["cursor_epoch"],
    )
    assert ack["result"]["structuredContent"]["acknowledged_cursor"] == 2
    assert not call(client, "get_pending_messages")["result"]["structuredContent"]["items"]
    restarted = create_app(
        config, source, verifier=lambda _: None, sender=app.state.events.deliver, worker=False
    )
    with TestClient(restarted, base_url=BASE, headers=dict(client.headers)) as again:
        assert not call(again, "get_pending_messages")["result"]["structuredContent"]["items"]
        assert (
            call(again, "get_profile")["result"]["structuredContent"]
            == call(client, "get_profile")["result"]["structuredContent"]
        )
        restarted.state.events.tick()
        assert len(delivered) == 1


def test_consumers_filters_pagination_and_empty_filtered_pages(plugin):
    client, app, source, *rest = plugin
    assert "result" in rpc(
        client,
        "events/subscribe",
        subscription("work", conversation_ref="room-b", include_mine=False),
    )
    assert "result" in rpc(client, "events/subscribe", subscription("personal"))
    assert "error" in rpc(
        client, "events/subscribe", subscription("work", conversation_ref="room-a")
    )
    source.add("mine", "room-b", True)
    source.add("other room", "room-a", False)
    source.add("match", "room-b", False)
    page = call(client, "get_pending_messages", consumer_id="work", limit=2)["result"][
        "structuredContent"
    ]
    assert page["items"] == [] and page["has_more"] and page["next_cursor"] == 3
    call(
        client,
        "acknowledge_messages",
        consumer_id="work",
        through_cursor=3,
        cursor_epoch=source.epoch,
    )
    page = call(client, "get_pending_messages", consumer_id="work")["result"]["structuredContent"]
    assert [r["body"] for r in page["items"]] == ["match"]
    assert (
        len(
            call(client, "get_pending_messages", consumer_id="personal")["result"][
                "structuredContent"
            ]["items"]
        )
        == 3
    )
    app.state.events.tick()
    assert len(rest[-2]) == 4  # 1 filtered delivery + 3 personal deliveries


@pytest.mark.parametrize("ttl", [1, 5000, None, 999999999])
def test_ttl_never_exceeds_requested_lifetime(plugin, ttl):
    client, app, *_ = plugin
    params = subscription()
    params["ttlMs"] = ttl
    before = time.time()
    reply = rpc(client, "events/subscribe", params)["result"]
    sub = app.state.store.get("subscription", reply["id"])
    bound = min(ttl if ttl is not None else 86400000, 86400000) / 1000
    assert sub["expires"] <= time.time() + bound
    assert sub["expires"] >= before
    assert reply["refreshBefore"] is not None


def test_rotation_retry_persistence_and_unsubscribe_during_delivery(plugin):
    client, app, source, _, _, _, _delivered, config = plugin
    params = subscription()
    key = rpc(client, "events/subscribe", params)["result"]["id"]
    source.add()
    app.state.events.deliver = lambda *args: (503, b"unavailable")
    app.state.events.tick()
    queued = app.state.store.all("delivery")
    assert len(queued) == 1 and queued[0][1]["attempts"] == 1
    event_id = queued[0][1]["event"]["eventId"]
    params["delivery"]["secret"] = "whsec_" + base64.b64encode(b"n" * 32).decode()
    rpc(client, "events/subscribe", params)
    sub = app.state.store.get("subscription", key)
    assert sub["previous_secret"] == SECRET
    headers = signed_headers(sub, event_id, b"{}")
    assert len(headers["webhook-signature"].split()) == 2
    item_id, item = queued[0]
    item["next_attempt"] = 0
    app.state.store.put("delivery", item_id, item)
    state = State(config.database, config.storage_key)

    def sender(sub, received_id, body):
        assert received_id == event_id
        # Unsubscribe must not wait on outbound HTTP, and the completed POST must
        # not resurrect a deleted queue item or subscription.
        principal = app.state.oauth.principal(client.headers["authorization"])
        app.state.events.unsubscribe(params, principal)
        return 200, b"{}"

    again = Events(state, app.state.oauth, source, deliver=sender)
    again.tick()
    assert not state.get("subscription", key)["active"]
    assert state.all("delivery") == []
    assert "result" in rpc(client, "events/unsubscribe", params)


@pytest.mark.parametrize("status", [410, 413, 400, 301])
def test_terminal_delivery_responses_are_not_retried(plugin, status):
    client, app, source, *_ = plugin
    key = rpc(client, "events/subscribe", subscription())["result"]["id"]
    source.add()
    sent = []
    app.state.events.deliver = lambda *args: (sent.append(True) or status, b"")
    app.state.events.tick()
    app.state.events.tick()
    assert len(sent) == 1 and app.state.store.all("delivery") == []
    sub = app.state.store.get("subscription", key)
    assert sub["failed"] == 1
    assert sub["active"] == (status != 410)


def test_failed_callback_does_not_create_subscription(plugin):
    client, app, *_ = plugin

    def broken(_):
        raise DeliveryError("challenge_failed")

    app.state.events.verify = broken
    result = rpc(client, "events/subscribe", subscription())
    assert result["error"]["code"] == -32015
    assert result["error"]["data"]["reason"] == "challenge_failed"
    assert app.state.store.all("subscription") == []


def test_refresh_rotation_reuse_revokes_grant_and_stops_delivery(plugin):
    client, app, source, registration, tokens, _, delivered, _ = plugin
    rpc(client, "events/subscribe", subscription())
    form = {
        "grant_type": "refresh_token",
        "client_id": registration["client_id"],
        "refresh_token": tokens["refresh_token"],
        "resource": BASE + "/mcp",
    }
    refreshed = client.post("/token", data=form, headers={"Authorization": ""})
    assert refreshed.status_code == 200, refreshed.text
    new = refreshed.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert client.post("/token", data=form, headers={"Authorization": ""}).status_code == 400
    client.headers["Authorization"] = "Bearer " + new["access_token"]
    assert client.get("/mcp").status_code == 401
    source.add()
    app.state.events.tick()
    assert delivered == []


def test_resource_pkce_and_client_secret_are_enforced(plugin):
    _client, app, *_ = plugin
    with TestClient(app, base_url=BASE) as other:
        registration, form = link(other, "client_secret_post")
        assert other.post("/token", data=form).status_code == 401
        form["client_secret"] = registration["client_secret"]
        assert (
            other.post("/token", data={**form, "resource": "https://other.example/mcp"}).status_code
            == 400
        )
        assert other.post("/token", data={**form, "code_verifier": "wrong" * 10}).status_code == 400
        # A failed exchange consumes the one-time code.
        assert other.post("/token", data=form).status_code == 400
        registration, form = link(other, "client_secret_post")
        response = other.post(
            "/token", data={**form, "client_secret": registration["client_secret"]}
        )
        assert response.status_code == 200
        assert (
            other.post(
                "/token", data={**form, "client_secret": registration["client_secret"]}
            ).status_code
            == 400
        )


def test_revoke_scope_expiry_and_source_reset_stop_events(plugin):
    client, app, source, registration, tokens, _, delivered, _ = plugin
    key = rpc(client, "events/subscribe", subscription())["result"]["id"]
    source.epoch = "restored-database"
    source.add()
    app.state.events.tick()
    assert not app.state.store.get("subscription", key)["active"]
    assert "error" in call(client, "get_pending_messages")
    assert delivered == []
    response = client.post(
        "/revoke",
        data={"client_id": registration["client_id"], "token": tokens["access_token"]},
        headers={"Authorization": ""},
    )
    assert response.status_code == 200
    assert client.get("/mcp").status_code == 401


def test_approval_csrf_encrypted_state_and_private_logs(plugin, capsys):
    client, app, source, _registration, tokens, _, _, config = plugin
    assert (
        client.post(
            "/authorize",
            data={"ticket": "missing", "link_key": config.link_key},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    rpc(client, "events/subscribe", subscription())
    source.add("private text must never reach logs")
    app.state.events.tick()
    call(client, "get_pending_messages")
    call(client, "search_messages", q="private text must never reach logs")
    log = capsys.readouterr().out
    assert "private text" not in log and tokens["access_token"] not in log and SECRET not in log
    from pathlib import Path

    data = Path(config.database).read_bytes()
    for secret in (
        tokens["access_token"],
        tokens["refresh_token"],
        SECRET,
        "https://receiver.example/callback",
    ):
        assert secret.encode() not in data


def test_expiration_and_short_ttl_do_not_send(plugin):
    client, app, source, _, _, _, delivered, _ = plugin
    key = rpc(client, "events/subscribe", subscription())["result"]["id"]
    sub = app.state.store.get("subscription", key)
    sub["expires"] = time.time() - 1
    app.state.store.put("subscription", key, sub)
    source.add()
    app.state.events.tick()
    assert delivered == []
    assert not app.state.store.get("subscription", key)["active"]


def test_retention_gap_is_explicit_and_ack_can_advance(plugin):
    client, _app, source, *_ = plugin
    rpc(client, "events/subscribe", subscription())
    source.add("pruned")
    source.add("retained")
    source.floor = 2
    pending = call(client, "get_pending_messages")["result"]["structuredContent"]
    assert pending["truncated"] and [r["body"] for r in pending["items"]] == ["retained"]
    assert "result" in call(
        client, "acknowledge_messages", through_cursor=3, cursor_epoch=source.epoch
    )


def test_events_scope_alone_cannot_read_messages_and_profile_is_stable(plugin):
    client, app, *_ = plugin
    principal = app.state.oauth.principal(client.headers["authorization"])
    grant = app.state.store.get("grant", principal["grant_id"])
    grant["scope"] = "kakao.events"
    app.state.store.put("grant", principal["grant_id"], grant)
    assert call(client, "get_pending_messages")["error"]["message"] == "insufficient_scope"
    assert call(client, "get_recent_messages")["error"]["message"] == "insufficient_scope"


def test_cimd_is_verified_and_failed_fetch_does_not_allow_redirect_wildcards(plugin, monkeypatch):
    _client, app, *_ = plugin
    from dot_plugin import network

    url = "https://chatgpt.com/oauth/client.json"
    document = {
        "client_id": url,
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "private_key_jwt",
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
    }
    monkeypatch.setattr(
        network, "public_request", lambda target: (200, json.dumps(document).encode())
    )
    assert app.state.oauth.client(url)["redirect_uris"] == [REDIRECT]
    app.state.store.delete("client", url)
    monkeypatch.setattr(network, "public_request", lambda target: (403, b"blocked"))
    from dot_plugin.auth import AuthError

    with pytest.raises(AuthError):
        app.state.oauth.client(url)
