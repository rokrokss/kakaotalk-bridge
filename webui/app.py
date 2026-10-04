"""HTTPS-only administrator sessions and finite Android controls; no shell endpoint."""

import hmac
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.app import BodyLimit
from server.config import secret
from webui.auth import OwnerAuth, digest
from webui.connections import Connections, RequestChanged
from webui.device import Android

COOKIE = "__Host-kakao-admin"
STATIC = Path(__file__).with_name("static")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    token: Annotated[str, Field(min_length=32, max_length=256)]


class OwnerLogin(Strict):
    password: Annotated[str, Field(max_length=256)] = ""
    pair: Annotated[str, Field(max_length=128)] = ""
    remember: bool = Field(default=False, strict=True)


class Decision(Strict):
    code: Annotated[str, Field(pattern=r"^[A-F0-9]{8}$")]
    approve: bool = Field(strict=True)


Identity = Annotated[str, Field(pattern=r"^[a-f0-9]{48,64}$")]


class Point(Strict):
    frame: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    x: int = Field(ge=0, le=8191, strict=True)
    y: int = Field(ge=0, le=8191, strict=True)
    end_x: int | None = Field(default=None, ge=0, le=8191, strict=True)
    end_y: int | None = Field(default=None, ge=0, le=8191, strict=True)
    duration: int = Field(default=350, ge=100, le=2000, strict=True)


class Text(Strict):
    text: Annotated[str, Field(min_length=1, max_length=4096)]


class Key(Strict):
    name: Literal["back", "home", "enter", "delete", "tab", "wake"]


class Action(Strict):
    name: Literal[
        "bootstrap",
        "prepare",
        "configure",
        "open-store",
        "setup-check",
        "open-kakao",
        "keyboard",
        "login-check",
        "confirm-secondary",
        "session-check",
        "phone-active",
        "phone-lost",
    ]
    phone_active: bool = Field(default=False, strict=True)
    tablet_active: bool = Field(default=False, strict=True)


def collector_status():
    import os

    request = URLRequest(
        os.getenv("API_URL", "http://api:8000") + "/v1/status",
        headers={"Authorization": "Bearer " + secret("READ_TOKEN")},
    )
    with urlopen(request, timeout=3) as response:
        data = json.load(response)
        # Status only: this service does not proxy arbitrary API paths or messages.
        return {
            k: data[k] for k in ("state", "warnings", "coverage", "last_observation_received_at")
        }


ERRORS = {
    "kakao_signature_unverified": "KakaoTalk publisher signature could not be verified. Use the official app; see the installation guide for supported signatures.",
    "aurora_artifact_unverified": "Aurora download did not match the pinned release. Retry or use APK import.",
    "android_not_ready": "Android is still starting. Wait, then refresh setup.",
    "screen_unavailable": "Could not retrieve the screen. Check that redroid has booted.",
    "keyboard_unavailable": "Select “Connect keyboard”, then focus a KakaoTalk input field. If needed, install the components under Installation first.",
    "focus_kakao_input": "Click an input field in KakaoTalk first.",
    "input_result_unknown": "Could not confirm the input result. Check the screen before entering text again.",
    "kakao_not_installed": "Complete the KakaoTalk installation first.",
}


