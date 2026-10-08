import io
import json
import struct
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from webui import device
from webui.app import COOKIE, create_app
from webui.auth import digest

TOKEN = "test-admin-" + "a" * 64
ORIGIN = "https://testserver"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1200, 1920)


@pytest.fixture
def console():
    android = Mock()
    android.screenshot.return_value = (PNG, 1200, 1920)
    android.session_status.side_effect = lambda: {
        "checked_at": time.time(),
        "phone": {"automatic": False},
    }
    app = create_app(
        TOKEN, android, lambda: {"state": "needs_attention", "warnings": []}, auth_mode="local"
    )
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, android


def signin(client):
    response = client.post("/admin/api/login", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf"]}


def test_automatic_setup_poll_does_not_dump_the_interactive_screen(console):
    client, android = console
    android.setup_status.return_value = {"state": "needs_setup", "enrolled": False}
    response = client.post("/admin/api/action", json={"name": "setup-poll"}, headers=signin(client))
    assert response.status_code == 202
    for _ in range(100):
        if client.app.state.job["state"] != "running":
            break
        time.sleep(0.01)
    assert client.app.state.job["state"] == "done"
    android.setup_status.assert_called_once()
    android.session_status.assert_not_called()
    assert client.get("/admin/api/screen").status_code == 200


def test_admin_session_security_and_read_token_is_not_admin(console):
    client, android = console
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/api/screen").status_code == 401
    assert (
        client.post(
            "/admin/api/login", json={"token": "r" * 64}, headers={"Origin": ORIGIN}
        ).status_code
        == 401
    )
    headers = signin(client)
    cookie = client.cookies.get(COOKIE)
    assert cookie and cookie != TOKEN
    assert client.get("/admin/api/session").json()["csrf"] == headers["X-CSRF-Token"]
    response = client.post("/admin/api/logout", json={}, headers=headers)
    assert response.status_code == 200
    assert client.get("/admin/api/screen").status_code == 401
    android.screenshot.assert_not_called()


def test_cookie_is_admin_scoped_and_old_sessions_cannot_be_renamed(console):
    client, _ = console
    signin(client)
    key = client.cookies.get(COOKIE)
    assert COOKIE in client.build_request("GET", "/admin/api/session").headers["cookie"]
    for path in ("/authorize", "/mcp", "/admin-evil"):
        assert COOKIE not in client.build_request("GET", path).headers.get("cookie", "")
    owner = client.app.state.owner
    record = owner.state.get("session", digest(key))
    del record["cookie_scope"]
    owner.state.put("session", digest(key), record)
    assert client.get("/admin/api/session").status_code == 401


def test_cross_origin_csrf_and_arbitrary_keys_are_rejected(console):
    client, android = console
    headers = signin(client)
    assert client.post("/admin/api/key", json={"name": "home"}).status_code == 403
    assert (
        client.post("/admin/api/key", json={"name": "home"}, headers={"Origin": ORIGIN}).status_code
        == 403
    )
    assert (
        client.post(
            "/admin/api/key",
            json={"name": "home"},
            headers={**headers, "Origin": "https://attacker.test"},
        ).status_code
        == 403
    )
    assert (
        client.post("/admin/api/key", json={"name": "home; rm -rf /"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/admin/api/key",
            json={"name": "home"},
            headers=[(b"origin", ORIGIN.encode()), (b"x-csrf-token", b"\xff")],
        ).status_code
        == 403
    )
    android.key.assert_not_called()
    assert client.post("/admin/api/key", json={"name": "back"}, headers=headers).status_code == 200
    android.key.assert_called_once_with("back")


def test_screenshot_and_coordinate_mapping_bounds(console):
    client, android = console
    headers = signin(client)
    shot = client.get("/admin/api/screen")
    assert shot.content == PNG
    assert shot.headers["cache-control"] == "no-store"
    assert shot.headers["x-frame-options"] == "DENY"
    assert shot.headers["x-screen-width"] == "1200"
    frame = shot.headers["x-frame-id"]
    assert (
        client.post(
            "/admin/api/pointer", json={"frame": frame, "x": 1199, "y": 1919}, headers=headers
        ).status_code
        == 200
    )
    android.tap.assert_called_once_with(1199, 1919)
    assert (
        client.post(
            "/admin/api/pointer", json={"frame": frame, "x": 1200, "y": 2}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/admin/api/pointer", json={"frame": "0" * 32, "x": 1, "y": 2}, headers=headers
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/admin/api/pointer", json={"frame": frame, "x": True, "y": 2}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/admin/api/pointer",
            json={"frame": frame, "x": 10, "y": 20, "end_x": 30, "end_y": 40, "duration": 500},
            headers=headers,
        ).status_code
        == 200
    )
    android.swipe.assert_called_once_with(10, 20, 30, 40, 500)
    session = next(iter(client.app.state.sessions.values()))
    session["frames"][frame] = (1200, 1920, time.monotonic() - 11)
    assert (
        client.post(
            "/admin/api/pointer", json={"frame": frame, "x": 1, "y": 2}, headers=headers
        ).status_code
        == 409
    )


def test_approval_requires_the_phone_check(console):
    client, android = console
    headers = signin(client)
    assert (
        client.post("/admin/api/action", json={"name": "approve"}, headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/admin/api/action", json={"name": "approve", "tablet_active": True}, headers=headers
        ).status_code
        == 422
    )
    android.approve.assert_not_called()
    response = client.post(
        "/admin/api/action", json={"name": "approve", "phone_active": True}, headers=headers
    )
    assert response.status_code == 202
    result = wait_job(client)
    assert result["job"]["state"] == "done"
    android.approve.assert_called_once_with(True)
    android.session_status.assert_called()


def test_long_job_blocks_device_controls_and_sanitizes_failures(console):
    client, android = console
    headers = signin(client)
    release = threading.Event()

    def fail():
        release.wait(3)
        raise RuntimeError("secret password or account content")

    android.bootstrap.side_effect = fail
    try:
        assert (
            client.post(
                "/admin/api/action", json={"name": "bootstrap"}, headers=headers
            ).status_code
            == 202
        )
        assert (
            client.post("/admin/api/key", json={"name": "home"}, headers=headers).status_code == 409
        )
        assert (
            client.post(
                "/admin/api/action", json={"name": "open-kakao"}, headers=headers
            ).status_code
            == 409
        )
    finally:
        release.set()
    for _ in range(100):
        response = client.get("/admin/api/state")
        if response.json()["job"]["state"] != "running":
            break
        time.sleep(0.01)
    assert response.json()["job"]["state"] == "failed"
    assert "secret password" not in response.text


@pytest.mark.parametrize(
    ("state", "bridge", "needed"),
    [
        ("collecting_partial", {"notification_reply_ready": False}, True),
        ("collecting_partial", {"notification_reply_ready": None}, False),
        ("collecting_partial", None, False),
        # A stale or disconnected collector reports its last check; the gate fails earlier.
        ("needs_attention", {"notification_reply_ready": False}, False),
    ],
)
def test_collector_status_flags_sending_before_first_notification(
    monkeypatch, state, bridge, needed
):
    from webui import app as webui

    status = {
        "state": state,
        "warnings": [],
        "coverage": {},
        "last_observation_received_at": None,
        "bridge": bridge,
    }
    monkeypatch.setattr(webui, "secret", lambda name: "read-token")
    monkeypatch.setattr(
        webui, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(status).encode())
    )
    result = webui.collector_status()
    assert result["send_needs_notification"] is needed
    assert "bridge" not in result


def test_text_not_echoed_even_on_failure_and_request_size_bounded(console):
    client, android = console
    headers = signin(client)
    typed = "한글 암호 '$() ; 😀"
    response = client.post("/admin/api/text", json={"text": typed}, headers=headers)
    assert response.json() == {"ok": True}
    android.text.assert_called_once_with(typed)
    android.text.side_effect = RuntimeError(typed)
    response = client.post("/admin/api/text", json={"text": typed}, headers=headers)
    assert response.status_code == 503 and typed not in response.text
    assert (
        client.post("/admin/api/text", json={"text": "s" * 40000}, headers=headers).status_code
        == 413
    )
    response = client.post(
        "/admin/api/text", json={"text": typed, "command": "secret"}, headers=headers
    )
    assert (
        response.status_code == 422 and "secret" not in response.text and typed not in response.text
    )


def test_session_expiry_and_new_login_invalidate_old_cookie(console):
    client, android = console
    signin(client)
    old = client.cookies.get(COOKIE)
    signin(client)
    assert old not in client.app.state.sessions
    current = next(iter(client.app.state.sessions.values()))
    current["expires"] = time.monotonic() - 1
    assert client.get("/admin/api/screen").status_code == 401
    android.screenshot.assert_not_called()


def test_login_rate_limit_and_secure_cookie(console):
    client, _android = console
    response = client.post("/admin/api/login", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    cookie = response.headers["set-cookie"].lower()
    assert all(part in cookie for part in ["secure", "httponly", "samesite=strict", "path=/"])
    for _ in range(5):
        assert (
            client.post(
                "/admin/api/login", json={"token": "wrong" * 10}, headers={"Origin": ORIGIN}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/admin/api/login", json={"token": TOKEN}, headers={"Origin": ORIGIN}
        ).status_code
        == 429
    )


def test_unicode_input_uses_private_file_and_cleans_it(monkeypatch):
    calls, uploaded = [], {}
    text = "password'; $(injection) 한글 😀"

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:4] == ("shell", "settings", "get", "secure"):
            return device.IME
        if args[:4] == ("shell", "pm", "list", "packages"):
            return "package:dev.kakaocollector.bridge uid:10123"
        if args[0] == "push":
            path = Path(args[1])
            assert path.stat().st_mode & 0o777 == 0o600
            uploaded.update(json.loads(path.read_text()))
        if args[:2] == ("shell", "cat"):
            return json.dumps({"nonce": uploaded["nonce"], "committed": True})
        return ""

    monkeypatch.setattr(device.cli, "adb", adb)
    device.Android().text(text)
    assert uploaded["text"] == text
    assert all(text not in " ".join(args) for args in calls)
    assert calls[-1][:4] == ("shell", "rm", "-f", next(c[2] for c in calls if c[0] == "push"))
    assert not Path(next(c[1] for c in calls if c[0] == "push")).exists()


def wait_job(client):
    for _ in range(100):
        result = client.get("/admin/api/state").json()
        if result["job"]["state"] != "running":
            return result
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_approval_failure_explains_the_reason_without_leaking_content(console):
    client, android = console
    headers = signin(client)
    android.approve.side_effect = RuntimeError("kakao_login_required")
    client.post("/admin/api/action", json={"name": "approve", "phone_active": True}, headers=headers)
    result = wait_job(client)
    assert result["job"]["state"] == "failed"
    assert "아직 로그인되지 않았습니다" in result["job"]["message"]
    android.approve.side_effect = RuntimeError("private account and UI contents 비밀 계정")
    client.post("/admin/api/action", json={"name": "approve", "phone_active": True}, headers=headers)
    result = wait_job(client)
    assert result["job"]["state"] == "failed"
    assert "private account" not in json.dumps(result) and "비밀" not in json.dumps(result)
    android.bootstrap.assert_not_called()


def test_session_inspection_is_authenticated_and_invalidates_after_input(console):
    client, android = console
    assert client.get("/admin/api/state").status_code == 401
    headers = signin(client)
    assert client.get("/admin/api/state").json()["sessions_stale"] is True
    assert (
        client.post(
            "/admin/api/action", json={"name": "session-check"}, headers=headers
        ).status_code
        == 202
    )
    result = wait_job(client)
    assert result["sessions_stale"] is False
    assert result["sessions"]["phone"]["automatic"] is False
    android.session_status.assert_called_once()
    client.post("/admin/api/key", json={"name": "home"}, headers=headers)
    assert client.get("/admin/api/state").json()["sessions_stale"] is True
    android.session_status.side_effect = lambda: {"checked_at": time.time() - 61}
    client.post("/admin/api/action", json={"name": "session-check"}, headers=headers)
    assert wait_job(client)["sessions_stale"] is True


def test_phone_reporting_requires_csrf_and_direct_confirmation(console):
    client, android = console
    headers = signin(client)
    assert client.post("/admin/api/action", json={"name": "phone-lost"}).status_code == 403
    assert (
        client.post("/admin/api/action", json={"name": "phone-active"}, headers=headers).status_code
        == 422
    )
    android.record_phone.assert_not_called()
    for name, active in [("phone-active", True), ("phone-lost", False)]:
        assert (
            client.post(
                "/admin/api/action", json={"name": name, "phone_active": active}, headers=headers
            ).status_code
            == 202
        )
        assert wait_job(client)["job"]["state"] == "done"
        android.record_phone.assert_called_with(active)
    android.record_phone.side_effect = RuntimeError("private-account-and-secret")
    client.post("/admin/api/action", json={"name": "phone-lost"}, headers=headers)
    result = wait_job(client)
    assert result["job"]["state"] == "failed"
    assert result["sessions_stale"] is True
    assert "private-account" not in json.dumps(result)
