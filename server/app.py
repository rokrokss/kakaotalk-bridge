import asyncio
import hmac
import sqlite3
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from server.config import Settings
from server.models import Batch, DeviceStatus, Heartbeat, Observation
from server.store import Conflict, Store


class BodyLimit:
    def __init__(self, app, maximum=1024 * 1024):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, length = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            length += len(message.get("body", b""))
            if length > self.maximum:
                return await JSONResponse({"error": "body_too_large"}, 413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None):
    config = settings or Settings.from_env()
    store = Store(config.db_path)

    @asynccontextmanager
    async def lifespan(app):
        async def maintenance():
            while True:
                try:
                    await asyncio.to_thread(store.prune, config.retention_days)
                except sqlite3.Error:
                    # No SQL exception/body logging; expose failure through readiness/status.
                    app.state.maintenance_failed = True
                else:
                    app.state.maintenance_failed = False
                await asyncio.sleep(3600)

        task = asyncio.create_task(maintenance())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(
        title="KakaoTalk Bridge",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.maintenance_failed = False
    app.add_middleware(BodyLimit)

    def auth(expected):
        def verify(authorization: str = Header(default="")):
            if not hmac.compare_digest(authorization.encode(), f"Bearer {expected}".encode()):
                raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})

        return verify

    ingest_auth, read_auth, device_auth = [
        auth(t) for t in (config.ingest_token, config.read_token, config.device_token)
    ]

    def check_device(device_id):
        if device_id != config.device_id:
            raise HTTPException(403, "device_not_enrolled")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"error": "invalid_request"}, 422)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        return JSONResponse({"error": "storage_unavailable"}, 503)

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        if app.state.maintenance_failed:
            raise HTTPException(503, "maintenance_failed")
        return {"status": "ready"}

    @app.post("/internal/v1/observations:batch", dependencies=[Depends(ingest_auth)])
    def ingest(batch: Batch):
        results = []
        for index, raw in enumerate(batch.events):
            # Index correlation works even when an invalid event ID cannot be echoed.
            try:
                event = Observation.model_validate(raw)
                check_device(event.device_id)
                bridge = store.status(config.heartbeat_timeout)["bridge"]
                if not bridge or bridge["stale"] or not bridge.get("secondary_login_confirmed"):
                    raise HTTPException(423, "secondary_login_confirmation_required")
                if event.source != bridge.get("source", "notification"):
                    raise HTTPException(423, "collector_source_mismatch")
                if event.source == "iris_db" and (
                    not bridge["listener_connected"]
                    or str(event.enrollment_epoch) != bridge["enrollment_epoch"]
                    or event.database_ref.database_id != bridge.get("database_id")
                ):
                    raise HTTPException(423, "iris_confirmation_mismatch")
                result = store.ingest(event)
                results.append({"index": index, "event_id": str(event.event_id), "status": result})
            except ValidationError:
                results.append({"index": index, "status": "rejected", "reason": "invalid_event"})
            except Conflict as exc:
                results.append({"index": index, "status": "rejected", "reason": str(exc)})
        return {"results": results}

    @app.get("/internal/v1/iris/cursor", dependencies=[Depends(ingest_auth)])
    def iris_cursor(epoch: UUID):
        return store.iris_progress(config.device_id, str(epoch))

    @app.post("/internal/v1/heartbeat", dependencies=[Depends(ingest_auth)])
    def heartbeat(body: Heartbeat):
        check_device(body.device_id)
        store.status_update("bridge", body.model_dump(mode="json"), config.heartbeat_timeout)
        return {"status": "committed"}

    @app.post("/internal/v1/device-status", dependencies=[Depends(device_auth)])
    def device_status(body: DeviceStatus):
        check_device(body.device_id)
        store.status_update("device", body.model_dump(mode="json"))
        return {"status": "committed"}

    @app.get("/v1/status", dependencies=[Depends(read_auth)])
    def status():
        return {
            **store.status(config.heartbeat_timeout),
            "maintenance_failed": app.state.maintenance_failed,
        }

    @app.get("/v1/checkpoint", dependencies=[Depends(read_auth)])
    def checkpoint():
        return store.checkpoint()

    @app.get("/v1/messages", dependencies=[Depends(read_auth)])
    def messages(
        after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        conversation_ref: str | None = Query(None, min_length=1, max_length=256),
    ):
        return {
            **store.messages(after, limit, conversation_ref=conversation_ref),
            "coverage": status()["coverage"],
        }

    @app.get("/v1/search", dependencies=[Depends(read_auth)])
    def search(
        q: str = Query(min_length=1, max_length=256),
        after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        return {**store.messages(after, limit, q), "coverage": status()["coverage"]}

    @app.get("/v1/conversations", dependencies=[Depends(read_auth)])
    def conversations(after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        return store.conversations(after, limit)

    return app
