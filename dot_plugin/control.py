"""Private approval listener. Never mounted by the public MCP application."""

import hmac
import secrets
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from webauthn.helpers.exceptions import WebAuthnException

from dot_plugin import event_policy
from dot_plugin.auth import digest, grant_unexpired, redirect_origin
from dot_plugin.config import SCOPES, Config
from dot_plugin.storage import State
from server.app import BodyLimit
from server.config import secret


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[A-F0-9]{8}$")
    approve: bool


class TunnelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tunnel_id: str = Field(pattern=r"^tunnel_[a-z0-9]{32}$")
    approve: bool
    allow_send: bool | None = None


def create_app(config=None, state=None, control_token=None, passkeys=None, verifier_token=None):
    config = config or Config.from_env(control=True)
    state = state or State(config.database, config.storage_key)
    token = control_token or secret("MCP_APPROVAL_TOKEN")
    if len(token) < 32:
        raise ValueError("Control token must contain at least 32 characters")

    def authenticate(request: Request):
        expected = token
        if request.url.path.startswith("/passkeys/public/"):
            expected = verifier_token or secret("MCP_PASSKEY_TOKEN")
            if len(expected) < 32:
                raise HTTPException(503, "passkey_unavailable")
        if not hmac.compare_digest(
            request.headers.get("authorization", "").encode(), ("Bearer " + expected).encode()
        ):
            raise HTTPException(401, "unauthorized")

    app = FastAPI(
        docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(authenticate)]
    )
    app.add_middleware(BodyLimit, maximum=32768)

    def owner_policy():
        nonlocal passkeys
        if passkeys is None:
            from server.passkeys import authority

            passkeys = authority()
        info = passkeys.call("admin", "info", {})
        if not info.get("registered"):
            raise HTTPException(409, "먼저 관리자 패스키를 등록하세요.")
        return info["policy"]

    def tunnel_status():
        identity = state.get("settings", "tunnel_grant", "")
        row = state.get("grant", identity)
        active = bool(
            config.tunnel_id
            and row
            and row.get("transport") == "tunnel"
            and not row["revoked"]
            and grant_unexpired(row)
            and row["resource"] == config.tunnel_resource
            and row.get("policy") == owner_policy()
        )
        return {
            "configured": bool(config.tunnel_id),
            "tunnel_id": config.tunnel_id,
            "approved": active,
            "allow_send": active and "kakao.send" in row["scope"].split(),
            "expires": row["expires"] if active else None,
            "last_tool_at": state.get("connection_activity", identity, {}).get("last_tool_at")
            if active
            else None,
        }

    @app.post("/tunnel/decision")
    def tunnel_decide(body: TunnelDecision):
        if not config.tunnel_id or body.tunnel_id != config.tunnel_id:
            raise HTTPException(409, "터널 설정이 바뀌었습니다. ‘연결 새로고침’을 누른 뒤 다시 승인하세요.")
        policy = owner_policy() if body.approve else None
        with state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = state.get("settings", "tunnel_grant", "", db=db)
            row = state.get("grant", previous, db=db)
            reusable = bool(
                row
                and row.get("transport") == "tunnel"
                and not row["revoked"]
                and grant_unexpired(row)
                and row["resource"] == config.tunnel_resource
                and row.get("policy") == policy
            )
            allow_send = (
                body.allow_send
                if body.allow_send is not None
                else bool(reusable and "kakao.send" in row["scope"].split())
            )
            scope = SCOPES if allow_send else "kakao.read kakao.events"
            # Repeated approval preserves the grant and its subscriptions.
            if body.approve and reusable:
                row["scope"] = scope
                state.put("grant", previous, row, db=db)
                return {"ok": True}
            if row:
                row["revoked"] = True
                state.put("grant", previous, row, db=db)
            if body.approve:
                profile = state.get("settings", "profile", db=db)
                if not profile:
                    profile = "prf_" + secrets.token_hex(16)
                    state.put("settings", "profile", profile, db=db)
                identity = secrets.token_hex(24)
                state.put(
                    "grant",
                    identity,
                    {
                        "transport": "tunnel",
                        "client_id": "OpenAI personal tunnel",
                        "resource": config.tunnel_resource,
                        "scope": scope,
                        "owner": digest(profile + ":personal-tunnel:" + config.tunnel_id),
                        "policy": policy,
                        "revoked": False,
                        "expires": None,
                    },
                    db=db,
                )
                state.put("settings", "tunnel_grant", identity, db=db)
        return {"ok": True}

    @app.get("/events/settings")
    def event_settings():
        now = time.time()
        subscriptions = []
        for _, sub in state.all("subscription"):
            grant = state.get("grant", sub["grant_id"])
            if (
                sub["active"]
                and sub["expires"] > now
                and grant
                and not grant["revoked"]
                and grant_unexpired(grant, now=now)
            ):
                subscriptions.append(
                    {
                        "conversation_ref": sub["args"].get("conversation_ref"),
                        "cursor_epoch": sub["epoch"],
                    }
                )
        return {"conversations": dict(state.all(event_policy.KIND)), "subscriptions": subscriptions}

    @app.post("/events/settings")
    def event_decide(body: event_policy.EventDecision):
        try:
            event_policy.decide(state, body)
        except ValueError:
            raise HTTPException(422, "collection_checkpoint_required") from None
        return {"ok": True}

    @app.post("/passkeys/{role}/{operation}")
    def passkey_call(role: str, operation: str, body: dict):
        nonlocal passkeys
        if role not in {"admin", "public"}:
            raise HTTPException(404)
        if passkeys is None:
            from server.passkeys import authority

            passkeys = authority()
        try:
            return passkeys.call(role, operation, body)
        except (ValueError, TypeError, KeyError, WebAuthnException):
            # Authenticator/parser failures never expose credentials or raw client data.
            raise HTTPException(400, "passkey_verification_failed") from None

    @app.get("/connections")
    def connections():
        now = time.time()
        pending = [
            {
                "id": identity,
                "code": row["display_code"],
                "client_name": row["client_name"],
                "client_id": row["query"]["client_id"],
                "scope": row["scope"],
                "redirect_origin": redirect_origin(row["query"]["redirect_uri"]),
                "expires": row["expires"],
            }
            for identity, row in state.all("approval")
            if config.approval_mode == "admin"
            and row.get("status") == "pending"
            and row["expires"] > now
        ]
        grants = [
            {
                "id": identity,
                "client_id": row["client_id"],
                "scope": row["scope"],
                "expires": row["expires"],
                "last_tool_at": state.get("connection_activity", identity, {}).get("last_tool_at"),
            }
            for identity, row in state.all("grant")
            if row.get("transport", "oauth") == "oauth"
            and not row["revoked"]
            and grant_unexpired(row, now=now)
        ]
        return {
            "pending": pending,
            "grants": grants,
            "resource": config.resource,
            "approval_mode": config.approval_mode,
            "tunnel": tunnel_status(),
        }

    @app.post("/approvals/{identity}")
    def decide(identity: str, body: Decision):
        if config.approval_mode != "admin":
            raise HTTPException(409, "admin_approval_disabled")
        with state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            row = state.get("approval", identity, db=db)
            if (
                not row
                or row["expires"] <= time.time()
                or row.get("status") != "pending"
                or not hmac.compare_digest(body.code, row["display_code"])
            ):
                raise HTTPException(409, "request_changed_or_expired")
            row["status"] = "approved" if body.approve else "denied"
            state.put("approval", identity, row, db=db)
        return {"ok": True}

    @app.post("/grants/{identity}/revoke")
    def revoke(identity: str):
        with state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            row = state.get("grant", identity, db=db)
            if row:
                row["revoked"] = True
                state.put("grant", identity, row, db=db)
        return {"ok": True}

    return app
