"""Durable, single-attempt text sends. An ambiguous attempt is never retried."""

import hashlib
import json
import time
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: Annotated[
        str, Field(description="A new UUID per intended message; reuse on retry.")
    ]
    conversation_ref: Annotated[str, Field(min_length=1, max_length=256)]
    text: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("request_id")
    @classmethod
    def valid_id(cls, value):
        return str(UUID(value))

    @field_validator("text")
    @classmethod
    def valid_text(cls, value):
        if not value.strip() or "\0" in value or len(value.encode("utf-16-le")) > 8000:
            raise ValueError("invalid_text")
        return value


class SendStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str

    _valid_id = field_validator("request_id")(SendMessage.valid_id.__func__)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enrollment_epoch: UUID
    account_ref: UUID
    database_id: str = Field(min_length=1, max_length=128)


class SendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["submitted", "failed", "unknown"]


class SendError(Exception):
    def __init__(self, reason, code=409):
        self.reason, self.code = reason, code


class Outgoing:
    def __init__(self, store, config):
        self.store, self.config = store, config
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS outgoing (
                    request_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    conversation_ref TEXT NOT NULL, device_id TEXT NOT NULL,
                    epoch TEXT NOT NULL, database_id TEXT NOT NULL, chat_id TEXT NOT NULL,
                    text TEXT, status TEXT NOT NULL, reason TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL, account_ref TEXT
                );
                CREATE INDEX IF NOT EXISTS outgoing_pending ON outgoing(status, created_at);
                CREATE INDEX IF NOT EXISTS outgoing_created ON outgoing(created_at);
            """)

    @staticmethod
    def expire(db):
        # Clear content on expiry; retain IDs/digests to reject late duplicate requests.
        db.execute(
            "UPDATE outgoing SET status='failed', reason='queue_expired', text=NULL, updated_at=? "
            "WHERE status='queued' AND created_at<?",
            (time.time(), time.time() - 120),
        )
        db.execute(
            "UPDATE outgoing SET status='unknown', reason='attempt_result_unavailable', "
            "updated_at=? WHERE status='dispatching' AND updated_at<?",
            (time.time(), time.time() - 120),
        )

    def gate(self, db):
        row = db.execute("SELECT * FROM statuses WHERE kind='bridge'").fetchone()
        bridge = json.loads(row["body"]) if row else {}
        if (
            not row
            or time.time() - datetime.fromisoformat(row["received_at"]).timestamp()
            > self.config.heartbeat_timeout
            or bridge.get("device_id") != self.config.device_id
            or bridge.get("source") != "iris_db"
            or not bridge.get("listener_connected")
            or not bridge.get("secondary_login_confirmed")
            or not bridge.get("supports_message_send")
            or not bridge.get("account_ref")
        ):
            raise SendError("sending_unavailable_confirm_login_and_upgrade_iris", 423)
        return bridge

    @staticmethod
    def view(row):
        return {
            key: row[key]
            for key in (
                "request_id",
                "conversation_ref",
                "status",
                "reason",
                "created_at",
                "updated_at",
            )
        } | {"delivery_confirmed": False}

    def enqueue(self, body):
        digest = hashlib.sha256(
            json.dumps([body.conversation_ref, body.text], ensure_ascii=False).encode()
        ).hexdigest()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.expire(db)
            prior = db.execute(
                "SELECT * FROM outgoing WHERE request_id=?", (body.request_id,)
            ).fetchone()
            if prior:
                if prior["digest"] != digest:
                    raise SendError("request_id_conflict")
                return self.view(prior)
            bridge = self.gate(db)
            if bridge.get("notification_reply_ready") is False:
                # Unknown does not block: Iris checks the referer again before sending.
                raise SendError("sending_unavailable_until_kakaotalk_notification", 423)
            target = db.execute(
                "SELECT * FROM message_lookup WHERE conversation_ref=? "
                "ORDER BY message_id DESC LIMIT 1",
                (body.conversation_ref,),
            ).fetchone()
            if not target or any(
                target[key] != value
                for key, value in {
                    "device_id": self.config.device_id,
                    "epoch": bridge["enrollment_epoch"],
                    "database_id": bridge["database_id"],
                    "source": "iris_db",
                }.items()
            ):
                raise SendError("conversation_not_in_current_enrollment")
            if (
                db.execute(
                    "SELECT count(*) FROM outgoing WHERE created_at>?", (time.time() - 60,)
                ).fetchone()[0]
                >= 30
            ):
                raise SendError("send_rate_limited", 429)
            instant = time.time()
            db.execute(
                "INSERT INTO outgoing(request_id,digest,conversation_ref,device_id,epoch,"
                "database_id,chat_id,text,status,reason,created_at,updated_at,account_ref) "
                "VALUES(?,?,?,?,?,?,?,?,'queued',NULL,?,?,?)",
                (
                    body.request_id,
                    digest,
                    body.conversation_ref,
                    target["device_id"],
                    target["epoch"],
                    target["database_id"],
                    target["chat_id"],
                    body.text,
                    instant,
                    instant,
                    bridge["account_ref"],
                ),
            )
            return self.view(
                db.execute(
                    "SELECT * FROM outgoing WHERE request_id=?", (body.request_id,)
                ).fetchone()
            )

    def status(self, request_id):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.expire(db)
            row = db.execute("SELECT * FROM outgoing WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                raise SendError("send_request_not_found", 404)
            return self.view(row)

    def claim(self, body):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.expire(db)
            bridge = self.gate(db)
            if (
                str(body.enrollment_epoch) != bridge["enrollment_epoch"]
                or body.database_id != bridge["database_id"]
                or str(body.account_ref) != bridge["account_ref"]
            ):
                raise SendError("send_enrollment_mismatch", 423)
            db.execute(
                "UPDATE outgoing SET status='failed',reason='enrollment_changed',text=NULL "
                "WHERE status='queued' AND (device_id!=? OR epoch!=? OR database_id!=? "
                "OR account_ref!=?)",
                (
                    self.config.device_id,
                    str(body.enrollment_epoch),
                    body.database_id,
                    str(body.account_ref),
                ),
            )
            row = db.execute(
                "SELECT * FROM outgoing WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return {"item": None}
            # Commit before contacting Android. Crashes/lost responses never requeue an attempt.
            db.execute(
                "UPDATE outgoing SET status='dispatching',text=NULL,updated_at=? WHERE request_id=?",
                (time.time(), row["request_id"]),
            )
            return {
                "item": {
                    key: row[key]
                    for key in (
                        "request_id",
                        "chat_id",
                        "text",
                        "epoch",
                        "database_id",
                        "account_ref",
                    )
                }
            }

    def complete(self, request_id, result):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM outgoing WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                raise SendError("send_request_not_found", 404)
            if row["status"] not in {"dispatching", "unknown", result.status}:
                raise SendError("invalid_send_transition")
            db.execute(
                "UPDATE outgoing SET status=?, reason=?,text=NULL,updated_at=? WHERE request_id=?",
                (
                    result.status,
                    "delivery_not_confirmed" if result.status != "failed" else "device_rejected",
                    time.time(),
                    request_id,
                ),
            )
        return self.status(request_id)
