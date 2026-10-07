"""Human-facing queries. Event delivery continues to use the separate v1 ingestion cursor."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime

from server import name_history

INDEX_SQL = """
INSERT OR IGNORE INTO message_lookup
SELECT c.id, o.device_id, o.epoch,
 json_extract(o.body,'$.database_ref.database_id'),
 o.device_id || ':' || o.epoch || ':' || json_extract(o.body,'$.database_ref.chat_id'),
 o.device_id || ':' || o.epoch || ':' || json_extract(o.body,'$.database_ref.sender_id'),
 json_extract(o.body,'$.database_ref.chat_id'), json_extract(o.body,'$.database_ref.sender_id'),
 CASE WHEN c.source_time > 0 THEN c.source_time END,
 json_extract(o.body,'$.database_ref.is_mine'), json_extract(o.body,'$.database_ref.message_type'),
 json_extract(o.body,'$.source')
FROM candidates c JOIN observations o ON o.id=c.observation_id
"""


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS message_lookup (
      message_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
      device_id TEXT, epoch TEXT, database_id TEXT, conversation_ref TEXT, sender_ref TEXT,
      chat_id TEXT, user_id TEXT, sent_ms INTEGER, is_mine INTEGER, message_type TEXT, source TEXT
    );
    CREATE INDEX IF NOT EXISTS lookup_time ON message_lookup(sent_ms DESC,message_id DESC);
    CREATE INDEX IF NOT EXISTS lookup_room ON message_lookup(conversation_ref,sent_ms DESC,message_id DESC);
    CREATE INDEX IF NOT EXISTS lookup_sender ON message_lookup(sender_ref,sent_ms DESC,message_id DESC);
    CREATE TABLE IF NOT EXISTS identities (
      conversation_ref TEXT, sender_ref TEXT, name TEXT, status TEXT NOT NULL,
      reason TEXT, name_source TEXT, updated_at TEXT NOT NULL,
      PRIMARY KEY(conversation_ref,sender_ref)
    );
    CREATE TABLE IF NOT EXISTS rooms (
      conversation_ref TEXT PRIMARY KEY, name TEXT, kind TEXT, status TEXT NOT NULL,
      reason TEXT, name_source TEXT, updated_at TEXT NOT NULL
    );
    """)
    db.execute(
        "INSERT OR IGNORE INTO metadata VALUES('query_cursor_key',?)", (secrets.token_hex(32),)
    )
    db.execute("INSERT OR IGNORE INTO metadata VALUES('identity_revision','0')")
    name_history.initialize(db)


def timestamp(value):
    return (
        datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")
        if value is not None
        else None
    )