def create_app(
    admin_token=None,
    android=None,
    status_provider=None,
    session_ttl=1800,
    auth_db=None,
    connections=None,
):
    token = admin_token or secret("ADMIN_TOKEN")
    if len(token) < 32:
        raise ValueError("Admin token must contain at least 32 characters")
    temporary = tempfile.TemporaryDirectory() if admin_token and not auth_db else None
    owner = OwnerAuth(
        auth_db
        or (
            temporary.name + "/admin.db"
            if temporary
            else os.getenv("ADMIN_AUTH_DB", "/auth/admin.db")
        ),
        token,
    )
    connections = connections or Connections()
    device = android or Android()
    status_provider = status_provider or collector_status
    lock = threading.Lock()
    session_lock = threading.Lock()
    sessions = {}
    failures = deque()
    pool = ThreadPoolExecutor(max_workers=1)
    job = {"state": "idle", "action": None, "message": ""}
    setup_snapshot = None
    session_snapshot = None
    snapshot_invalidated = True

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True, cancel_futures=True)
        if temporary:
            temporary.cleanup()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.owner = owner
    app.state.sessions = sessions
    app.state.job = job
    app.add_middleware(BodyLimit, maximum=32768)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in ("GET", "HEAD"):
            # Caddy preserves Host. HTTPS is mandatory externally; forwarded headers are not trusted.
            expected = "https://" + request.headers.get("host", "")
            if request.headers.get("origin") != expected:
                return JSONResponse({"detail": "invalid_origin"}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    def authenticated(request: Request):
        key = request.cookies.get(COOKIE, "")
        with session_lock:
            stored = owner.session(key)
            session = sessions.get(key)
            if stored and session is None:
                session = {
                    **stored,
                    "expires": time.monotonic() + stored["expires"] - time.time(),
                    "frames": {},
                }
                sessions[key] = session
            if not stored or session is None or session["expires"] <= time.monotonic():
                sessions.pop(key, None)
                raise HTTPException(401, "session_required")
        if request.method != "GET" and not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), session["csrf"].encode()
        ):
            raise HTTPException(403, "invalid_csrf")
        return session

    def operate(fn):
        if job["state"] == "running" or not lock.acquire(timeout=0.2):
            raise HTTPException(409, "device_busy")
        try:
            return fn()
        except (OSError, RuntimeError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(
                503,
                ERRORS.get(
                    str(exc),
                    "The device operation failed. Check the connection and installation status.",
                ),
            ) from None
        finally:
            lock.release()

    def invalidate_snapshot():
        nonlocal snapshot_invalidated
        snapshot_invalidated = True

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/admin/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/admin/{asset}")
    def asset(asset: str):
        if asset == "logo.svg":
            return FileResponse(STATIC.parent.parent / "assets" / "logo.svg")
        if asset not in {"app.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(STATIC / asset)

    @app.post("/admin/api/login")
    def login(body: Login, response: Response):
        with session_lock:
            now = time.monotonic()
            while failures and failures[0] <= now - 60:
                failures.popleft()
            if len(failures) >= 5:
                raise HTTPException(429, "Try again shortly.")
            if not hmac.compare_digest(body.token.encode(), token.encode()):
                failures.append(now)
                raise HTTPException(401, "The admin key is incorrect.")
        return issue_session(response, session_ttl, "Recovery key", exclusive=True)

    def issue_session(response, ttl, label, exclusive=False):
        key, record = owner.create_session(ttl, label, exclusive=exclusive)
        with session_lock:
            if exclusive:
                sessions.clear()
            sessions[key] = {**record, "expires": time.monotonic() + ttl, "frames": {}}
        response.set_cookie(
            COOKIE, key, max_age=ttl, secure=True, httponly=True, samesite="strict", path="/"
        )
        return {"csrf": record["csrf"], "expires_in": ttl}

    @app.get("/admin/api/auth-info")
    def auth_info():
        return {"configured": owner.configured()}

    @app.post("/admin/api/owner-login")
    def owner_login(body: OwnerLogin, request: Request, response: Response):
        with session_lock:
            now = time.monotonic()
            while failures and failures[0] <= now - 60:
                failures.popleft()
            if len(failures) >= 5:
                raise HTTPException(429, "Try again shortly.")
            # Count before password hashing to bound concurrent authentication work.
            failures.append(now)
            valid = (
                owner.check_pair(body.pair, body.password)
                if body.pair
                else owner.check_password(body.password)
            )
            if not valid:
                raise HTTPException(401, "Password or pairing link is invalid or expired.")
            failures.pop()
        return issue_session(
            response,
            7 * 86400 if body.remember else session_ttl,
            request.headers.get("user-agent", "Browser"),
        )

    @app.get("/admin/api/browsers")
    def browsers(request: Request, current: Annotated[dict, Depends(authenticated)]):
        return {"items": owner.sessions(request.cookies.get(COOKIE, ""))}

    @app.post("/admin/api/browsers/{identity}/revoke")
    def revoke_browser(identity: Identity, current: Annotated[dict, Depends(authenticated)]):
        owner.revoke(identity)
        return {"ok": True}

    def connection_call(method, path, data=None):
        try:
            return connections.call(method, path, data)
        except RequestChanged:
            raise HTTPException(
                409, "Code is incorrect or the request expired. Refresh Connections."
            ) from None
        except (OSError, ValueError):
            raise HTTPException(
                503, "Connection service unavailable. Start the dot profile."
            ) from None

    @app.get("/admin/api/connections")
    def connection_list(current: Annotated[dict, Depends(authenticated)]):
        return connection_call("GET", "/connections")

    @app.post("/admin/api/connections/{identity}/decide")
    def decide(
        identity: Identity, body: Decision, current: Annotated[dict, Depends(authenticated)]
    ):
        return connection_call("POST", "/approvals/" + identity, body.model_dump())

    @app.post("/admin/api/connections/{identity}/revoke")
    def revoke_connection(identity: Identity, current: Annotated[dict, Depends(authenticated)]):
        return connection_call("POST", "/grants/" + identity + "/revoke", {})

    @app.get("/admin/api/session")
    def session(current: Annotated[dict, Depends(authenticated)]):
        return {
            "csrf": current["csrf"],
            "expires_in": max(0, int(current["expires"] - time.monotonic())),
        }

    @app.post("/admin/api/logout")
    def logout(
        request: Request, response: Response, current: Annotated[dict, Depends(authenticated)]
    ):
        with session_lock:
            owner.revoke(digest(request.cookies.get(COOKIE, "")))
            sessions.pop(request.cookies.get(COOKIE), None)
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
        return {"ok": True}

    @app.get("/admin/api/state")
    def state(current: Annotated[dict, Depends(authenticated)]):
        try:
            status = status_provider()
        except (OSError, ValueError, KeyError):
            status = {"state": "unavailable", "warnings": ["collector_unavailable"]}
        return {
            "checked_at": time.time(),
            "job": dict(job),
            "setup": setup_snapshot,
            "collector": status,
            "sessions": session_snapshot,
            "sessions_stale": snapshot_invalidated
            or not session_snapshot
            or not 0 <= time.time() - session_snapshot["checked_at"] <= 60,
        }

    @app.get("/admin/api/screen")
    def screen(current: Annotated[dict, Depends(authenticated)]):
        png, width, height = operate(device.screenshot)
        frame = secrets.token_hex(16)
        now = time.monotonic()
        with session_lock:
            frames = current["frames"]
            for old in list(frames):
                if now - frames[old][2] > 10 or len(frames) >= 5:
                    del frames[old]
            frames[frame] = (width, height, now)
        return Response(
            png,
            media_type="image/png",
            headers={
                "X-Frame-Id": frame,
                "X-Screen-Width": str(width),
                "X-Screen-Height": str(height),
            },
        )

    @app.post("/admin/api/pointer")
    def pointer(body: Point, current: Annotated[dict, Depends(authenticated)]):
        with session_lock:
            frame = current["frames"].get(body.frame)
        if not frame or time.monotonic() - frame[2] > 10:
            raise HTTPException(
                409, "The screen is outdated. Wait for a new frame before trying again."
            )
        if (body.end_x is None) != (body.end_y is None):
            raise HTTPException(422, "invalid_swipe")
        points = [(body.x, body.y)]
        if body.end_x is not None:
            points.append((body.end_x, body.end_y))
        if any(x >= frame[0] or y >= frame[1] for x, y in points):
            raise HTTPException(422, "point_outside_screen")
        invalidate_snapshot()
        if body.end_x is None:
            operate(lambda: device.tap(body.x, body.y))
        else:
            operate(lambda: device.swipe(body.x, body.y, body.end_x, body.end_y, body.duration))
        return {"ok": True}

    @app.post("/admin/api/key")
    def key(body: Key, current: Annotated[dict, Depends(authenticated)]):
        invalidate_snapshot()
        operate(lambda: device.key(body.name))
        return {"ok": True}

    @app.post("/admin/api/text")
    def text(body: Text, current: Annotated[dict, Depends(authenticated)]):
        invalidate_snapshot()
        operate(lambda: device.text(body.text))
        return {"ok": True}

    def run_action(body):
        nonlocal session_snapshot, snapshot_invalidated, setup_snapshot
        try:
            already_approved = False
            changed = True
            with lock:
                if body.name == "prepare":
                    changed = device.prepare()
                elif body.name == "configure":
                    changed = device.configure()
                elif body.name == "open-store":
                    device.open_store()
                elif body.name == "bootstrap":
                    device.bootstrap()
                elif body.name == "open-kakao":
                    device.open_kakao()
                elif body.name == "keyboard":
                    device.enable_keyboard()
                elif body.name == "login-check":
                    already_approved = device.login_check() is False
                elif body.name == "confirm-secondary":
                    device.confirm(body.phone_active, body.tablet_active)
                elif body.name in ("phone-active", "phone-lost"):
                    device.record_phone(body.name == "phone-active")
                if body.name in ("setup-check", "prepare", "configure", "bootstrap"):
                    setup_snapshot = device.setup_status()
                if body.name in (
                    "setup-check",
                    "session-check",
                    "login-check",
                    "confirm-secondary",
                    "phone-active",
                    "phone-lost",
                ):
                    session_snapshot = device.session_status()
                    snapshot_invalidated = False
            message = {
                "prepare": "Aurora is ready. Choose anonymous sign-in and install KakaoTalk."
                if changed
                else "Existing installation preserved. Continue with the next setup step.",
                "configure": "Components installed. Open KakaoTalk and check login options."
                if changed
                else "Existing enrollment and collection approval preserved.",
                "open-store": "Aurora opened. Search for KakaoTalk by Kakao Corp.",
                "setup-check": "Setup status refreshed.",
                "bootstrap": "Installation complete. Open KakaoTalk and check login options.",
                "open-kakao": "KakaoTalk opened.",
                "keyboard": "Keyboard connected. Select an input field on the tablet.",
                "login-check": (
                    "Collection is already approved. Use “Check status” to see the current state."
                    if already_approved
                    else "Secondary-login options verified. Sign in on the tablet now."
                ),
                "confirm-secondary": "Both sessions confirmed. Starting message collection.",
                "session-check": "Checked the current screen and login confirmation records.",
                "phone-active": "Updated the time of your manual phone confirmation.",
                "phone-lost": "Phone sign-out recorded. Iris collection approval revoked.",
            }[body.name]
            job.update(state="done", message=message)
        except Exception as exc:  # noqa: BLE001 — isolate background jobs without leaking credentials
            # Login UI dumps, input strings, filesystem paths and exception bodies stay private.
            message = (
                "Could not verify login options. Select “Use with other devices” on the Korean KakaoTalk login screen before signing in. Existing collection approval is unchanged."
                if body.name == "login-check"
                else "Secondary-login confirmation failed. Check the precheck expiry and both sessions."
                if body.name in ("confirm-secondary", "phone-active")
                else "Could not stop collection. Check the device connection and Iris collection status."
                if body.name == "phone-lost"
                else "The operation failed. Check the redroid connection, APK files, and installation status."
            )
            job.update(state="failed", message=ERRORS.get(str(exc), message))

    @app.post("/admin/api/action", status_code=202)
    def action(body: Action, current: Annotated[dict, Depends(authenticated)]):
        if body.name == "confirm-secondary" and not (body.phone_active and body.tablet_active):
            raise HTTPException(422, "Manually confirm both the phone and redroid login sessions.")
        if body.name == "phone-active" and not body.phone_active:
            raise HTTPException(422, "Manually confirm that your existing phone session is active.")
        with session_lock:
            if job["state"] == "running":
                raise HTTPException(409, "device_busy")
            invalidate_snapshot()
            job.update(state="running", action=body.name, message="Working…")
            pool.submit(run_action, body)
        return {"accepted": True}

    return app
