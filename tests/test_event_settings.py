"""Conversation gating through the real private control, admin and event paths."""

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from dot_plugin.control import create_app as control_app
from dot_plugin.event_policy import KIND, allows
from dot_plugin.storage import State
from tests.test_dot_plugin import call, rpc, subscription
from tests.test_dot_plugin import plugin as plugin_fixture
from tests.test_webui import ORIGIN, TOKEN, signin
from webui.app import create_app

CONTROL = "control-" + "c" * 40
plugin = plugin_fixture


@pytest.fixture
def settings(plugin):
    client, app, source, *_, config = plugin
    state = app.state.store
    for key, _ in state.all(KIND):
        state.delete(KIND, key)
    # A separate State instance matches the control and worker processes in Docker.
    private = TestClient(control_app(config, State(config.database, config.storage_key), CONTROL))
    private.headers["Authorization"] = "Bearer " + CONTROL
    return client, app, source, state, private


def set_room(control, source, ref, enabled):
    checkpoint = source.checkpoint()
    body = {"conversation_ref": ref, "enabled": enabled}
    if enabled:
        body.update(cursor_epoch=checkpoint["cursor_epoch"], after_cursor=checkpoint["cursor"])
    response = control.post("/events/settings", json=body)
    assert response.status_code == 200, response.text


def test_default_off_does_not_subscribe_or_limit_normal_queries(settings):
    client, app, source, state, control = settings
    assert control.get("/events/settings").json() == {"conversations": {}, "subscriptions": []}
    assert "result" in rpc(client, "events/subscribe", subscription())
    source.add("disabled message")
    app.state.events.tick()
    assert state.all("delivery") == []
    assert state.all("subscription")[0][1]["delivered"] == 0
    pending = call(client, "get_pending_messages")["result"]["structuredContent"]
    assert pending["items"] == [] and pending["next_cursor"] == 2
    assert (
        len(call(client, "search_messages", q="disabled")["result"]["structuredContent"]["items"])
        == 1
    )
    set_room(control, source, "room-a", True)
    assert len(state.all("subscription")) == 1


def test_enable_off_retry_cancel_and_reenable_skip_disabled_history(settings):
    client, app, source, state, control = settings
    rpc(client, "events/subscribe", subscription())
    source.add("before enabling")
    set_room(control, source, "room-a", True)
    source.add("enabled")
    source.add("other room", "room-b")
    app.state.events.deliver = Mock(return_value=(503, b"retry"))
    app.state.events.tick()
    assert app.state.events.deliver.call_count == 1
    assert len(state.all("delivery")) == 1
    assert [
        r["body"]
        for r in call(client, "get_pending_messages")["result"]["structuredContent"]["items"]
    ] == ["enabled"]
    set_room(control, source, "room-a", False)
    assert state.all("delivery") == []
    assert call(client, "get_pending_messages")["result"]["structuredContent"]["items"] == []
    source.add("while disabled")
    set_room(control, source, "room-a", True)
    source.add("after reenable")
    # A repeated On request keeps the original activation boundary.
    set_room(control, source, "room-a", True)
    app.state.events.deliver = Mock(return_value=(200, b"ok"))
    app.state.events.tick()
    assert app.state.events.deliver.call_count == 1
    event = json.loads(app.state.events.deliver.call_args.args[2])
    assert event["data"]["message_id"] == len(source.rows)
    pending = call(client, "get_pending_messages")["result"]["structuredContent"]
    assert [r["body"] for r in pending["items"]] == ["after reenable"]


def test_disable_between_scan_and_send_and_persistence(settings):
    client, app, source, state, control = settings
    rpc(client, "events/subscribe", subscription())
    set_room(control, source, "room-a", True)
    source.add("queued")
    app.state.events._scan()
    saved = state.all("delivery")[0]
    set_room(control, source, "room-a", False)
    # Simulate a stale queue row from an older worker: delivery checks policy again.
    state.put("delivery", *saved)
    app.state.events.deliver = Mock(return_value=(200, b"ok"))
    app.state.events._deliver_pending()
    app.state.events.deliver.assert_not_called()
    assert state.all("delivery") == []
    restarted = State(state.path, app.state.oauth.config.storage_key)
    assert not allows(restarted, "room-a", source.epoch, 999)
    set_room(control, source, "room-a", True)
    assert allows(restarted, "room-a", source.epoch, 999)
    assert not allows(restarted, "room-a", "restored-epoch", 999)


