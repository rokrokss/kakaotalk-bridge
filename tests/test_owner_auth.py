import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from fastapi.testclient import TestClient

from webui.app import COOKIE, create_app
from webui.auth import OwnerAuth, digest

TOKEN = "a" * 64
PASSWORD = "an owner password with spaces"
ORIGIN = "https://testserver"


def test_pair_is_atomic_one_use_and_never_changes_existing_password(tmp_path):
    owner = OwnerAuth(tmp_path / "owner.db", TOKEN)
    pair = owner.issue_pair()
    assert not owner.check_pair(pair, "short")
    with ThreadPoolExecutor(2) as pool:
        accepted = list(pool.map(lambda _: owner.check_pair(pair, PASSWORD), range(2)))
    assert accepted.count(True) == 1
    pair = owner.issue_pair()
    assert owner.check_pair(pair, "different password")
    assert owner.check_password(PASSWORD)
    assert not owner.check_password("different password")
    assert pair.encode() not in (tmp_path / "owner.db").read_bytes()
    old, new = owner.issue_pair(), owner.issue_pair()
    assert not owner.check_pair(old)
    row = owner.state.get("pair", digest(new))
    row["expires"] = time.time() - 1
    owner.state.put("pair", digest(new), row)
    assert not owner.check_pair(new)


def test_owner_session_survives_restart_and_can_be_revoked(tmp_path):
    path = tmp_path / "owner.db"
    app = create_app(TOKEN, Mock(), dict, auth_db=path, auth_mode="local")
    pair = app.state.owner.issue_pair()
    with TestClient(app, base_url=ORIGIN) as browser:
        response = browser.post(
            "/admin/api/owner-login",
            json={"pair": pair, "password": PASSWORD, "remember": True},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        assert response.json()["expires_in"] == 7 * 86400
        cookie = browser.cookies.get(COOKIE)
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
    restarted = create_app(TOKEN, Mock(), dict, auth_db=path, auth_mode="local")
    with TestClient(restarted, base_url=ORIGIN) as browser:
        browser.cookies.set(COOKIE, cookie)
        session = browser.get("/admin/api/session")
        assert session.status_code == 200
        headers = {"Origin": ORIGIN, "X-CSRF-Token": session.json()["csrf"]}
        rows = browser.get("/admin/api/browsers").json()["items"]
        assert len(rows) == 1 and rows[0]["current"]
        assert "csrf" not in rows[0]
        assert (
            browser.post(
                f"/admin/api/browsers/{rows[0]['id']}/revoke", json={}, headers={"Origin": ORIGIN}
            ).status_code
            == 403
        )
        assert (
            browser.post(
                f"/admin/api/browsers/{rows[0]['id']}/revoke", json={}, headers=headers
            ).status_code
            == 200
        )
        assert browser.get("/admin/api/session").status_code == 401
        assert (
            browser.post(
                "/admin/api/owner-login",
                json={"password": PASSWORD},
                headers={"Origin": "https://evil.test"},
            ).status_code
            == 403
        )
        assert (
            browser.post(
                "/admin/api/owner-login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
            ).status_code
            == 200
        )
        restarted.state.owner.reset_password()
        assert browser.get("/admin/api/session").status_code == 401


def test_session_limit_and_rate_limit(tmp_path):
    owner = OwnerAuth(tmp_path / "owner.db", TOKEN)
    first = owner.create_session(1800, "first")[0]
    for _ in range(10):
        owner.create_session(1800, "browser")
    assert len(owner.sessions("")) == 10
    assert owner.session(first) is None
    app = create_app(TOKEN, Mock(), dict, auth_db=tmp_path / "other.db", auth_mode="local")
    with TestClient(app, base_url=ORIGIN) as browser:
        for _ in range(5):
            assert (
                browser.post(
                    "/admin/api/owner-login", json={"password": "wrong"}, headers={"Origin": ORIGIN}
                ).status_code
                == 401
            )
        assert (
            browser.post(
                "/admin/api/owner-login", json={"password": "wrong"}, headers={"Origin": ORIGIN}
            ).status_code
            == 429
        )
