"""HTTPS-only administrator sessions and finite Android controls; no shell endpoint."""

import hmac
import json
import os
import re
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

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from webauthn.helpers.exceptions import WebAuthnException

from device.messages import message as device_message
from dot_plugin.collector import QueryError
from dot_plugin.event_policy import ConversationDecision
from dot_plugin.event_policy import enabled as events_enabled
from server.app import BodyLimit
from server.config import secret
from server.connection_setup import validate as validate_connection_setup
from webui.auth import OwnerAuth, digest
from webui.connections import Connections, RequestChanged
from webui.device import Android
from webui.event_settings import EventSource
from webui.setup import SetupBusy, SetupClient

COOKIE = "__Secure-kakao-admin-v2"
COOKIE_PATH = "/admin"
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
        "setup-poll",
        "open-kakao",
        "keyboard",
        "approve",
        "session-check",
        "phone-active",
        "phone-lost",
    ]
    phone_active: bool = Field(default=False, strict=True)


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


def create_app(
    admin_token=None,
    android=None,
    status_provider=None,
    session_ttl=1800,
    auth_db=None,
    connections=None,
    auth_mode=None,
    passkeys=None,
    local_origin=None,
    event_source=None,
    setup_client=None,
):
    from urllib.parse import urlsplit

    from server.origins import validate_admin_origin

    local_origin = local_origin or os.getenv("ADMIN_LOCAL_ORIGIN", "")
    if local_origin:
        validate_admin_origin(local_origin)
        if not local_origin.startswith("http://localhost:"):
            raise ValueError("Local admin requires http://localhost:<port>")
    local_host = urlsplit(local_origin).netloc

    def is_local(request):
        return bool(local_origin and request.headers.get("host") == local_host)

    def request_origin(request):
        return local_origin if is_local(request) else "https://" + request.headers.get("host", "")

    def cookie_name(request):
        return (
            "kakao-admin-local-" + str(urlsplit(local_origin).port) if is_local(request) else COOKIE
        )

    auth_mode = auth_mode or os.getenv("ADMIN_AUTH_MODE", "passkey")
    if auth_mode not in {"local", "passkey"}:
        raise ValueError(
            "ADMIN_AUTH_MODE must be passkey or local"
        )
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
    setup_client = setup_client or SetupClient()
    event_source = event_source or EventSource()
    from server.passkey_client import PasskeyClient

    passkeys = passkeys or PasskeyClient("admin")
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
    app.state.passkeys = passkeys
    app.state.sessions = sessions
    app.state.job = job
    app.add_middleware(BodyLimit, maximum=32768)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in ("GET", "HEAD"):
            # Only the explicitly configured localhost origin may use HTTP.
            expected = request_origin(request)
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
        key = request.cookies.get(cookie_name(request), "")
        with session_lock:
            stored = owner.session(key)
            if stored and stored.get("cookie_scope") != "admin-v2":
                stored = None
            if stored and stored["origin"] != (local_origin if is_local(request) else ""):
                stored = None
            policy = current_policy()
            if stored and stored["policy"] != policy:
                stored = None
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
            raise HTTPException(503, device_message(exc)) from None
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
        if asset == "passkey.js":
            return FileResponse(STATIC.parent.parent / "dot_plugin/static/passkey.js")
        if asset == "logo.svg":
            return FileResponse(STATIC.parent.parent / "assets" / asset)
        if asset not in {"app.js", "setup-flow.js", "connection-setup.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(STATIC / asset)

    @app.post("/admin/api/login")
    def login(body: Login, request: Request, response: Response):
        if auth_mode != "local":
            raise HTTPException(
                403, "패스키로 로그인하세요. 서버에서 복구하려면 kakaotalk-bridge admin --recovery를 실행하세요."
            )
        with session_lock:
            now = time.monotonic()
            while failures and failures[0] <= now - 60:
                failures.popleft()
            if len(failures) >= 5:
                raise HTTPException(429, "잠시 후 다시 시도하세요.")
            if not hmac.compare_digest(body.token.encode(), token.encode()):
                failures.append(now)
                raise HTTPException(401, "관리자 키가 올바르지 않습니다.")
        return issue_session(request, response, session_ttl, "복구 키", exclusive=True)

    def issue_session(request, response, ttl, label, exclusive=False, policy="local"):
        key, record = owner.create_session(
            ttl,
            label,
            exclusive=exclusive,
            policy=policy,
            origin=local_origin if is_local(request) else "",
        )
        with session_lock:
            if exclusive:
                sessions.clear()
            sessions[key] = {**record, "expires": time.monotonic() + ttl, "frames": {}}
        response.set_cookie(
            cookie_name(request),
            key,
            max_age=ttl,
            secure=not is_local(request),
            httponly=True,
            samesite="strict",
            path=COOKIE_PATH,
        )
        return {"csrf": record["csrf"], "expires_in": ttl}

    def passkey_call(operation, data=None):
        try:
            return passkeys.call("admin", operation, data)
        except (ValueError, TypeError, KeyError, WebAuthnException):
            raise HTTPException(
                400, "패스키 인증에 실패했습니다. 다시 시도하거나 새 설정 링크를 여세요."
            ) from None
        except (OSError, RuntimeError):
            raise HTTPException(503, "패스키 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.") from None

    def current_policy():
        if auth_mode == "passkey":
            return passkey_call("info")["policy"]
        return "local"

    def passkey_origin(request):
        info = passkey_call("info")
        origin = request_origin(request)
        if auth_mode != "passkey" or not info["configured"] or origin != info["admin_origin"]:
            raise HTTPException(403, "패스키에 설정된 관리 화면 주소로 접속하세요.")
        return origin

    @app.post("/admin/api/passkeys/{operation}")
    def passkey_route(operation: str, body: dict, request: Request, response: Response):
        origin = passkey_origin(request)
        if operation not in {
            "register-options",
            "register-verify",
            "login-options",
            "login-verify",
            "credentials",
            "remove",
        }:
            raise HTTPException(404)
        flow_cookie = (
            "passkey-admin-local-" + str(urlsplit(local_origin).port)
            if is_local(request)
            else "__Host-passkey-admin-flow"
        )
        browser = request.cookies.get(flow_cookie, "")
        if not browser and operation.endswith("options"):
            browser = secrets.token_urlsafe(32)
        response.set_cookie(
            flow_cookie,
            browser,
            max_age=600,
            secure=not is_local(request),
            httponly=True,
            samesite="strict",
            path=COOKIE_PATH if is_local(request) else "/",
        )
        data = {"origin": origin, "browser": browser}
        if (
            operation in {"credentials", "remove"}
            or body.get("purpose") == "manage"
            or body.get("proof")
        ):
            authenticated(request)
        if operation == "credentials":
            return passkey_call("credentials")
        if operation == "remove":
            return passkey_call(
                "remove",
                {
                    "browser": browser,
                    "proof": body.get("proof", ""),
                    "identity": body.get("identity", ""),
                },
            )
        if operation == "register-options":
            return passkey_call(
                "register_options",
                {
                    **data,
                    "enrollment": body.get("enrollment", ""),
                    "proof": body.get("proof", ""),
                    "label": body.get("label", "패스키"),
                },
            )
        if operation == "register-verify":
            result = passkey_call(
                "register_verify",
                {**data, "flow": body.get("flow", ""), "credential": body.get("credential", {})},
            )
            return issue_session(
                request,
                response,
                session_ttl,
                "패스키 · " + request.headers.get("user-agent", "브라우저"),
                policy=result["policy"],
            )
        purpose = body.get("purpose", "login")
        if purpose not in {"login", "manage"}:
            raise HTTPException(400, "invalid_request")
        if operation == "login-options":
            # Remember preference is carried in the signed-by-server ceremony context.
            context = "remember" if body.get("remember") is True else ""
            result = passkey_call(
                "authenticate_options", {**data, "purpose": purpose, "context": context}
            )
            return {**result, "context": context}
        context = body.get("context", "")
        result = passkey_call(
            "authenticate_verify",
            {
                **data,
                "flow": body.get("flow", ""),
                "credential": body.get("credential", {}),
                "purpose": purpose,
                "context": context,
            },
        )
        if purpose == "manage":
            return result
        return issue_session(
            request,
            response,
            7 * 86400 if context == "remember" else session_ttl,
            "패스키 · " + request.headers.get("user-agent", "브라우저"),
            policy=result["policy"],
        )

    @app.get("/admin/api/auth-info")
    def auth_info():
        if auth_mode == "passkey":
            info = passkey_call("info")
            return {
                "mode": auth_mode,
                "configured": info["configured"],
                "owner_registered": info["registered"],
                "origin": info["admin_origin"],
            }
        return {
            "mode": auth_mode,
            "configured": owner.configured(),
            "owner_registered": owner.configured(),
        }

    @app.post("/admin/api/owner-login")
    def owner_login(body: OwnerLogin, request: Request, response: Response):
        policy = current_policy()
        if auth_mode != "local" and not body.pair:
            raise HTTPException(403, "설정된 로그인 방식을 사용하세요.")
        with session_lock:
            now = time.monotonic()
            while failures and failures[0] <= now - 60:
                failures.popleft()
            if len(failures) >= 5:
                raise HTTPException(429, "잠시 후 다시 시도하세요.")
            # Count before password hashing to bound concurrent authentication work.
            failures.append(now)
            valid = (
                owner.check_pair(body.pair, body.password, policy=policy)
                if body.pair
                else owner.check_password(body.password)
            )
            if not valid:
                raise HTTPException(401, "비밀번호가 올바르지 않거나 연결 링크가 만료되었습니다.")
            failures.pop()
        return issue_session(
            request,
            response,
            7 * 86400 if body.remember and auth_mode == "local" else session_ttl,
            request.headers.get("user-agent", "브라우저"),
            policy=policy,
        )

    @app.get("/admin/api/browsers")
    def browsers(request: Request, current: Annotated[dict, Depends(authenticated)]):
        return {"items": owner.sessions(request.cookies.get(cookie_name(request), ""))}

    @app.post("/admin/api/browsers/{identity}/revoke")
    def revoke_browser(identity: Identity, current: Annotated[dict, Depends(authenticated)]):
        owner.revoke(identity)
        return {"ok": True}

    def connection_call(method, path, data=None):
        try:
            return connections.call(method, path, data)
        except RequestChanged as exc:
            # The approval service sends fixed Korean guidance for known conflicts.
            detail = str(exc)
            raise HTTPException(
                409,
                detail
                if re.search("[가-힣]", detail)
                else "코드가 올바르지 않거나 요청이 만료되었습니다. ‘AI 연결’을 새로고침하세요.",
            ) from None
        except (OSError, ValueError):
            raise HTTPException(
                503, "연결 서비스를 사용할 수 없습니다. kakaotalk-bridge start로 서비스를 다시 시작하세요."
            ) from None

    @app.get("/admin/api/connections")
    def connection_list(current: Annotated[dict, Depends(authenticated)]):
        return connection_call("GET", "/connections")

    def setup_call(method="GET", data=None):
        try:
            return setup_client.call(method, data)
        except SetupBusy:
            raise HTTPException(
                409, "연결 설정이 이미 진행 중입니다. 완료될 때까지 기다리세요."
            ) from None
        except (OSError, ValueError):
            if method == "GET":
                return {
                    "available": False,
                    "message": "웹 설정 서비스를 사용할 수 없습니다. 설치된 컴퓨터에서 Bridge를 업데이트하고 kakaotalk-bridge up 또는 kakaotalk-bridge setup-agent install을 실행하세요. CLI 설정은 계속 사용할 수 있습니다.",
                }
            raise HTTPException(
                503,
                "설정 서비스를 사용할 수 없습니다. ‘AI 연결’을 다시 열어 상태를 확인한 뒤 재시도하세요.",
            ) from None

    @app.get("/admin/api/connection-setup")
    def setup_status(current: Annotated[dict, Depends(authenticated)]):
        return setup_call()

    @app.post("/admin/api/connection-setup", status_code=202)
    def setup_connection(data: dict, current: Annotated[dict, Depends(authenticated)]):
        try:
            validated = validate_connection_setup(data)
        except ValueError as exc:
            # Fixed Korean validation messages; they never contain submitted values.
            raise HTTPException(422, str(exc)) from None
        return setup_call("POST", validated)

    @app.get("/admin/api/events/conversations")
    def event_conversations(
        current: Annotated[dict, Depends(authenticated)],
        q: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    ):
        settings = connection_call("GET", "/events/settings")
        try:
            checkpoint = event_source.checkpoint()
            page = event_source.conversations(q=q, cursor=cursor)
        except QueryError:
            raise HTTPException(400, "대화 목록을 새로고침한 뒤 다시 시도하세요.") from None
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(
                503, "대화 목록을 가져올 수 없습니다. 수집 상태를 확인하세요."
            ) from None
        epoch = checkpoint["cursor_epoch"]
        items = []
        for room in page["items"]:
            if not room.get("ref"):
                continue
            subscriptions = sum(
                sub["cursor_epoch"] == epoch and sub["conversation_ref"] in (None, room["ref"])
                for sub in settings["subscriptions"]
            )
            items.append(
                {
                    **{
                        key: room.get(key)
                        for key in ("ref", "name", "name_status", "kind", "last_message_at")
                    },
                    "enabled": events_enabled(settings["conversations"].get(room["ref"]), epoch),
                    "subscriptions": subscriptions,
                }
            )
        return {"items": items, "next_cursor": page["next_cursor"], "has_more": page["has_more"]}

    @app.post("/admin/api/events/conversations")
    def event_decision(
        body: ConversationDecision, current: Annotated[dict, Depends(authenticated)]
    ):
        data = body.model_dump()
        if body.enabled:
            try:
                checkpoint = event_source.checkpoint()
            except (OSError, ValueError, RuntimeError):
                raise HTTPException(
                    503, "수집이 가능해진 뒤 이벤트를 켤 수 있습니다."
                ) from None
            data.update(cursor_epoch=checkpoint["cursor_epoch"], after_cursor=checkpoint["cursor"])
        return connection_call("POST", "/events/settings", data)

    from dot_plugin.control import TunnelDecision

    @app.post("/admin/api/tunnel/decision")
    def tunnel_decision(body: TunnelDecision, current: Annotated[dict, Depends(authenticated)]):
        return connection_call("POST", "/tunnel/decision", body.model_dump(exclude_none=True))

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
            owner.revoke(digest(request.cookies.get(cookie_name(request), "")))
            sessions.pop(request.cookies.get(cookie_name(request)), None)
        response.delete_cookie(
            cookie_name(request),
            secure=not is_local(request),
            httponly=True,
            samesite="strict",
            path=COOKIE_PATH,
        )
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
                409, "화면이 오래되었습니다. 새 화면을 받은 뒤 다시 시도하세요."
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
            changed = True
            with lock:
                if body.name == "prepare":
                    changed = device.prepare()
                elif body.name == "configure":
                    changed = device.configure()
                elif body.name == "open-store":
                    changed = device.open_store()
                elif body.name == "bootstrap":
                    device.bootstrap()
                elif body.name == "open-kakao":
                    device.open_kakao()
                elif body.name == "keyboard":
                    device.enable_keyboard()
                elif body.name == "approve":
                    device.approve(body.phone_active)
                elif body.name in ("phone-active", "phone-lost"):
                    device.record_phone(body.name == "phone-active")
                if body.name in ("setup-check", "setup-poll", "prepare", "configure", "bootstrap"):
                    setup_snapshot = device.setup_status()
                if body.name in (
                    "setup-check",
                    "session-check",
                    "approve",
                    "phone-active",
                    "phone-lost",
                ):
                    session_snapshot = device.session_status()
                    snapshot_invalidated = False
            message = {
                "prepare": "Aurora가 준비되었습니다. 시작 안내와 익명 로그인을 마치면 카카오톡 페이지가 열립니다."
                if changed
                else "기존 설치를 유지했습니다. 다음 설정 단계를 진행하세요.",
                "configure": "구성 요소를 설치했습니다. 카카오톡을 열고 ‘다른 기기와 함께 사용’을 선택해 로그인하세요."
                if changed
                else "기존 기기 등록과 수집 승인을 유지했습니다.",
                "open-store": "Aurora에서 카카오톡 페이지를 열었습니다. 설치를 누르세요."
                if changed
                else "Aurora를 열었습니다. 시작 안내와 익명 로그인을 마치면 카카오톡 페이지가 열립니다.",
                "setup-check": "설정 상태를 새로고침했습니다.",
                "setup-poll": "설정 상태를 새로고침했습니다.",
                "bootstrap": "설치가 완료되었습니다. 카카오톡을 열고 ‘다른 기기와 함께 사용’을 선택해 로그인하세요.",
                "open-kakao": "카카오톡을 열었습니다.",
                "keyboard": "키보드를 연결했습니다. 태블릿의 입력란을 선택하세요.",
                "approve": "휴대폰 로그인 유지를 확인했습니다. 메시지 수집을 시작합니다.",
                "session-check": "현재 화면과 로그인 확인 기록을 점검했습니다.",
                "phone-active": "휴대폰을 직접 확인한 시간을 갱신했습니다.",
                "phone-lost": "휴대폰 로그아웃을 기록하고 Iris 수집 승인을 취소했습니다.",
            }[body.name]
            job.update(state="done", message=message)
        except Exception as exc:  # noqa: BLE001 — isolate background jobs without leaking credentials
            # Login UI dumps, input strings, filesystem paths and exception bodies stay private.
            fallback = (
                "수집 승인에 실패했습니다. 태블릿 로그인과 휴대폰 로그인을 확인하세요."
                if body.name in ("approve", "phone-active")
                else "수집을 중지하지 못했습니다. 기기 연결과 Iris 수집 상태를 확인하세요."
                if body.name == "phone-lost"
                else "작업에 실패했습니다. redroid 연결, APK 파일과 설치 상태를 확인하세요."
            )
            job.update(state="failed", message=device_message(exc, fallback))

    @app.post("/admin/api/action", status_code=202)
    def action(body: Action, current: Annotated[dict, Depends(authenticated)]):
        if body.name in ("approve", "phone-active") and not body.phone_active:
            raise HTTPException(422, "휴대폰의 기존 로그인이 유지되는지 직접 확인하세요.")
        with session_lock:
            if job["state"] == "running":
                raise HTTPException(409, "device_busy")
            invalidate_snapshot()
            job.update(state="running", action=body.name, message="작업 중…")
            pool.submit(run_action, body)
        return {"accepted": True}

    return app
