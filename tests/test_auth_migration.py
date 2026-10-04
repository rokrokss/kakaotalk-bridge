import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dot_plugin.app import create_app as public_app
from dot_plugin.auth import OAuth
from dot_plugin.config import Config
from dot_plugin.storage import State
from server.auth_migration import retire_social_login
from tests.test_dot_plugin import Source
from tests.test_passkeys import ADMIN, PUBLIC, assertion, authority, enroll  # noqa: F401
from webui.app import COOKIE, create_app
from webui.auth import OwnerAuth


def test_retirement_is_idempotent_and_preserves_other_policies(tmp_path):
    state = State(str(tmp_path / "state.db"), Fernet.generate_key())
    kinds = ("session", "pair", "approval", "code", "grant")
    for kind in kinds:
        for policy in ("kakao:old", "google:old", "passkey:existing", "local", "legacy:admin"):
            state.put(kind, policy, {"policy": policy, "other": "retained"})
    for kind in ("kakao", "kakao-flow", "kakao-enroll", "google", "google-flow"):
        state.put(kind, "config", {"secret": "synthetic"})
    state.put("settings", "profile", "same profile")
    retire_social_login(state)
    retire_social_login(state)
    for kind in kinds:
        assert {key for key, _ in state.all(kind)} == {"passkey:existing", "local", "legacy:admin"}
    for kind in ("kakao", "kakao-flow", "kakao-enroll", "google", "google-flow"):
        assert state.all(kind) == []
    assert state.get("settings", "profile") == "same profile"


def test_restart_preserves_real_passkey_session_and_grant(authority, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ADMIN_AUTH_MODE", raising=False)
    key, _ = enroll(authority)
    policy = authority.info()["policy"]
    path = tmp_path / "admin.db"
    owner = OwnerAuth(path, "a" * 43)
    cookie, _ = owner.create_session(1800, "existing browser", policy=policy)
    owner.state.put("kakao", "config", {"secret": "obsolete"})
    owner.create_session(1800, "old provider", policy="kakao:old")
    restarted = create_app("a" * 43, auth_db=path, passkeys=authority)
    with TestClient(restarted, base_url=ADMIN) as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get("/admin/api/auth-info").json()["mode"] == "passkey"
        assert client.get("/admin/api/session").status_code == 200
        assert client.get("/admin/api/kakao-callback").status_code == 404
        assert (
            client.post("/admin/api/kakao-login", json={}, headers={"Origin": ADMIN}).status_code
            == 404
        )
        assert client.get("/admin/kakao-login.png").status_code == 404
    assert owner.state.all("kakao") == []
    assert len(owner.state.all("session")) == 1

    config = Config(PUBLIC, str(tmp_path / "dot.db"), "", Fernet.generate_key())
    assert config.approval_mode == "passkey"
    state = State(config.database, config.storage_key)
    oauth = OAuth(config, state, authority)
    profile = oauth.profile
    grant = {
        "policy": policy,
        "revoked": False,
        "expires": time.time() + 3600,
        "scope": "kakao.read",
        "resource": config.resource,
        "client_id": "existing",
    }
    state.put("grant", "existing", grant)
    tokens = oauth.issue("existing", grant)
    state.put("kakao", "config", {"secret": "obsolete"})
    state.put("grant", "old", {**grant, "policy": "kakao:old"})
    public = public_app(config, Source(), worker=False, passkeys=authority)
    assert public.state.oauth.profile == profile
    with TestClient(public, base_url=PUBLIC) as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer " + tokens["access_token"]},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 200
        assert "tools" in response.json()["result"]
        assert client.get("/authorize/kakao/callback").status_code == 404
        assert client.get("/assets/kakao-login.png").status_code == 404
    assert state.all("kakao") == []
    assert state.get("grant", "old") is None
    assert authority.info()["policy"] == policy
    _, data = assertion(authority, key)
    assert authority.call("admin", "authenticate_verify", data)["policy"] == policy
