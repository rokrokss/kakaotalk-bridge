"""HTTPS-only administrator sessions and finite Android controls; no shell endpoint."""

import hmac
import json
import secrets
import subprocess
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
from webui.device import Android

COOKIE = "__Host-kakao-admin"
STATIC = Path(__file__).with_name("static")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    token: Annotated[str, Field(min_length=32, max_length=256)]


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
        return {k: data[k] for k in ("state", "warnings", "coverage")}


ERRORS = {
    "screen_unavailable": "화면을 가져오지 못했습니다. redroid 부팅 상태를 확인하세요.",
    "keyboard_unavailable": "‘입력기 연결’을 누르고 카카오톡 입력칸을 선택하세요. 설치 전이라면 설치 관리에서 먼저 설치하세요.",
    "focus_kakao_input": "카카오톡의 입력칸을 먼저 클릭하세요.",
    "input_result_unknown": "입력 결과를 확인하지 못했습니다. 화면을 확인한 뒤 필요할 때 다시 입력하세요.",
    "kakao_not_installed": "카카오톡 설치를 먼저 완료하세요.",
}


def create_app(admin_token=None, android=None, status_provider=None, session_ttl=1800):
    token = admin_token or secret("ADMIN_TOKEN")
    if len(token) < 32:
        raise ValueError("Admin token must contain at least 32 characters")
    device = android or Android()
    status_provider = status_provider or collector_status
    lock = threading.Lock()
    session_lock = threading.Lock()
    sessions = {}
    failures = deque()
    pool = ThreadPoolExecutor(max_workers=1)
    job = {"state": "idle", "action": None, "message": ""}
    session_snapshot = None
    snapshot_invalidated = True

    @asynccontextmanager
    async def lifespan(app):
        yield
        pool.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
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
            session = sessions.get(key)
            if session is None or session["expires"] <= time.monotonic():
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
                ERRORS.get(str(exc), "기기 작업에 실패했습니다. 연결 및 설치 상태를 확인하세요."),
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
                raise HTTPException(429, "잠시 후 다시 시도하세요.")
            if not hmac.compare_digest(body.token.encode(), token.encode()):
                failures.append(now)
                raise HTTPException(401, "관리자 키가 올바르지 않습니다.")
            key, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            # Only one administrator session controls the tablet at a time.
            sessions.clear()
            sessions[key] = {"csrf": csrf, "expires": now + session_ttl, "frames": {}}
        response.set_cookie(
            COOKIE,
            key,
            max_age=session_ttl,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return {"csrf": csrf, "expires_in": session_ttl}

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
            "job": dict(job),
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
            raise HTTPException(409, "화면이 오래되었습니다. 새 화면을 받은 뒤 다시 조작하세요.")
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
        nonlocal session_snapshot, snapshot_invalidated
        try:
            with lock:
                if body.name == "bootstrap":
                    device.bootstrap()
                elif body.name == "open-kakao":
                    device.open_kakao()
                elif body.name == "keyboard":
                    device.enable_keyboard()
                elif body.name == "login-check":
                    device.login_check()
                elif body.name == "confirm-secondary":
                    device.confirm(body.phone_active, body.tablet_active)
                elif body.name in ("phone-active", "phone-lost"):
                    device.record_phone(body.name == "phone-active")
                if body.name in (
                    "session-check",
                    "login-check",
                    "confirm-secondary",
                    "phone-active",
                    "phone-lost",
                ):
                    session_snapshot = device.session_status()
                    snapshot_invalidated = False
            message = {
                "bootstrap": "설치했습니다. 카카오톡을 열어 로그인 옵션을 검사하세요.",
                "open-kakao": "카카오톡을 열었습니다.",
                "keyboard": "입력기를 연결했습니다. 태블릿의 입력칸을 선택하세요.",
                "login-check": "보조 로그인 옵션 검사를 통과했습니다. 이제 화면에서 로그인하세요.",
                "confirm-secondary": "양쪽 로그인을 확인했습니다. 메시지 수집을 시작합니다.",
                "session-check": "현재 화면과 로그인 확인 기록을 검사했습니다.",
                "phone-active": "핸드폰에서 직접 확인한 시각을 갱신했습니다.",
                "phone-lost": "핸드폰 로그아웃 보고를 기록하고 Iris 수집 승인을 해제했습니다.",
            }[body.name]
            job.update(state="done", message=message)
        except Exception:  # noqa: BLE001 — isolate background jobs without leaking credentials
            # Login UI dumps, input strings, filesystem paths and exception bodies stay private.
            message = (
                "보조 로그인 확인 실패. ‘다른 기기와 함께 사용’ 선택 여부, 검사 유효시간 및 양쪽 세션을 확인하세요."
                if body.name in ("login-check", "confirm-secondary", "phone-active")
                else "수집 중단을 완료하지 못했습니다. 기기 연결과 Iris 수집 상태를 확인하세요."
                if body.name == "phone-lost"
                else "작업에 실패했습니다. redroid 연결, APK 배치 및 설치 상태를 확인하세요."
            )
            job.update(state="failed", message=message)

    @app.post("/admin/api/action", status_code=202)
    def action(body: Action, current: Annotated[dict, Depends(authenticated)]):
        if body.name == "confirm-secondary" and not (body.phone_active and body.tablet_active):
            raise HTTPException(422, "핸드폰과 redroid 양쪽 로그인을 직접 확인해야 합니다.")
        if body.name == "phone-active" and not body.phone_active:
            raise HTTPException(422, "핸드폰의 기존 로그인을 직접 확인해야 합니다.")
        with session_lock:
            if job["state"] == "running":
                raise HTTPException(409, "device_busy")
            invalidate_snapshot()
            job.update(state="running", action=body.name, message="작업 중…")
            pool.submit(run_action, body)
        return {"accepted": True}

    return app
