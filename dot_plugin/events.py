"""Durable signal-only webhook outbox plus per-consumer read/ack cursors."""

import hashlib
import json
import re
import threading
import time
from datetime import UTC, datetime

from dot_plugin import event_policy, network
from dot_plugin.config import EVENT
from dot_plugin.storage import canonical


class RpcError(Exception):
    def __init__(self, message, code=-32602, reason=None):
        self.message, self.code, self.reason = message, code, reason


def iso(stamp):
    return datetime.fromtimestamp(stamp, UTC).isoformat().replace("+00:00", "Z")


def event_args(raw):
    if not isinstance(raw, dict) or set(raw) - {"consumer_id", "conversation_ref", "include_mine"}:
        raise RpcError("invalid_event_arguments")
    args = {
        "consumer_id": raw.get("consumer_id", "dot"),
        "include_mine": raw.get("include_mine", True),
    }
    if not isinstance(args["consumer_id"], str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,64}", args["consumer_id"]
    ):
        raise RpcError("invalid_consumer_id")
    if type(args["include_mine"]) is not bool:
        raise RpcError("invalid_include_mine")
    if "conversation_ref" in raw:
        if (
            not isinstance(raw["conversation_ref"], str)
            or not 1 <= len(raw["conversation_ref"]) <= 256
        ):
            raise RpcError("invalid_conversation_ref")
        args["conversation_ref"] = raw["conversation_ref"]
    return args


def match(row, args):
    return (
        row.get("source") == "iris_db"
        and (
            not args.get("conversation_ref")
            or row.get("conversation_ref") == args["conversation_ref"]
        )
        and (args["include_mine"] or not row["database_ref"]["is_mine"])
    )


