import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server import name_history
from server.models import Observation
from server.queries import INDEX_SQL, initialize


def now():
    return datetime.now(UTC).isoformat()


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported database schema; restore a compatible backup")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL, epoch TEXT NOT NULL, event_id TEXT NOT NULL,
                    source_seq INTEGER NOT NULL, digest TEXT NOT NULL,
                    received_at TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(device_id, epoch, event_id), UNIQUE(device_id, epoch, source_seq)
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
                    item_ordinal INTEGER NOT NULL, title TEXT, sender TEXT, body TEXT NOT NULL,
                    source_time INTEGER, observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
                    notification_key TEXT NOT NULL, truncated INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS candidate_observation ON candidates(observation_id);
                CREATE TABLE IF NOT EXISTS statuses (
                    kind TEXT PRIMARY KEY, received_at TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
                    ended_at TEXT, reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            db.execute(
                "INSERT OR IGNORE INTO metadata VALUES('cursor_epoch',?)", (str(uuid.uuid4()),)
            )
            initialize(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, event: Observation):
        serialized = json.dumps(event.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        canonical = event.model_dump(mode="json")
        if event.source == "notification":
            canonical.pop("database_ref")
        if event.source == "iris_db":
            canonical.pop("observed_at")  # Replay keeps the first receipt; row identity is stable.
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        identity = (event.device_id, str(event.enrollment_epoch), str(event.event_id))
        received = now()
        with self.connect() as db:
            # Serialize check + write to avoid competing retries racing on the unique constraint.
            db.execute("BEGIN IMMEDIATE")
            if event.source == "iris_db":
                key = f"iris:{event.device_id}:{event.enrollment_epoch}"
                existing = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
                progress = json.loads(existing[0]) if existing else None
                if progress and progress["database_id"] != event.database_ref.database_id:
                    raise Conflict("iris_database_changed_requires_new_epoch")
            prior = db.execute(
                "SELECT digest FROM observations WHERE device_id=? AND epoch=? AND event_id=?",
                identity,
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise Conflict("event_id_conflict")
                return "duplicate"
            if db.execute(
                "SELECT 1 FROM observations WHERE device_id=? AND epoch=? AND source_seq=?",
                (*identity[:2], event.source_seq),
            ).fetchone():
                raise Conflict("source_seq_conflict")
            row = db.execute(
                "INSERT INTO observations(device_id,epoch,event_id,source_seq,digest,received_at,body) "
                "VALUES(?,?,?,?,?,?,?)",
                (*identity, event.source_seq, digest, received, serialized),
            ).lastrowid
            p = event.payload
            if event.kind != "removed" and not p.is_group_summary:
                items = [(m.sender, m.body, m.timestamp) for m in p.messages]
                if not items:
                    body = p.big_text or p.text or "\n".join(p.text_lines)
                    items = [(None, body, None)] if body else []
                for ordinal, (sender, body, timestamp) in enumerate(items):
                    db.execute(
                        "INSERT INTO candidates(observation_id,item_ordinal,title,sender,body,"
                        "source_time,observed_at,received_at,notification_key,truncated) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            row,
                            ordinal,
                            p.title,
                            sender,
                            body,
                            timestamp,
                            event.observed_at.isoformat(),
                            received,
                            event.notification_key,
                            p.truncated,
                        ),
                    )
            db.execute(INDEX_SQL + " WHERE c.observation_id=?", (row,))
            name_history.index_new(db, observation_id=row)
            if event.source == "iris_db":
                cursor = max(event.source_seq, progress["after"] if progress else 0)
                db.execute(
                    "INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (
                        key,
                        json.dumps(
                            {"after": cursor, "database_id": event.database_ref.database_id}
                        ),
                    ),
                )
        # Context exit committed before an ACK can be returned.
        return "committed"

    def iris_progress(self, device_id, epoch):
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE key=?", (f"iris:{device_id}:{epoch}",)
            ).fetchone()
        return json.loads(row[0]) if row else {"after": 0, "database_id": None}

    def status_update(self, kind, payload, timeout=180):
        received = now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "bridge":
                previous = db.execute("SELECT * FROM statuses WHERE kind='bridge'").fetchone()
                gap_reason = None
                if previous:
                    old = json.loads(previous["body"])
                    age = datetime.fromisoformat(received) - datetime.fromisoformat(
                        previous["received_at"]
                    )
                    if age.total_seconds() > timeout:
                        db.execute(
                            "INSERT INTO gaps(started_at,ended_at,reason) VALUES(?,?,?)",
                            (previous["received_at"], received, "heartbeat_gap"),
                        )
                    if old["enrollment_epoch"] != payload["enrollment_epoch"]:
                        gap_reason = "enrollment_changed"
                    elif payload["last_source_seq"] < old["last_source_seq"]:
                        gap_reason = "sequence_regressed_restore_requires_new_epoch"
                    elif payload["dropped_events"] > old.get("dropped_events", 0):
                        gap_reason = "bridge_storage_loss"
                else:
                    gap_reason = "collection_started_history_unknown"
                if gap_reason:
                    db.execute(
                        "INSERT INTO gaps(started_at,ended_at,reason) VALUES(?,?,?)",
                        (received, received, gap_reason),
                    )
                if not payload["listener_connected"]:
                    if not db.execute(
                        "SELECT 1 FROM gaps WHERE ended_at IS NULL AND reason='listener_disconnected'"
                    ).fetchone():
                        db.execute(
                            "INSERT INTO gaps(started_at,reason) VALUES(?,?)",
                            (received, "listener_disconnected"),
                        )
                else:
                    db.execute(
                        "UPDATE gaps SET ended_at=? WHERE ended_at IS NULL AND reason='listener_disconnected'",
                        (received,),
                    )
            db.execute(
                "INSERT INTO statuses VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET "
                "received_at=excluded.received_at,body=excluded.body",
                (kind, received, json.dumps(payload)),
            )

    def status(self, timeout=180):
        with self.connect() as db:
            states = {}
            for row in db.execute("SELECT * FROM statuses"):
                age = (
                    datetime.now(UTC) - datetime.fromisoformat(row["received_at"])
                ).total_seconds()
                states[row["kind"]] = {
                    **json.loads(row["body"]),
                    "received_at": row["received_at"],
                    "stale": age > timeout,
                }
            gaps = [dict(r) for r in db.execute("SELECT * FROM gaps ORDER BY id DESC LIMIT 100")]
            last = db.execute("SELECT max(received_at) FROM observations").fetchone()[0]
            floor = db.execute("SELECT value FROM metadata WHERE key='pruned_cursor'").fetchone()
            cursor_epoch = db.execute(
                "SELECT value FROM metadata WHERE key='cursor_epoch'"
            ).fetchone()[0]
        bridge = states.get("bridge")
        collecting = bridge and not bridge["stale"] and bridge["listener_connected"]
        secondary_confirmed = bool(
            bridge and not bridge["stale"] and bridge.get("secondary_login_confirmed")
        )
        warnings = []
        if not secondary_confirmed:
            warnings.append("secondary_login_confirmation_required")
        if bridge:
            if bridge.get("quarantine_depth", 0):
                warnings.append("quarantined_events")
            if bridge.get("dropped_events", 0):
                warnings.append("bridge_reported_data_loss")
            if (
                bridge.get("oldest_pending_at")
                and (
                    datetime.now(UTC) - datetime.fromisoformat(bridge["oldest_pending_at"])
                ).total_seconds()
                > 72 * 3600
            ):
                warnings.append("outbox_older_than_72h")
        if bridge and bridge["stale"]:
            gaps.insert(
                0,
                {
                    "started_at": bridge["received_at"],
                    "ended_at": None,
                    "reason": "heartbeat_stale",
                },
            )
        return {
            "state": "collecting_partial" if collecting and not warnings else "needs_attention",
            "warnings": warnings,
            "mode": "passive",
            "device": states.get("device"),
            "bridge": bridge,
            "last_observation_received_at": last,
            "coverage": {
                "secondary_login_operator_confirmed": secondary_confirmed,
                "phone_session_monitoring": False,
                "cursor_epoch": cursor_epoch,
                "complete": False,
                "scope": "redroid_local_database_rows"
                if bridge and bridge.get("source") == "iris_db"
                else "posted_notifications_only",
                "login_verified": False,
                "read_receipt_preservation_verified": False,
                "possible_duplicates": True,
                "gaps": gaps,
                "pruned_through_cursor": int(floor[0]) if floor else 0,
            },
        }

    def checkpoint(self):
        with self.connect() as db:
            db.execute("BEGIN")
            cursor = db.execute(
                "SELECT seq FROM sqlite_sequence WHERE name='candidates'"
            ).fetchone()
            epoch = db.execute("SELECT value FROM metadata WHERE key='cursor_epoch'").fetchone()[0]
            floor = db.execute("SELECT value FROM metadata WHERE key='pruned_cursor'").fetchone()
            return {
                "cursor": int(cursor[0]) if cursor else 0,
                "cursor_epoch": epoch,
                "pruned_through_cursor": int(floor[0]) if floor else 0,
            }

    def messages(self, after=0, limit=50, query=None, conversation_ref=None):
        where = "c.id > ?"
        params = [after]
        if query is not None:
            # Literal substring, not user-provided SQL/FTS grammar.
            where += " AND instr(lower(c.body),lower(?)) > 0"
            params.append(query)
        if conversation_ref is not None:
            where += " AND (o.device_id || ':' || o.epoch || ':' || json_extract(o.body,'$.database_ref.chat_id')) = ?"
            params.append(conversation_ref)
        with self.connect() as db:
            rows = db.execute(
                "SELECT c.*,o.event_id,o.body AS observation_body,o.epoch AS observation_epoch,o.device_id FROM candidates c JOIN observations o ON o.id=c.observation_id "
                f"WHERE {where} ORDER BY c.id LIMIT ?",
                (*params, limit + 1),
            ).fetchall()
        items = [dict(r) for r in rows[:limit]]
        for item in items:
            observation = json.loads(item.pop("observation_body"))
            epoch = item.pop("observation_epoch")
            device_id = item.pop("device_id")
            ref = observation.get("database_ref")
            item.update(
                source="notification",
                completeness="notification_only",
                ambiguity=True,
                conversation_ref=None,
            )
            if ref:
                item.update(
                    source="iris_db",
                    completeness="local_database_row",
                    ambiguity=False,
                    conversation_ref=f"{device_id}:{epoch}:{ref['chat_id']}",
                    database_ref=ref,
                )
            item["truncated"] = bool(item["truncated"])
        return {
            "items": items,
            "next_cursor": items[-1]["id"] if items else after,
            "has_more": len(rows) > limit,
        }

    def conversations(self, after=0, limit=50):
        page = self.messages(after, limit)
        return {
            "items": [
                {
                    "observation_cursor": r["id"],
                    "title": r["title"],
                    "notification_key": r["notification_key"],
                    "conversation_ref": r["conversation_ref"],
                    "identity_confidence": "database_id"
                    if r["source"] == "iris_db"
                    else "unresolved",
                }
                for r in page["items"]
            ],
            "next_cursor": page["next_cursor"],
            "has_more": page["has_more"],
            "scope": "observed_conversations_may_repeat",
        }

    def prune(self, days):
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            highest = db.execute(
                "SELECT max(id) FROM candidates WHERE received_at<?", (cutoff,)
            ).fetchone()[0]
            if highest:
                db.execute(
                    "INSERT INTO metadata VALUES('pruned_cursor',?) ON CONFLICT(key) DO UPDATE SET "
                    "value=CAST(max(CAST(value AS INTEGER),CAST(excluded.value AS INTEGER)) AS TEXT)",
                    (str(highest),),
                )
            db.execute("DELETE FROM observations WHERE received_at<?", (cutoff,))
            db.execute(
                "DELETE FROM identities WHERE NOT EXISTS (SELECT 1 FROM message_lookup m WHERE m.conversation_ref=identities.conversation_ref AND m.sender_ref=identities.sender_ref)"
            )
            db.execute(
                "DELETE FROM rooms WHERE NOT EXISTS (SELECT 1 FROM message_lookup m WHERE m.conversation_ref=rooms.conversation_ref)"
            )
            db.execute("DELETE FROM gaps WHERE ended_at IS NOT NULL AND ended_at<?", (cutoff,))
        with self.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
