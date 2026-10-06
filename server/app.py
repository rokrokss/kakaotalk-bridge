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
from server.models import Batch, DeviceStatus, Heartbeat, MetadataBatch, Observation
from server.outgoing import Claim, Outgoing, SendError, SendMessage, SendResult
from server.queries import Queries
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
    queries = Queries(store)
    outgoing = Outgoing(store, config)

    @asynccontextmanager
    async def lifespan(app):
        async def maintenance():
            while True:
                try:
                    await asyncio.to_thread(store.prune, config.retention_days)
                    with store.connect() as db:
                        outgoing.expire(db)
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
    app.state.outgoing = outgoing
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

    def send_auth(authorization: str = Header(default="")):
        if not config.send_token:
            raise HTTPException(503, "sending_not_configured")
        auth(config.send_token)(authorization)

    @app.exception_handler(SendError)
    async def send_error(request, exc):
        return JSONResponse({"error": exc.reason}, exc.code)

    @app.post("/v1/outgoing", dependencies=[Depends(send_auth)])
    def send_message(body: SendMessage):
        return outgoing.enqueue(body)

    @app.get("/v1/outgoing/{request_id}", dependencies=[Depends(send_auth)])
    def send_status(request_id: UUID):
        return outgoing.status(str(request_id))

    @app.post("/internal/v1/outgoing/claim", dependencies=[Depends(ingest_auth)])
    def claim_send(body: Claim):
        return outgoing.claim(body)

    @app.post("/internal/v1/outgoing/{request_id}/result", dependencies=[Depends(ingest_auth)])
    def complete_send(request_id: UUID, body: SendResult):
        return outgoing.complete(str(request_id), body)

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

    def metadata_gate(epoch, database_id=None):
        bridge = store.status(config.heartbeat_timeout)["bridge"]
        if (
            not bridge
            or bridge["stale"]
            or not bridge.get("secondary_login_confirmed")
            or not bridge.get("listener_connected")
            or bridge.get("source") != "iris_db"
            or bridge["enrollment_epoch"] != str(epoch)
        ):
            raise HTTPException(423, "iris_confirmation_mismatch")
        if database_id is not None and bridge.get("database_id") != database_id:
            raise HTTPException(423, "iris_confirmation_mismatch")

    @app.get("/internal/v1/iris/metadata-targets", dependencies=[Depends(ingest_auth)])
    def metadata_targets(epoch: UUID):
        metadata_gate(epoch)
        return {"items": queries.metadata_targets(config.device_id, str(epoch))}

    @app.post("/internal/v1/iris/metadata", dependencies=[Depends(ingest_auth)])
    def metadata_update(body: MetadataBatch):
        check_device(body.device_id)
        metadata_gate(body.enrollment_epoch, body.database_id)
        try:
            return queries.metadata_update(
                body.device_id, str(body.enrollment_epoch), body.database_id, body.items
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

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
            "identity_metadata": queries.metadata_status(),
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

    def query_result(fn, **params):
        try:
            return {**fn(**params), "coverage": status()["coverage"]}
        except (ValueError, OverflowError) as exc:
            reason = (
                str(exc)
                if str(exc)
                in {
                    "invalid_or_expired_query_cursor",
                    "message_not_found_or_expired",
                    "conversation_unresolved",
                    "invalid_time_range",
                    "timezone_required",
                }
                else "invalid_query"
            )
            raise HTTPException(400, reason) from None

    @app.get("/v2/messages", dependencies=[Depends(read_auth)])
    def query_messages(
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        q: str | None = Query(None, min_length=1, max_length=256),
        conversation_ref: str | None = Query(None, min_length=1, max_length=256),
        sender_ref: str | None = Query(None, min_length=1, max_length=256),
        sender_name: str | None = Query(None, min_length=1, max_length=256),
        since: str | None = Query(None, max_length=40),
        until: str | None = Query(None, max_length=40),
        include_mine: bool = True,
    ):
        return query_result(
            queries.messages,
            limit=limit,
            cursor=cursor,
            q=q,
            conversation_ref=conversation_ref,
            sender_ref=sender_ref,
            sender_name=sender_name,
            since=since,
            until=until,
            include_mine=include_mine,
        )

    @app.get("/v2/conversations", dependencies=[Depends(read_auth)])
    def query_conversations(
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None, max_length=2048),
        q: str | None = Query(None, min_length=1, max_length=256),
    ):
        return query_result(queries.conversations, limit=limit, cursor=cursor, q=q)

    @app.get("/v2/context", dependencies=[Depends(read_auth)])
    def query_context(
        message_id: int = Query(ge=1),
        before: int = Query(5, ge=0, le=30),
        after: int = Query(5, ge=0, le=30),
    ):
        return query_result(queries.context, message_id=message_id, before=before, after=after)

    return app
