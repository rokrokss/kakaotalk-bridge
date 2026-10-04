"""Private approval listener. Never mounted by the public MCP application."""

import hmac
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from webauthn.helpers.exceptions import WebAuthnException

from dot_plugin.auth import redirect_origin
from dot_plugin.config import Config
from dot_plugin.storage import State
from server.app import BodyLimit
from server.config import secret


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[A-F0-9]{8}$")
    approve: bool


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
            }
            for identity, row in state.all("grant")
            if not row["revoked"] and row["expires"] > now
        ]
        return {
            "pending": pending,
            "grants": grants,
            "resource": config.resource,
            "approval_mode": config.approval_mode,
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
