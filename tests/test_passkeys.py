import hashlib
import json
import secrets
import struct
import time

import cbor2
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from webauthn.helpers.exceptions import WebAuthnException

from dot_plugin.config import Config
from dot_plugin.control import create_app as control_app
from dot_plugin.storage import State
from server.passkeys import Passkeys, decode, digest, encode
from webui.app import create_app

ADMIN = "https://bridge.example:8443"
PUBLIC = "https://bridge.example"
BROWSER = "b" * 43


class Authenticator:
    """Real ES256 signatures and WebAuthn wire data; no verifier mocks."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.identity = secrets.token_bytes(32)
        self.count = 0

    def credential(
        self, start, origin=ADMIN, *, register=False, uv=True, rp="bridge.example", handle=None
    ):
        client = json.dumps(
            {
                "type": "webauthn.create" if register else "webauthn.get",
                "challenge": start["options"]["challenge"],
                "origin": origin,
                "crossOrigin": False,
            }
        ).encode()
        self.count += 1
        data = (
            hashlib.sha256(rp.encode()).digest()
            + bytes([1 | (4 if uv else 0) | (64 if register else 0)])
            + struct.pack(">I", self.count)
        )
        response = {"clientDataJSON": encode(client)}
        if register:
            point = self.key.public_key().public_numbers()
            cose = cbor2.dumps(
                {1: 2, 3: -7, -1: 1, -2: point.x.to_bytes(32), -3: point.y.to_bytes(32)}
            )
            data += bytes(16) + struct.pack(">H", len(self.identity)) + self.identity + cose
            response.update(
                attestationObject=encode(
                    cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": data})
                ),
                transports=["internal"],
            )
        else:
            response.update(
                authenticatorData=encode(data),
                signature=encode(
                    self.key.sign(data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
                ),
                userHandle=handle,
            )
        return {
            "id": encode(self.identity),
            "rawId": encode(self.identity),
            "type": "public-key",
            "response": response,
        }


@pytest.fixture
def authority(tmp_path):
    auth = Passkeys(State(str(tmp_path / "passkeys.db"), Fernet.generate_key()))
    auth.configure(ADMIN, PUBLIC)
    return auth


def enroll(auth, key=None):
    key = key or Authenticator()
    token = auth.issue_enrollment()
    start = auth.call(
        "admin", "register_options", {"origin": ADMIN, "browser": BROWSER, "enrollment": token}
    )
    auth.call(
        "admin",
        "register_verify",
        {
            "origin": ADMIN,
            "browser": BROWSER,
            "flow": start["flow"],
            "credential": key.credential(start, register=True),
        },
    )
    return key, token


def assertion(auth, key, *, role="admin", origin=ADMIN, purpose="login", context="", **options):
    data = {"origin": origin, "browser": BROWSER, "purpose": purpose, "context": context}
    start = auth.call(role, "authenticate_options", data)
    credential = key.credential(start, origin, **options)
    return start, {**data, "flow": start["flow"], "credential": credential}


def test_registration_assertion_and_enrollment_replay(authority):
    key, token = enroll(authority)
    with pytest.raises(ValueError):
        authority.call(
            "admin", "register_options", {"origin": ADMIN, "browser": BROWSER, "enrollment": token}
        )
    _, data = assertion(authority, key)
    assert authority.call("admin", "authenticate_verify", data)["policy"].startswith("passkey:")
    with pytest.raises(ValueError):
        authority.call("admin", "authenticate_verify", data)


@pytest.mark.parametrize(
    "change",
    ["browser", "origin", "challenge", "signature", "uv", "rp", "handle", "expired", "purpose"],
)
def test_assertion_rejects_invalid_bindings(authority, change):
    key, _ = enroll(authority)
    kwargs = (
        {"uv": False}
        if change == "uv"
        else {"rp": "other.example"}
        if change == "rp"
        else {"handle": encode(b"other")}
        if change == "handle"
        else {}
    )
    start, data = assertion(authority, key, **kwargs)
    if change in {"browser", "origin", "purpose"}:
        data[change] = {"browser": "x" * 43, "origin": PUBLIC, "purpose": "manage"}[change]
    if change == "signature":
        data["credential"]["response"]["signature"] = encode(b"invalid")
    if change == "challenge":
        client = json.loads(decode(data["credential"]["response"]["clientDataJSON"]))
        client["challenge"] = encode(b"wrong")
        data["credential"]["response"]["clientDataJSON"] = encode(json.dumps(client).encode())
    if change == "expired":
        row = authority.state.get("ceremony", digest(start["flow"]))
        row["expires"] = time.time() - 1
        authority.state.put("ceremony", digest(start["flow"]), row)
    with pytest.raises((ValueError, WebAuthnException)):
        authority.call("admin", "authenticate_verify", data)


def test_no_public_enrollment_or_admin_proof(authority):
    key, _ = enroll(authority)
    for operation in (
        "register_options",
        "register_verify",
        "credentials",
        "remove",
        "configure",
        "issue_enrollment",
    ):
        with pytest.raises(ValueError):
            authority.call("public", operation)
    with pytest.raises(ValueError):
        assertion(authority, key, role="public", origin=PUBLIC, purpose="manage")
    _, data = assertion(
        authority, key, role="public", origin=PUBLIC, purpose="mcp", context="ticket"
    )
    assert authority.call("public", "authenticate_verify", data)["proof"] == ""


def test_registration_requires_cli_and_invalidates_old_links(authority):
    old = authority.issue_enrollment()
    authority.issue_enrollment()
    for value in ("", old):
        with pytest.raises(ValueError):
            authority.call(
                "admin",
                "register_options",
                {"origin": ADMIN, "browser": BROWSER, "enrollment": value},
            )
    with pytest.raises(ValueError):
        authority.configure("https://127.0.0.1")
    with pytest.raises(ValueError):
        authority.configure(ADMIN, "https://different.example")


def test_reauth_backup_passkey_and_last_key_protection(authority):
    key, _ = enroll(authority)
    _, data = assertion(authority, key, purpose="manage")
    proof = authority.call("admin", "authenticate_verify", data)["proof"]
    with pytest.raises(ValueError):
        authority.call(
            "admin",
            "remove",
            {"browser": BROWSER, "proof": proof, "identity": encode(key.identity)},
        )
    start = authority.call(
        "admin", "register_options", {"origin": ADMIN, "browser": BROWSER, "proof": proof}
    )
    second = Authenticator()
    authority.call(
        "admin",
        "register_verify",
        {
            "origin": ADMIN,
            "browser": BROWSER,
            "flow": start["flow"],
            "credential": second.credential(start, register=True),
        },
    )
    old_policy = authority.info()["policy"]
    _, data = assertion(authority, second, purpose="manage")
    proof = authority.call("admin", "authenticate_verify", data)["proof"]
    authority.call(
        "admin", "remove", {"browser": BROWSER, "proof": proof, "identity": encode(key.identity)}
    )
    assert authority.info()["policy"] != old_policy
    _, data = assertion(authority, key)
    with pytest.raises(ValueError):
        authority.call("admin", "authenticate_verify", data)


def test_control_limits_public_service_token(authority, tmp_path):
    config = Config(
        PUBLIC, str(tmp_path / "dot.db"), "", Fernet.generate_key(), approval_mode="passkey"
    )
    app = control_app(config, control_token="a" * 43, verifier_token="v" * 43, passkeys=authority)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + "v" * 43}
        assert client.post("/passkeys/public/info", headers=headers, json={}).status_code == 200
        assert client.post("/passkeys/admin/info", headers=headers, json={}).status_code == 401
        assert client.get("/connections", headers=headers).status_code == 401
        assert (
            client.post("/passkeys/public/register_options", headers=headers, json={}).status_code
            == 400
        )


def test_admin_registration_session_and_revocation(authority, tmp_path):
    app = create_app(
        "a" * 43, auth_mode="passkey", auth_db=tmp_path / "admin.db", passkeys=authority
    )
    with TestClient(app, base_url=ADMIN) as client:
        headers = {"Origin": ADMIN}
        assert client.get("/admin/api/session").status_code == 401
        assert (
            client.post(
                "/admin/api/owner-login", json={"password": "anything"}, headers=headers
            ).status_code
            == 403
        )
        start = client.post(
            "/admin/api/passkeys/register-options",
            json={"enrollment": authority.issue_enrollment()},
            headers=headers,
        ).json()
        key = Authenticator()
        registered = client.post(
            "/admin/api/passkeys/register-verify",
            json={"flow": start["flow"], "credential": key.credential(start, register=True)},
            headers=headers,
        )
        assert registered.status_code == 200
        assert client.get("/admin/api/session").status_code == 200
        assert client.post("/admin/api/logout", json={}, headers=headers).status_code == 403
        headers["X-CSRF-Token"] = registered.json()["csrf"]
        assert client.post("/admin/api/logout", json={}, headers=headers).status_code == 200
        assert client.get("/admin/api/session").status_code == 401


def test_counter_rollback_and_request_context(authority):
    key, _ = enroll(authority)
    _, data = assertion(authority, key)
    authority.call("admin", "authenticate_verify", data)
    key.count = 0
    _, data = assertion(authority, key)
    with pytest.raises(WebAuthnException):
        authority.call("admin", "authenticate_verify", data)
    key.count = 10
    _, data = assertion(authority, key, role="public", origin=PUBLIC, purpose="mcp", context="one")
    data["context"] = "two"
    with pytest.raises(ValueError):
        authority.call("public", "authenticate_verify", data)
