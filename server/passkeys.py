"""Single-owner WebAuthn authority. Its database is never mounted by the public service."""

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sys
import time
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from dot_plugin.storage import State
from server.config import secret
from server.origins import validate_admin_origin, validate_origin


def encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_client_data(credential):
    data = json.loads(decode(credential["response"]["clientDataJSON"]))
    if data.get("crossOrigin", False) is not False or "topOrigin" in data:
        raise ValueError("Cross-origin WebAuthn ceremonies are not allowed")


class Passkeys:
    def __init__(self, state):
        self.state = state

    def configure(self, admin_origin, public_origin=""):
        validate_admin_origin(admin_origin)
        if public_origin:
            validate_origin(public_origin)
        host = urlsplit(admin_origin).hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("Use an HTTPS hostname, not an IP address")
        if public_origin and urlsplit(public_origin).hostname != host:
            raise ValueError("Admin and MCP must use the same hostname for this passkey")
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self.state.get("passkey", "config", db=db)
            if old and old["rp_id"] != host:
                raise ValueError(
                    "The passkey hostname cannot change; recover at the original address"
                )
            config = {
                "rp_id": host,
                "admin_origin": admin_origin,
                "public_origin": public_origin,
                "user_id": old["user_id"] if old else encode(secrets.token_bytes(32)),
                "generation": secrets.token_hex(16),
            }
            self.state.put("passkey", "config", config, db=db)
            db.execute("DELETE FROM records WHERE kind IN ('ceremony','enrollment','proof')")
        return self.info()

    def info(self):
        config = self.state.get("passkey", "config")
        return {
            "configured": bool(config),
            "registered": bool(self.state.all("credential")),
            "admin_origin": config["admin_origin"] if config else "",
            "public_origin": config["public_origin"] if config else "",
            "policy": "passkey:" + (config["generation"] if config else "unconfigured"),
        }

    def issue_enrollment(self):
        """CLI only, including recovery. Reissuing invalidates pending registrations."""
        if not self.info()["configured"]:
            raise ValueError("passkey_not_configured")
        token = secrets.token_urlsafe(32)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM records WHERE kind='enrollment'")
            self.state.put("enrollment", digest(token), {"expires": time.time() + 600}, db=db)
        return token

    def config(self, role, origin):
        config = self.state.get("passkey", "config")
        if role not in {"admin", "public"} or not config or origin != config[role + "_origin"]:
            raise ValueError("invalid_passkey_origin")
        return config

    def call(self, role, operation, data=None):
        allowed = {"info", "authenticate_options", "authenticate_verify"}
        if role == "admin":
            allowed |= {"register_options", "register_verify", "credentials", "remove"}
        if operation not in allowed:
            raise ValueError("passkey_operation_unavailable")
        return getattr(self, operation)(
            **({} if operation == "info" else {"role": role}), **(data or {})
        )

    def _options(self, role, origin, browser, purpose, context, **extra):
        config = self.config(role, origin)
        if not isinstance(browser, str) or not 32 <= len(browser) <= 128:
            raise ValueError("invalid_passkey_browser")
        if role == "public" and purpose != "mcp":
            raise ValueError("invalid_passkey_purpose")
        if role == "admin" and purpose not in {"login", "manage", "register"}:
            raise ValueError("invalid_passkey_purpose")
        if not isinstance(context, str) or len(context) > 256:
            raise ValueError("invalid_passkey_context")
        flow = secrets.token_urlsafe(32)
        row = {
            "challenge": encode(secrets.token_bytes(32)),
            "browser": digest(browser),
            "role": role,
            "origin": origin,
            "purpose": purpose,
            "context": context,
            "generation": config["generation"],
            "expires": time.time() + 180,
            **extra,
        }
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            for kind in ("ceremony", "proof"):
                for key, value in self.state.all(kind, db=db):
                    if value["expires"] <= time.time():
                        self.state.delete(kind, key, db=db)
            if sum(r["role"] == role for _, r in self.state.all("ceremony", db=db)) >= 30:
                raise ValueError("passkey_busy")
            self.state.put("ceremony", digest(flow), row, db=db)
        return config, flow, row

    def _consume(self, role, origin, browser, flow, purpose, context):
        config = self.config(role, origin)
        # Consume before verification: malformed or replayed responses cannot reuse a challenge.
        row = self.state.take("ceremony", digest(flow))
        if (
            not row
            or row["expires"] <= time.time()
            or row["role"] != role
            or row["origin"] != origin
            or row["purpose"] != purpose
            or row["context"] != context
            or row["generation"] != config["generation"]
            or not hmac.compare_digest(row["browser"], digest(browser))
        ):
            raise ValueError("invalid_passkey_ceremony")
        return config, row

    def _capability(self, kind, token, browser, db):
        row = self.state.get(kind, digest(token), db=db)
        if not row or row["expires"] <= time.time():
            raise ValueError("passkey_registration_required")
        if kind == "proof":
            config = self.state.get("passkey", "config", db=db)
            if row["browser"] != digest(browser) or row["generation"] != config["generation"]:
                raise ValueError("invalid_passkey_proof")
        return row

    def register_options(self, role, origin, browser, enrollment="", proof="", label="Passkey"):
        if role != "admin":
            raise ValueError("passkey_registration_unavailable")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            raise ValueError("invalid_passkey_label")
        kind, value = ("enrollment", enrollment) if enrollment else ("proof", proof)
        with self.state.transaction() as db:
            self._capability(kind, value, browser, db)
            credentials = self.state.all("credential", db=db)
            if len(credentials) >= 10:
                raise ValueError("passkey_limit")
        config, flow, row = self._options(
            role,
            origin,
            browser,
            "register",
            "",
            capability=[kind, digest(value)],
            label=label.strip(),
        )
        options = generate_registration_options(
            rp_id=config["rp_id"],
            rp_name="KakaoTalk Bridge",
            user_id=decode(config["user_id"]),
            user_name="Bridge owner",
            user_display_name="Bridge owner",
            challenge=decode(row["challenge"]),
            timeout=120000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=decode(key)) for key, _ in credentials
            ],
        )
        return {"flow": flow, "options": json.loads(options_to_json(options))}

    def register_verify(self, role, origin, browser, flow, credential):
        config, row = self._consume(role, origin, browser, flow, "register", "")
        check_client_data(credential)
        if role != "admin":
            raise ValueError("passkey_registration_unavailable")
        result = verify_registration_response(
            credential=credential,
            expected_challenge=decode(row["challenge"]),
            expected_rp_id=config["rp_id"],
            expected_origin=origin,
            require_user_verification=True,
        )
        identity = encode(result.credential_id)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self.state.get("passkey", "config", db=db)
            kind, key = row["capability"]
            cap = self.state.get(kind, key, db=db)
            if (
                not cap
                or cap["expires"] <= time.time()
                or current != config
                or self.state.get("credential", identity, db=db)
                or len(self.state.all("credential", db=db)) >= 10
            ):
                raise ValueError("passkey_registration_expired")
            self.state.delete(kind, key, db=db)
            if kind == "enrollment" and self.state.all("credential", db=db):
                # CLI recovery revokes pre-existing browser and OAuth sessions.
                current["generation"] = secrets.token_hex(16)
                self.state.put("passkey", "config", current, db=db)
            self.state.put(
                "credential",
                identity,
                {
                    "key": encode(result.credential_public_key),
                    "count": result.sign_count,
                    "created": time.time(),
                    "last_used": None,
                    "label": row["label"],
                    "backed_up": result.credential_backed_up,
                },
                db=db,
            )
        return {"policy": "passkey:" + current["generation"], "id": identity}

    def authenticate_options(self, role, origin, browser, purpose="login", context=""):
        if not self.info()["registered"]:
            raise ValueError("passkey_registration_required")
        config, flow, row = self._options(role, origin, browser, purpose, context)
        options = generate_authentication_options(
            rp_id=config["rp_id"],
            challenge=decode(row["challenge"]),
            timeout=120000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return {"flow": flow, "options": json.loads(options_to_json(options))}

    def authenticate_verify(
        self, role, origin, browser, flow, credential, purpose="login", context=""
    ):
        config, row = self._consume(role, origin, browser, flow, purpose, context)
        check_client_data(credential)
        identity = encode(decode(credential["id"]))
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = self.state.get("credential", identity, db=db)
            handle = credential.get("response", {}).get("userHandle")
            if (
                not stored
                or (handle is not None and decode(handle) != decode(config["user_id"]))
                or self.state.get("passkey", "config", db=db) != config
            ):
                raise ValueError("unknown_passkey")
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=decode(row["challenge"]),
                expected_rp_id=config["rp_id"],
                expected_origin=origin,
                credential_public_key=decode(stored["key"]),
                credential_current_sign_count=stored["count"],
                require_user_verification=True,
            )
            stored.update(
                count=result.new_sign_count,
                last_used=time.time(),
                backed_up=result.credential_backed_up,
            )
            self.state.put("credential", identity, stored, db=db)
            proof = ""
            if purpose == "manage" and role == "admin":
                proof = secrets.token_urlsafe(32)
                self.state.put(
                    "proof",
                    digest(proof),
                    {
                        "browser": digest(browser),
                        "generation": config["generation"],
                        "expires": time.time() + 180,
                    },
                    db=db,
                )
        return {"policy": "passkey:" + config["generation"], "proof": proof}

    def credentials(self, role):
        return {
            "items": [
                {"id": key, **{k: row[k] for k in ("label", "created", "last_used", "backed_up")}}
                for key, row in self.state.all("credential")
            ]
        }

    def remove(self, role, browser, proof, identity):
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            self._capability("proof", proof, browser, db)
            if len(self.state.all("credential", db=db)) <= 1:
                raise ValueError("Keep at least one passkey. Add another before removing this one.")
            if not self.state.get("credential", identity, db=db):
                raise ValueError("unknown_passkey")
            self.state.delete("proof", digest(proof), db=db)
            self.state.delete("credential", identity, db=db)
            config = self.state.get("passkey", "config", db=db)
            config["generation"] = secrets.token_hex(16)
            self.state.put("passkey", "config", config, db=db)
        return {"ok": True}


def authority():
    key = base64.urlsafe_b64encode(
        hashlib.sha256(("passkey-v1:" + secret("MCP_APPROVAL_TOKEN")).encode()).digest()
    )
    return Passkeys(State(os.getenv("PASSKEY_DB", "/passkeys/passkeys.db"), key))


if __name__ == "__main__":
    auth = authority()
    if sys.argv[1:] == ["configure"]:
        auth.configure(**json.loads(sys.stdin.read(4096)))
        print("Passkey origins configured.")
    elif sys.argv[1:] == ["enroll"]:
        print(auth.issue_enrollment())
    elif sys.argv[1:] == ["info"]:
        print(json.dumps(auth.info()))
    else:
        raise SystemExit("Use configure, enroll or info")
