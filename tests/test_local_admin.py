"""Local WebAuthn remains authenticated and cannot widen HTTP access."""

import argparse
import json
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dot_plugin.storage import State
from ops import cli
from server.origins import validate_admin_origin, validate_origin
from server.passkeys import Passkeys
from tests.test_passkeys import Authenticator
from webui.app import create_app

LOCAL = "http://localhost:18789"


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.168.1.2:18789",
        "http://127.0.0.1:18789",
        "http://localhost.evil:18789",
        "http://localhost:80",
        "http://localhost:18789/",
        "http://localhost:99999",
        "http://user@localhost:18789",
        "http://localhost:18789?x=1",
    ],
)
def test_http_exception_only_allows_exact_localhost_origin(origin):
    with pytest.raises(ValueError):
        validate_admin_origin(origin)
    validate_admin_origin(LOCAL)
    with pytest.raises(ValueError):
        validate_origin(LOCAL)


def test_local_registration_session_is_bound_to_origin_and_revocable(tmp_path):
    authority = Passkeys(State(str(tmp_path / "keys.db"), Fernet.generate_key()))
    authority.configure(LOCAL)
    app = create_app(
        "a" * 43,
        auth_mode="passkey",
        passkeys=authority,
        local_origin=LOCAL,
        auth_db=tmp_path / "admin.db",
    )
    with TestClient(app, base_url=LOCAL) as client:
        headers = {"Origin": LOCAL}
        start = client.post(
            "/admin/api/passkeys/register-options",
            headers=headers,
            json={"enrollment": authority.issue_enrollment()},
        ).json()
        key = Authenticator()
        response = client.post(
            "/admin/api/passkeys/register-verify",
            headers=headers,
            json={
                "flow": start["flow"],
                "credential": key.credential(start, origin=LOCAL, rp="localhost", register=True),
            },
        )
        assert response.status_code == 200
        cookie = client.cookies.get("kakao-admin-local-18789")
        assert cookie and app.state.owner.session(cookie)["origin"] == LOCAL
        set_cookie = response.headers.get_list("set-cookie")
        assert all("Secure" not in value and "HttpOnly" in value for value in set_cookie)
        assert client.get("/admin/api/session").status_code == 200
        for host in ("localhost:18790", "other.test:18789"):
            assert client.get("/admin/api/session", headers={"Host": host}).status_code == 401
        # A local cookie cannot be relabelled as a TLS session.
        assert (
            client.get(
                "/admin/api/session",
                headers={
                    "Host": "other.test",
                    "Cookie": "__Secure-kakao-admin-v2=" + cookie,
                },
            ).status_code
            == 401
        )
        for origin in ("http://localhost:18790", "https://other.test", "null"):
            assert (
                client.post(
                    "/admin/api/logout",
                    json={},
                    headers={
                        "Origin": origin,
                        "X-CSRF-Token": response.json()["csrf"],
                        "X-Forwarded-Proto": "http",
                    },
                ).status_code
                == 403
            )
        assert client.post("/admin/api/logout", headers=headers, json={}).status_code == 403
        assert (
            client.post(
                "/admin/api/logout",
                json={},
                headers={
                    **headers,
                    "X-CSRF-Token": response.json()["csrf"],
                },
            ).status_code
            == 200
        )
        assert client.get("/admin/api/session").status_code == 401


def test_http_admin_disabled_without_explicit_configuration(tmp_path):
    app = create_app("a" * 43, auth_mode="local", auth_db=tmp_path / "admin.db")
    with TestClient(app, base_url=LOCAL) as client:
        assert (
            client.post(
                "/admin/api/login", headers={"Origin": LOCAL}, json={"token": "a" * 43}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("public,mode", [("", None), ("https://public.test", "admin")])
def test_setup_keeps_local_passkey_and_automates_public_consent(
    tmp_path, monkeypatch, public, mode
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    (tmp_path / ".env").write_text("DOT_PUBLIC_URL=" + (public or "https://a.invalid") + "\n")
    info = {"configured": True, "registered": True, "admin_origin": LOCAL, "public_origin": ""}

    def compose(*args, **kwargs):
        if args[-1] == "info":
            return json.dumps(info)
        assert args[-1] != "configure", "Do not reset an existing passkey"
        return ""

    execute = Mock(side_effect=compose)
    monkeypatch.setattr(cli, "compose", execute)
    cli.passkey_setup(
        argparse.Namespace(local=True, url=None, public_url=None, enroll=False, link_only=True)
    )
    assert cli.read_env()["ADMIN_LOCAL_ORIGIN"] == LOCAL
    assert cli.read_env().get("DOT_APPROVAL_MODE") == mode
    assert (tmp_path / ".bridge/admin-url").read_text() == LOCAL + "/admin/"
    assert "admin-local" in execute.call_args.args
    assert "openai-tunnel" not in cli.services()
    assert ("dot-ingress" in cli.services()) == bool(public)