def test_conversation_policy_intersects_client_filters(settings):
    client, app, source, _state, control = settings
    set_room(control, source, "room-a", True)
    set_room(control, source, "room-b", True)
    rpc(client, "events/subscribe", subscription(conversation_ref="room-b", include_mine=False))
    source.add("a", "room-a", False)
    source.add("self", "room-b", True)
    source.add("b", "room-b", False)
    app.state.events.deliver = Mock(return_value=(200, b"ok"))
    app.state.events.tick()
    assert app.state.events.deliver.call_count == 1
    assert [
        r["body"]
        for r in call(client, "get_pending_messages")["result"]["structuredContent"]["items"]
    ] == ["b"]


def test_policy_private_auth_validation_and_no_public_route(settings):
    client, _app, _source, state, control = settings
    assert client.get("/events/settings").status_code == 404
    assert client.post("/events/settings", json={}).status_code == 404
    for token in ("", "Bearer wrong"):
        assert control.get("/events/settings", headers={"Authorization": token}).status_code == 401
        assert (
            control.post("/events/settings", json={}, headers={"Authorization": token}).status_code
            == 401
        )
    for body in (
        {"conversation_ref": "room-a", "enabled": True},
        {"conversation_ref": "room-a", "enabled": "false"},
        {"conversation_ref": "", "enabled": False},
        {"conversation_ref": "room-a", "enabled": False, "url": "https://arbitrary"},
    ):
        assert control.post("/events/settings", json=body).status_code == 422
    assert state.all(KIND) == []


def test_admin_selector_auth_csrf_metadata_pagination_and_checkpoint(settings):
    client, _app, source, state, control = settings
    source.add("body must not be in admin response")
    event_source = Mock()
    event_source.checkpoint.side_effect = source.checkpoint
    event_source.conversations.return_value = {
        "items": [
            {
                "ref": "room-a",
                "name": "<img onerror=alert(1)>",
                "kind": "DirectChat",
                "body": "private",
            }
        ],
        "next_cursor": "opaque-page",
        "has_more": True,
    }
    connections = Mock()

    def connection_call(method, path, data=None):
        response = control.request(method, path, json=data)
        assert response.status_code == 200, response.text
        return response.json()

    connections.call.side_effect = connection_call
    web = create_app(
        TOKEN, Mock(), dict, auth_mode="local", connections=connections, event_source=event_source
    )
    with TestClient(web, base_url=ORIGIN) as admin:
        path = "/admin/api/events/conversations"
        assert admin.get(path).status_code == 401
        headers = signin(admin)
        body = {"conversation_ref": "room-a", "enabled": True}
        assert admin.post(path, json=body).status_code == 403
        assert admin.post(path, json=body, headers={"Origin": ORIGIN}).status_code == 403
        assert (
            admin.post(
                path, json=body, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            admin.post(path, json={**body, "after_cursor": 0}, headers=headers).status_code == 422
        )
        response = admin.get(path, params={"q": "Alice", "cursor": "page-two"}).json()
        event_source.conversations.assert_called_once_with(q="Alice", cursor="page-two")
        assert response["next_cursor"] == "opaque-page" and response["has_more"]
        assert response["items"][0]["enabled"] is False
        assert response["items"][0]["subscriptions"] == 0
        assert "private" not in json.dumps(response)
        assert admin.post(path, json=body, headers=headers).status_code == 200
        assert state.get(KIND, "room-a")["after_cursor"] == len(source.rows)
        assert state.all("subscription") == []
        rpc(client, "events/subscribe", subscription())
        response = admin.get(path).json()["items"][0]
        assert response["enabled"] and response["subscriptions"] == 1
        event_source.checkpoint.side_effect = RuntimeError("unavailable")
        assert admin.post(path, json=body, headers=headers).status_code == 503
        assert admin.post(path, json={**body, "enabled": False}, headers=headers).status_code == 200
        assert not state.get(KIND, "room-a")["enabled"]