def instant(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("timezone_required")
    return int(parsed.timestamp() * 1000)


class Queries:
    def __init__(self, store):
        self.store = store

    def _cursor(self, db, cursor, query):
        epoch = db.execute("SELECT value FROM metadata WHERE key='cursor_epoch'").fetchone()[0]
        key = (
            db.execute("SELECT value FROM metadata WHERE key='query_cursor_key'")
            .fetchone()[0]
            .encode()
        )
        fingerprint = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        high = db.execute("SELECT COALESCE(MAX(id),0) FROM candidates").fetchone()[0]
        floor = int(
            (db.execute("SELECT value FROM metadata WHERE key='pruned_cursor'").fetchone() or [0])[
                0
            ]
        )
        state = {"v": 2, "epoch": epoch, "query": fingerprint, "snapshot": high, "floor": floor}
        if query.get("sender_name") is not None or (
            query["kind"] == "conversations" and query.get("q")
        ):
            state["names"] = db.execute(
                "SELECT value FROM metadata WHERE key='identity_revision'"
            ).fetchone()[0]
        if cursor:
            try:
                payload, signature = cursor.split(".")
                if not hmac.compare_digest(
                    hmac.new(key, payload.encode(), "sha256").hexdigest(), signature
                ):
                    raise ValueError
                old = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                checks = (
                    ("v", "epoch", "query", "floor", "names")
                    if "names" in state
                    else ("v", "epoch", "query", "floor")
                )
                if any(old[k] != state[k] for k in checks):
                    raise ValueError
                if not 0 <= old["snapshot"] <= high:
                    raise ValueError
                state = old
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise ValueError("invalid_or_expired_query_cursor") from None
        return state, key

    @staticmethod
    def _encode(state, key, last):
        payload = (
            base64.urlsafe_b64encode(
                json.dumps({**state, "last": last}, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        return payload + "." + hmac.new(key, payload.encode(), "sha256").hexdigest()

    @staticmethod
    def _item(row):
        r = dict(row)
        return {
            "message_id": r["message_id"],
            "conversation": {
                "ref": r["conversation_ref"],
                "name": r["room_name"],
                "kind": r["room_kind"],
                "name_status": r["room_status"] or "pending",
                "name_reason": r["room_reason"],
                "name_source": r["room_source"],
                "updated_at": r["room_updated"],
            },
            "sender": {
                "ref": r["sender_ref"],
                "name": r["sender_name"],
                "name_status": r["sender_status"] or "pending",
                "name_reason": r["sender_reason"],
                "name_source": r["sender_source"],
                "updated_at": r["sender_updated"],
                "name_observed_at": timestamp(r["sender_observed_ms"]),
                "name_evidence_message_id": r["sender_evidence_id"],
            },
            "is_mine": None if r["is_mine"] is None else bool(r["is_mine"]),
            "sent_at": timestamp(r["sent_ms"]),
            "collected_at": r["received_at"],
            "body": r["body"],
            "message_type": r["message_type"],
            "source": r["source"],
            "truncated": bool(r["truncated"]),
        }

    SELECT = f"""SELECT m.*, c.body,c.received_at,c.truncated,
      {name_history.NAME} sender_name,{name_history.STATUS} sender_status,
      CASE WHEN h.name IS NOT NULL THEN 'historical_name_current_unverified' ELSE s.reason END sender_reason,
      CASE WHEN h.name IS NOT NULL THEN h.name_source ELSE s.name_source END sender_source,
      s.updated_at sender_updated,h.observed_ms sender_observed_ms,h.message_id sender_evidence_id,
      r.name room_name,r.kind room_kind,r.status room_status,r.reason room_reason,r.name_source room_source,r.updated_at room_updated
      FROM message_lookup m JOIN candidates c ON c.id=m.message_id
      {name_history.JOINS}"""

    def messages(
        self,
        *,
        limit=50,
        cursor=None,
        q=None,
        conversation_ref=None,
        sender_ref=None,
        sender_name=None,
        since=None,
        until=None,
        include_mine=True,
    ):
        start, end = instant(since), instant(until)
        if start is not None and end is not None and start >= end:
            raise ValueError("invalid_time_range")
        query = {
            "kind": "messages",
            "q": q,
            "conversation_ref": conversation_ref,
            "sender_ref": sender_ref,
            "sender_name": sender_name,
            "since": start,
            "until": end,
            "include_mine": include_mine,
        }
        with self.store.connect() as db:
            db.execute("BEGIN")
            state, key = self._cursor(db, cursor, query)
            where, args = ["m.message_id <= ?"], [state["snapshot"]]
            for field, value in [
                ("m.conversation_ref", conversation_ref),
                ("m.sender_ref", sender_ref),
            ]:
                if value is not None:
                    where.append(field + "=?")
                    args.append(value)
            if sender_name is not None:
                where.append(f"instr(lower({name_history.NAME}),lower(?))>0")
                args.append(sender_name)
            if q is not None:
                where.append("instr(lower(c.body),lower(?))>0")
                args.append(q)
            if start is not None:
                where.append("m.sent_ms>=?")
                args.append(start)
            if end is not None:
                where.append("m.sent_ms<?")
                args.append(end)
            if not include_mine:
                where.append("m.is_mine=0")
            if "last" in state:
                where.append("(COALESCE(m.sent_ms,-1),m.message_id)<(?,?)")
                args.extend(state["last"])
            rows = db.execute(
                self.SELECT
                + " WHERE "
                + " AND ".join(where)
                + " ORDER BY COALESCE(m.sent_ms,-1) DESC,m.message_id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
            selected = rows[:limit]
            more = len(rows) > limit
            last = (
                [
                    selected[-1]["sent_ms"] if selected[-1]["sent_ms"] is not None else -1,
                    selected[-1]["message_id"],
                ]
                if more
                else None
            )
            return {
                "items": [self._item(r) for r in selected],
                "has_more": more,
                "next_cursor": self._encode(state, key, last) if more else None,
                "order": "sent_at_desc",
                "unknown_times": "last",
                "time_range": "since_inclusive_until_exclusive",
            }

    def conversations(self, *, limit=50, cursor=None, q=None):
        with self.store.connect() as db:
            db.execute("BEGIN")
            state, key = self._cursor(db, cursor, {"kind": "conversations", "q": q})
            where, args = ["rn=1"], [state["snapshot"]]
            if q:
                where.append("instr(lower(name),lower(?))>0")
                args.append(q)
            if "last" in state:
                where.append("(COALESCE(sent_ms,-1),message_id)<(?,?)")
                args.extend(state["last"])
            rows = db.execute(
                """WITH latest AS (
              SELECT m.*,r.name,r.kind,r.status,r.reason,r.name_source,r.updated_at,
                COUNT(*) OVER (PARTITION BY m.conversation_ref) message_count,
                ROW_NUMBER() OVER (PARTITION BY m.conversation_ref ORDER BY COALESCE(m.sent_ms,-1) DESC,m.message_id DESC) rn
              FROM message_lookup m LEFT JOIN rooms r USING(conversation_ref)
              WHERE m.message_id<=? AND m.conversation_ref IS NOT NULL)
              SELECT * FROM latest WHERE """
                + " AND ".join(where)
                + " ORDER BY COALESCE(sent_ms,-1) DESC,message_id DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
            selected = rows[:limit]
            more = len(rows) > limit
            last = (
                [
                    selected[-1]["sent_ms"] if selected[-1]["sent_ms"] is not None else -1,
                    selected[-1]["message_id"],
                ]
                if more
                else None
            )
            return {
                "items": [
                    {
                        "ref": r["conversation_ref"],
                        "name": r["name"],
                        "kind": r["kind"],
                        "name_status": r["status"] or "pending",
                        "name_reason": r["reason"],
                        "name_source": r["name_source"],
                        "updated_at": r["updated_at"],
                        "last_message_at": timestamp(r["sent_ms"]),
                        "last_message_id": r["message_id"],
                        "message_count": r["message_count"],
                    }
                    for r in selected
                ],
                "has_more": more,
                "next_cursor": self._encode(state, key, last) if more else None,
                "order": "last_message_at_desc",
                "scope": "retained_collected_messages",
            }

    def context(self, message_id, before=5, after=5):
        with self.store.connect() as db:
            db.execute("BEGIN")
            target = db.execute(self.SELECT + " WHERE m.message_id=?", (message_id,)).fetchone()
            if target is None:
                raise ValueError("message_not_found_or_expired")
            if not target["conversation_ref"]:
                raise ValueError("conversation_unresolved")
            base = (
                self.SELECT
                + " WHERE m.conversation_ref=? AND (COALESCE(m.sent_ms,-1),m.message_id)"
            )
            key = (
                target["conversation_ref"],
                target["sent_ms"] if target["sent_ms"] is not None else -1,
                message_id,
            )
            earlier = db.execute(
                base + "<(?,?) ORDER BY COALESCE(m.sent_ms,-1) DESC,m.message_id DESC LIMIT ?",
                (*key, before + 1),
            ).fetchall()
            later = db.execute(
                base + ">(?,?) ORDER BY COALESCE(m.sent_ms,-1),m.message_id LIMIT ?",
                (*key, after + 1),
            ).fetchall()
            return {
                "target_message_id": message_id,
                "items": [
                    self._item(r) for r in [*reversed(earlier[:before]), target, *later[:after]]
                ],
                "has_more_before": len(earlier) > before,
                "has_more_after": len(later) > after,
                "order": "sent_at_asc",
            }

    def metadata_targets(self, device, epoch, limit=50):
        with self.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """SELECT m.chat_id,m.user_id,MAX(m.is_mine) is_mine
              FROM message_lookup m LEFT JOIN identities s ON s.conversation_ref=m.conversation_ref AND s.sender_ref=m.sender_ref
              LEFT JOIN rooms r ON r.conversation_ref=m.conversation_ref
              WHERE m.device_id=? AND m.epoch=? AND m.conversation_ref IS NOT NULL AND (
                s.updated_at IS NULL OR r.updated_at IS NULL OR
                julianday(s.updated_at)<julianday('now',CASE WHEN s.status='resolved' THEN '-1 hour' ELSE '-1 minute' END) OR
                julianday(r.updated_at)<julianday('now',CASE WHEN r.status='resolved' THEN '-1 hour' ELSE '-1 minute' END))
              GROUP BY m.chat_id,m.user_id
              ORDER BY COALESCE(s.updated_at,''),MAX(m.message_id) DESC LIMIT ?""",
                    (device, epoch, limit),
                )
            ]

    def metadata_update(self, device, epoch, database_id, items, self_source=None):
        updated = datetime.now(UTC).isoformat()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self_source:
                db.execute(
                    "INSERT INTO metadata VALUES('self_identity_source',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (self_source,),
                )
            for item in items:
                room = f"{device}:{epoch}:{item.chat_id}"
                sender = f"{device}:{epoch}:{item.user_id}"
                if not db.execute(
                    "SELECT 1 FROM message_lookup WHERE conversation_ref=? AND sender_ref=? AND database_id=? LIMIT 1",
                    (room, sender, database_id),
                ).fetchone():
                    raise ValueError("metadata_identity_mismatch")
                user, chat = item.sender, item.conversation
                previous = db.execute(
                    """SELECT s.name,s.status,r.name,r.kind FROM identities s
                    LEFT JOIN rooms r USING(conversation_ref)
                    WHERE s.conversation_ref=? AND s.sender_ref=?""",
                    (room, sender),
                ).fetchone()
                if previous is None or tuple(previous) != (
                    user.name,
                    user.status,
                    chat.name,
                    item.kind,
                ):
                    name_history.changed(db)
                db.execute(
                    "INSERT INTO identities VALUES(?,?,?,?,?,?,?) ON CONFLICT(conversation_ref,sender_ref) DO UPDATE SET name=excluded.name,status=excluded.status,reason=excluded.reason,name_source=excluded.name_source,updated_at=excluded.updated_at",
                    (room, sender, user.name, user.status, user.reason, user.name_source, updated),
                )
                db.execute(
                    "INSERT INTO rooms VALUES(?,?,?,?,?,?,?) ON CONFLICT(conversation_ref) DO UPDATE SET name=excluded.name,kind=excluded.kind,status=excluded.status,reason=excluded.reason,name_source=excluded.name_source,updated_at=excluded.updated_at",
                    (
                        room,
                        chat.name,
                        item.kind,
                        chat.status,
                        chat.reason,
                        chat.name_source,
                        updated,
                    ),
                )
        return {"updated": len(items)}

    def metadata_status(self):
        with self.store.connect() as db:
            rows = db.execute(f"""SELECT {name_history.STATUS} sender_status,COALESCE(r.status,'pending') room_status,COUNT(*) count
                FROM (SELECT conversation_ref,sender_ref,MAX(is_mine) is_mine FROM message_lookup
                  WHERE conversation_ref IS NOT NULL GROUP BY conversation_ref,sender_ref) m
                {name_history.JOINS} GROUP BY sender_status,room_status""").fetchall()
            source = db.execute(
                "SELECT value FROM metadata WHERE key='self_identity_source'"
            ).fetchone()
            return {
                "scope": "observed_room_sender_pairs",
                "states": [dict(r) for r in rows],
                "self_identity_source": source[0] if source else None,
            }