class Events:
    def __init__(
        self, state, auth, collector, verify=network.verify_callback, deliver=network.deliver
    ):
        self.state, self.auth, self.collector = state, auth, collector
        self.verify, self.deliver = verify, deliver
        self.stop = threading.Event()
        self.operation_lock = threading.RLock()

    @staticmethod
    def consumer_key(owner, consumer_id):
        return hashlib.sha256(canonical([owner, consumer_id]).encode()).hexdigest()

    def identity(self, params, principal):
        if params.get("name") != EVENT:
            raise RpcError("unknown_event")
        args = event_args(params.get("arguments", {}))
        delivery = params.get("delivery", {})
        if (
            not isinstance(delivery, dict)
            or delivery.get("mode") != "webhook"
            or not isinstance(delivery.get("url"), str)
        ):
            raise RpcError("webhook_delivery_required")
        url = delivery["url"]
        # Syntax checks apply even to unsubscribe; no network access is needed there.
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or len(url) > 4096
        ):
            raise RpcError("invalid_callback_url")
        key = (
            "sub_"
            + hashlib.sha256(
                canonical([principal["owner"], url, EVENT, args]).encode()
            ).hexdigest()[:40]
        )
        return key, args, url

    def subscribe(self, params, principal):
        if params.get("cursor") is not None:
            raise RpcError("protocol_replay_not_supported_use_pending_messages")
        ttl = params.get("ttlMs", 86400000)
        if ttl is not None and (type(ttl) is not int or ttl <= 0):
            raise RpcError("invalid_ttl")
        ttl = min(ttl if ttl is not None else 86400000, 86400000) / 1000
        key, args, url = self.identity(params, principal)
        secret = params["delivery"].get("secret")
        try:
            network.signing_key(secret)
        except ValueError:
            raise RpcError("invalid_signing_secret") from None
        checkpoint = self.collector.checkpoint()
        consumer_key = self.consumer_key(principal["owner"], args["consumer_id"])
        existing = self.state.get("subscription", key)
        consumer = self.state.get("consumer", consumer_key)
        if consumer and consumer["args"] != args:
            raise RpcError("consumer_id_already_has_different_filters_use_a_new_id")
        if consumer and consumer["epoch"] != checkpoint["cursor_epoch"]:
            raise RpcError("collector_epoch_changed_use_a_new_consumer_id")
        if len(self.state.all("subscription")) >= 100 and not existing:
            raise RpcError("subscription_limit")
        now = time.time()
        continuing = (
            existing
            and existing["active"]
            and existing["expires"] > now
            and existing["epoch"] == checkpoint["cursor_epoch"]
            and self.auth.active_grant(existing["grant_id"])
        )
        sub = {
            "id": key,
            "owner": principal["owner"],
            "grant_id": principal["grant_id"],
            "args": args,
            "url": url,
            "secret": secret,
            "expires": now + ttl,
            "active": True,
            "epoch": checkpoint["cursor_epoch"],
            "scan_cursor": checkpoint["cursor"],
            "verified_until": now + 300,
            "delivered": 0,
            "failed": 0,
            "last_delivery_at": None,
        }
        if continuing:
            sub.update(
                {k: existing[k] for k in ("scan_cursor", "delivered", "failed", "last_delivery_at")}
            )
            if existing["secret"] != secret:
                sub.update(previous_secret=existing["secret"], rotation_until=now + 300)
            elif existing.get("rotation_until", 0) > now:
                sub.update(
                    previous_secret=existing["previous_secret"],
                    rotation_until=existing["rotation_until"],
                )
        if not (
            continuing and existing["secret"] == secret and existing.get("verified_until", 0) > now
        ):
            try:
                self.verify(sub)
            except network.DeliveryError as error:
                raise RpcError("callback_verification_failed", -32015, error.args[0]) from None
        # Serialize against the worker only for the commit, never while verifying HTTP.
        with self.operation_lock, self.state.transaction() as db:
            if not self.auth.active_grant(principal["grant_id"]):
                raise RpcError("authorization_revoked", -32001)
            latest = self.state.get("subscription", key, db=db)
            if continuing and latest and latest["active"]:
                sub.update(
                    {
                        k: latest[k]
                        for k in ("scan_cursor", "delivered", "failed", "last_delivery_at")
                    }
                )
            else:
                for item_id, item in self.state.all("delivery", db=db):
                    if item["subscription_id"] == key:
                        self.state.delete("delivery", item_id, db=db)
            self.state.put("subscription", key, sub, db=db)
            if not consumer:
                self.state.put(
                    "consumer",
                    consumer_key,
                    {
                        "owner": principal["owner"],
                        "args": args,
                        "epoch": checkpoint["cursor_epoch"],
                        "acked": checkpoint["cursor"],
                        "offered": checkpoint["cursor"],
                    },
                    db=db,
                )
        return {"id": key, "refreshBefore": iso(sub["expires"]), "cursor": None, "truncated": False}

    def unsubscribe(self, params, principal):
        key, _, _ = self.identity(params, principal)
        with self.operation_lock, self.state.transaction() as db:
            sub = self.state.get("subscription", key, db=db)
            if sub:
                sub["active"] = False
                sub["stopped_reason"] = "unsubscribed"
                self.state.put("subscription", key, sub, db=db)
            for item_id, item in self.state.all("delivery", db=db):
                if item["subscription_id"] == key:
                    self.state.delete("delivery", item_id, db=db)
        return {}

    def pending(self, principal, consumer_id, limit):
        key = self.consumer_key(principal["owner"], consumer_id)
        consumer = self.state.get("consumer", key)
        if not consumer:
            raise RpcError("subscribe_with_this_consumer_id_first")
        checkpoint = self.collector.checkpoint()
        if checkpoint["cursor_epoch"] != consumer["epoch"]:
            raise RpcError("collector_epoch_changed_use_a_new_consumer_id")
        after = max(consumer["acked"], checkpoint["pruned_through_cursor"])
        page = self.collector.messages(after, limit)
        if page["coverage"]["cursor_epoch"] != consumer["epoch"]:
            raise RpcError("collector_epoch_changed_use_a_new_consumer_id")
        rows = [
            row
            for row in page["items"]
            if match(row, consumer["args"])
            and event_policy.allows(
                self.state, row["conversation_ref"], consumer["epoch"], row["id"]
            )
        ]
        through = page["next_cursor"]
        with self.state.transaction() as db:
            current = self.state.get("consumer", key, db=db)
            current["offered"] = max(current["offered"], through)
            self.state.put("consumer", key, current, db=db)
        return {
            "consumer_id": consumer_id,
            "cursor_epoch": consumer["epoch"],
            "after_cursor": consumer["acked"],
            "next_cursor": through,
            "items": rows,
            "has_more": page["has_more"],
            "truncated": consumer["acked"] < checkpoint["pruned_through_cursor"],
            "coverage": page["coverage"],
        }

    def acknowledge(self, principal, consumer_id, through_cursor, epoch):
        key = self.consumer_key(principal["owner"], consumer_id)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            consumer = self.state.get("consumer", key, db=db)
            if not consumer or epoch != consumer["epoch"] or through_cursor > consumer["offered"]:
                raise RpcError("only_acknowledge_a_cursor_returned_by_get_pending_messages")
            consumer["acked"] = max(consumer["acked"], through_cursor)
            self.state.put("consumer", key, consumer, db=db)
            return {
                "consumer_id": consumer_id,
                "acknowledged_cursor": consumer["acked"],
                "cursor_epoch": epoch,
            }

    def summary(self, owner):
        subs = [s for _, s in self.state.all("subscription") if s["owner"] == owner]
        return {
            "subscriptions": [
                {
                    "id": s["id"],
                    "consumer_id": s["args"]["consumer_id"],
                    "active": bool(
                        s["active"]
                        and s["expires"] > time.time()
                        and self.auth.active_grant(s["grant_id"])
                    ),
                    "delivered": s["delivered"],
                    "failed": s["failed"],
                    "last_delivery_at": s["last_delivery_at"],
                    "stopped_reason": s.get("stopped_reason"),
                }
                for s in subs
            ],
            "pending_deliveries": sum(
                1
                for _, d in self.state.all("delivery")
                if d["subscription_id"] in {s["id"] for s in subs}
            ),
        }

    def tick(self):
        with self.operation_lock:
            self._scan()
        self._deliver_pending()

    def _scan(self):
        now = time.time()
        checkpoint = None
        for key, sub in self.state.all("subscription"):
            if not sub["active"]:
                continue
            if sub["expires"] <= now or not self.auth.active_grant(sub["grant_id"]):
                sub.update(active=False, stopped_reason="expired_or_revoked")
                self.state.put("subscription", key, sub)
                continue
            checkpoint = checkpoint or self.collector.checkpoint()
            if (
                checkpoint["cursor_epoch"] != sub["epoch"]
                or sub["scan_cursor"] < checkpoint["pruned_through_cursor"]
            ):
                sub.update(active=False, stopped_reason="source_history_changed_resubscribe")
                self.state.put("subscription", key, sub)
                continue
            if sum(1 for _, d in self.state.all("delivery") if d["subscription_id"] == key) >= 1000:
                continue  # Backpressure: leave the source cursor in place.
            page = self.collector.messages(sub["scan_cursor"], 100)
            if page["coverage"]["cursor_epoch"] != sub["epoch"]:
                continue
            with self.state.transaction() as db:
                db.execute("BEGIN IMMEDIATE")
                for row in page["items"]:
                    if not match(row, sub["args"]) or not event_policy.allows(
                        self.state, row["conversation_ref"], sub["epoch"], row["id"], db=db
                    ):
                        continue
                    event_id = (
                        "evt_" + hashlib.sha256(f"{sub['epoch']}:{row['id']}".encode()).hexdigest()
                    )
                    event = {
                        "eventId": event_id,
                        "name": EVENT,
                        "timestamp": row["received_at"],
                        "cursor": None,
                        "data": {
                            "consumer_id": sub["args"]["consumer_id"],
                            "message_id": row["id"],
                            "cursor_epoch": sub["epoch"],
                            "conversation_ref": row["conversation_ref"],
                            "is_mine": bool(row["database_ref"]["is_mine"]),
                        },
                    }
                    delivery_id = key + ":" + event_id
                    if not self.state.get("delivery", delivery_id, db=db):
                        self.state.put(
                            "delivery",
                            delivery_id,
                            {
                                "subscription_id": key,
                                "event": event,
                                "attempts": 0,
                                "next_attempt": now,
                            },
                            db=db,
                        )
                sub["scan_cursor"] = page["next_cursor"]
                self.state.put("subscription", key, sub, db=db)

    def _deliver_pending(self):
        # A crash after POST may cause a duplicate with the
        # same eventId. A 2xx means receipt, not successful execution by ChatGPT.
        sent = 0
        for item_id, delivery in self.state.all("delivery"):
            if sent >= 20 or self.stop.is_set():
                break
            sub = self.state.get("subscription", delivery["subscription_id"])
            data = delivery["event"]["data"]
            if (
                not sub
                or not sub["active"]
                or sub["expires"] <= time.time()
                or not self.auth.active_grant(sub["grant_id"])
                or not event_policy.allows(
                    self.state, data["conversation_ref"], data["cursor_epoch"], data["message_id"]
                )
            ):
                self.state.delete("delivery", item_id)
                continue
            if delivery["next_attempt"] > time.time():
                continue
            sent += 1
            event = delivery["event"]
            try:
                status, _ = self.deliver(sub, event["eventId"], canonical(event).encode())
            except network.DeliveryError:
                status = 0
            delivery["attempts"] += 1
            success = 200 <= status < 300
            terminal = (
                success
                or status in (410, 413)
                or (400 <= status < 500 and status != 429)
                or 300 <= status < 400
                or delivery["attempts"] >= 8
            )
            with self.operation_lock, self.state.transaction() as db:
                # A refresh/unsubscribe can finish while the HTTPS request is in
                # flight. Do not restore an old signing key or deleted queue item.
                sub = self.state.get("subscription", delivery["subscription_id"], db=db)
                if not sub or not sub["active"] or not self.state.get("delivery", item_id, db=db):
                    continue
                if terminal:
                    self.state.delete("delivery", item_id, db=db)
                    if success:
                        sub["delivered"] += 1
                        sub["last_delivery_at"] = iso(time.time())
                    else:
                        sub["failed"] += 1
                    if status == 410:
                        sub.update(active=False, stopped_reason="receiver_gone")
                else:
                    delivery["next_attempt"] = time.time() + min(
                        3600, 2 ** delivery["attempts"] * 5
                    )
                    self.state.put("delivery", item_id, delivery, db=db)
                self.state.put("subscription", sub["id"], sub, db=db)
            print(
                json.dumps(
                    {
                        "component": "mcp_events",
                        "delivery": "accepted" if success else "failed" if terminal else "retry",
                        "status": status,
                    }
                ),
                flush=True,
            )

    def run(self):
        cleaned = 0
        while not self.stop.is_set():
            try:
                if time.time() - cleaned > 300:
                    self.auth.cleanup()
                    cleaned = time.time()
                self.tick()
            except Exception:  # noqa: BLE001 — isolate worker failures without private output
                # Never log OAuth credentials, callback URLs or private message bodies.
                print(
                    '{"component":"mcp_events","state":"source_or_delivery_unavailable"}',
                    flush=True,
                )
            self.stop.wait(2)
