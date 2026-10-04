import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dot_plugin.app import create_app
from dot_plugin.auth import digest
from dot_plugin.config import Config
from dot_plugin.control import create_app as control_app
from dot_plugin.storage import State
from tests.test_dot_plugin import BASE, Source, begin_link

TOKEN = "control-" + "c" * 40


def setup(tmp_path):
    config = Config(
        BASE, str(tmp_path / "dot.db"), "", Fernet.generate_key(), approval_mode="admin"
    )
    state = State(config.database, config.storage_key)
    public = TestClient(create_app(config, Source(), state, worker=False), base_url=BASE)
    private = TestClient(control_app(config, state, TOKEN), base_url="http://control")
    return state, public, private


def test_only_private_approval_can_issue_code(tmp_path):
    state, public, private = setup(tmp_path)
    _, ticket = begin_link(public)
    assert public.get("/connections").status_code == 404
    assert (
        public.post(
            "/approvals/" + digest(ticket), json={"code": "00000000", "approve": True}
        ).status_code
        == 404
    )
    assert private.get("/connections").status_code == 401
    rows = private.get("/connections", headers={"Authorization": "Bearer " + TOKEN}).json()
    pending = rows["pending"][0]
    assert not {"ticket", "cookie", "code_challenge", "state", "query"} & pending.keys()
    headers = {"Origin": BASE}
    data = {"ticket": ticket, "link_key": "anything"}
    assert public.post("/authorize", data=data, headers=headers).status_code == 403
    auth = {"Authorization": "Bearer " + TOKEN}
    assert (
        private.post(
            "/approvals/" + pending["id"], json={"code": "00000000", "approve": True}, headers=auth
        ).status_code
        == 409
    )
    assert (
        private.post(
            "/approvals/" + pending["id"],
            json={"code": pending["code"], "approve": True},
            headers=auth,
        ).status_code
        == 200
    )
    assert (
        private.post(
            "/approvals/" + pending["id"],
            json={"code": pending["code"], "approve": False},
            headers=auth,
        ).status_code
        == 409
    )
    assert public.post("/authorize/status", data={"ticket": ticket}, headers=headers).json() == {
        "status": "approved"
    }
    assert (
        public.post(
            "/authorize/status", data={"ticket": ticket}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    cookie = public.cookies.get("__Host-kakao-link")
    public.cookies.clear()
    assert (
        public.post("/authorize", data=data, headers=headers, follow_redirects=False).status_code
        == 403
    )
    public.cookies.set("__Host-kakao-link", cookie)
    assert (
        public.post("/authorize", data=data, headers=headers, follow_redirects=False).status_code
        == 303
    )
    assert (
        public.post("/authorize", data=data, headers=headers, follow_redirects=False).status_code
        == 403
    )
    assert state.all("subscription") == []


def test_denied_expired_and_revoked_grants(tmp_path):
    state, public, private = setup(tmp_path)
    auth = {"Authorization": "Bearer " + TOKEN}
    for expired in (False, True):
        _, ticket = begin_link(public)
        identity = digest(ticket)
        row = state.get("approval", identity)
        if expired:
            row["expires"] = time.time() - 1
            state.put("approval", identity, row)
        else:
            assert (
                private.post(
                    "/approvals/" + identity,
                    json={"code": row["display_code"], "approve": False},
                    headers=auth,
                ).status_code
                == 200
            )
        assert (
            public.post("/authorize", data={"ticket": ticket}, headers={"Origin": BASE}).status_code
            == 403
        )
    state.put(
        "grant",
        "g",
        {
            "client_id": "client",
            "scope": "kakao.read",
            "revoked": False,
            "expires": time.time() + 60,
        },
    )
    assert len(private.get("/connections", headers=auth).json()["grants"]) == 1
    assert private.post("/grants/g/revoke", json={}, headers=auth).status_code == 200
    assert state.get("grant", "g")["revoked"]
    assert not private.get("/connections", headers=auth).json()["grants"]


def test_control_config_requires_no_collector_or_link_secret(tmp_path, monkeypatch):
    (tmp_path / "storage").write_bytes(Fernet.generate_key())
    monkeypatch.setenv("DOT_PUBLIC_URL", BASE)
    monkeypatch.setenv("DOT_APPROVAL_MODE", "admin")
    monkeypatch.setenv("MCP_STORAGE_KEY_FILE", str(tmp_path / "storage"))
    monkeypatch.setenv("MCP_LINK_KEY_FILE", "/missing/link")
    monkeypatch.setenv("READ_TOKEN_FILE", "/missing/read")
    config = Config.from_env(control=True)
    assert config.read_token == config.link_key == ""
