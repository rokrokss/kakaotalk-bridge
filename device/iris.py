"""Poll the restricted Iris endpoint through loopback ADB; commit before advancing."""

import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from device import cli, enrollment

BUILD = "iris-ee1dc978-collector-v6"
ENTRY = "party.qwer.iris.CollectorMain"
LOCAL_APK = "/opt/iris.apk"
HOME = enrollment.HOME
REMOTE_APK = HOME + "/iris.apk"
PID_FILE = HOME + "/iris.pid"
AUTH_FILE = HOME + "/iris-auth.json"
# Iris replies through KakaoTalk notifications using the referer stored here.
KAKAO_PREFS = "/data/user/0/com.kakao.talk/shared_prefs/KakaoTalk.hw.perferences.xml"
# The API accepts 1 MiB bodies; leave room for the JSON envelope.
MAX_BATCH_BYTES = 768 * 1024
SKIP_REASONS = {"decrypt_failed", "metadata_unreadable"}


def request(url, payload=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=25) as response:
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024 or response.status != 200:
            raise RuntimeError("iris_transport_failed")
        return json.loads(body)


def identity(config):
    return str(uuid.uuid5(uuid.UUID(config["enrollment_epoch"]), "iris_db"))


def account_identity(config):
    return str(
        uuid.uuid5(
            uuid.UUID(config["enrollment_epoch"]), "kakao_account:" + config["approved_user_id"]
        )
    )


@functools.cache
def local_apk_sha():
    return hashlib.sha256(Path(LOCAL_APK).read_bytes()).hexdigest()


def stop():
    # Only a process whose command line is the collector entry point is signalled.
    cli.adb(
        "shell",
        f"p=$(cat {PID_FILE} 2>/dev/null); case \"$p\" in ''|*[!0-9]*) ;; "
        f"*) grep -q {ENTRY} /proc/$p/cmdline 2>/dev/null && kill $p ;; esac; rm -f {PID_FILE}",
        check=False,
    )


def ensure_auth(epoch):
    """Provision a root-only, enrollment-bound credential; never put it in argv/logs."""
    raw = cli.adb("shell", "cat", AUTH_FILE, check=False)
    try:
        record = json.loads(raw)
    except ValueError:
        record = {}
    if record.get("enrollment_epoch") == epoch and re.fullmatch(
        r"[A-Za-z0-9_-]{43}", record.get("token", "")
    ):
        return record["token"]
    record = {"enrollment_epoch": epoch, "token": secrets.token_urlsafe(32)}
    staged = AUTH_FILE + ".next"
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "auth.json"
        local.write_text(json.dumps(record))
        local.chmod(0o600)
        cli.adb("shell", f"mkdir -p {HOME} && chown 0:0 {HOME} && chmod 700 {HOME}")
        cli.adb("push", str(local), staged)
    cli.adb("shell", f"chown 0:0 {staged} && chmod 600 {staged} && mv {staged} {AUTH_FILE}")
    return record["token"]


def install():
    """Put this image's Iris build on the device, so updates and rollbacks carry their own."""
    wanted = local_apk_sha()
    if cli.adb("shell", "sha256sum", REMOTE_APK, check=False).split()[:1] == [wanted]:
        return False
    staged = REMOTE_APK + ".next"
    cli.adb("shell", f"mkdir -p {HOME} && chown 0:0 {HOME} && chmod 700 {HOME}")
    cli.adb("push", LOCAL_APK, staged)
    if cli.adb("shell", "sha256sum", staged).split()[:1] != [wanted]:
        cli.adb("shell", "rm", "-f", staged, check=False)
        raise RuntimeError("iris_upload_checksum_mismatch")
    cli.adb("shell", f"chmod 0444 {staged} && mv {staged} {REMOTE_APK}")
    return True


def healthy(token):
    # Authenticate the listener before sending a bearer credential: an Android
    # app can otherwise bind the loopback port while Iris is stopped.
    challenge = secrets.token_hex(32)
    info = request("http://127.0.0.1:3000/collector/health?" + urlencode({"challenge": challenge}))
    proof = hmac.new(token.encode(), f"{challenge}:{BUILD}".encode(), hashlib.sha256).hexdigest()
    if info.get("build") != BUILD or not hmac.compare_digest(str(info.get("proof", "")), proof):
        raise RuntimeError("unexpected_iris_server")


def notification_reply_ready():
    """Whether KakaoTalk stored its reply referer. None when ADB cannot tell.

    KakaoTalk saves it with its first message notification. Only presence is
    reported; the value never leaves the device.
    """
    # Without root the app's data is hidden, so a missing file would look like a denied one.
    answer = cli.adb(
        "shell",
        f"[ $(id -u) = 0 ] || exit; [ -e {KAKAO_PREFS} ] || {{ echo 1; exit; }}; "
        "grep -qE '<string name=\"NotificationReferer\">[^<]*[^<[:space:]]' "
        f"{KAKAO_PREFS} 2>/dev/null; echo $?",
        check=False,
    )
    # grep exits 1 when the value is absent and 2 when it cannot read the file.
    return {"0": True, "1": False}.get(answer)


def ensure_started(epoch):
    """Authenticate the running listener, or start this image's build. Returns the bearer."""
    token = ensure_auth(epoch)
    try:
        healthy(token)
        return token
    except (OSError, ValueError, RuntimeError):
        pass  # Not running, an earlier build, or not our listener.
    stop()
    install()
    cli.adb("forward", "tcp:3000", "tcp:3000")
    # All shell fragments are constants. No credentials or user content enters this command.
    cli.adb(
        "shell",
        f"CLASSPATH={REMOTE_APK} app_process / {ENTRY} >/dev/null 2>&1 & echo $! > {PID_FILE}",
    )
    for _ in range(10):
        try:
            healthy(token)
        except (OSError, ValueError):
            time.sleep(1)
            continue
        return token
    raise RuntimeError("iris_start_failed")


def _field(value, pattern, fallback):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else fallback


def make_event(config, database_id, row):
    log_id = int(row["log_id"])
    if not 0 < log_id <= 9223372036854775807:
        raise RuntimeError("unsupported_log_id")
    epoch = identity(config)
    reason = row.get("skipped")
    event = {
        "event_id": str(uuid.uuid5(uuid.UUID(epoch), f"{database_id}:{log_id}")),
        "device_id": config["device_id"],
        "enrollment_epoch": epoch,
        "source_seq": log_id,
        "source": "iris_db",
        "kind": "db_row",
        "package_name": "com.kakao.talk",
        "notification_key": "iris:" + str(row.get("chat_id")),
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {
            "messages": [
                {
                    "body": row.get("message"),
                    "sender": row.get("sender_id"),
                    "timestamp": max(0, int(row.get("created_at") or 0)) * 1000,
                }
            ],
            "truncated": row.get("truncated", False),
        },
        "database_ref": {
            "database_id": database_id,
            **{
                k: row.get(k)
                for k in ("log_id", "chat_id", "sender_id", "message_type", "origin", "is_mine")
            },
        },
    }
    if reason:
        return skipped(event, reason if reason in SKIP_REASONS else "unreadable")
    return event


def skipped(event, reason="invalid_row"):
    """A cursor-only marker for a row that cannot be stored as a message."""
    ref = event["database_ref"]
    chat = _field(ref.get("chat_id"), r"-?[0-9]{1,20}", "0")
    return {
        **event,
        "kind": "db_row_skipped",
        "notification_key": "iris:" + chat,
        "payload": {"messages": [], "truncated": False},
        "database_ref": {
            "database_id": ref["database_id"],
            "log_id": ref["log_id"],
            "chat_id": chat,
            "sender_id": _field(ref.get("sender_id"), r"-?[0-9]{1,20}", "0"),
            "message_type": str(ref.get("message_type") or "")[:32],
            "origin": "",
            "is_mine": ref.get("is_mine") is True,
            "skip_reason": reason,
        },
    }


class Collector:
    def __init__(self, api=None):
        self.api = api or self.api_request
        self.epoch = str(uuid.UUID(int=0))
        self.last_seq = 0
        self.database_id = None
        self.account_ref = None
        self.kakao_version = None
        self.metadata_checked = 0
        self.send_ready = None
        self.send_checked = 0
        self.connected = False
        self.iris_token = None
        self.iris_epoch = None
        self.has_more = False

    def api_request(self, path, payload=None):
        return request(
            os.getenv("API_URL", "http://api:8000") + path,
            payload,
            Path("/run/secrets/ingest_token").read_text().strip(),
        )

    def reset(self):
        self.connected = False
        self.iris_token = None

    def heartbeat(self, allowed, connected):
        self.api(
            "/internal/v1/heartbeat",
            {
                "device_id": os.getenv("DEVICE_ID", "personal-tablet"),
                "enrollment_epoch": self.epoch,
                "source": "iris_db",
                "database_id": self.database_id,
                "secondary_login_confirmed": allowed,
                "supports_message_send": True,
                "notification_reply_ready": self.send_ready,
                "account_ref": self.account_ref,
                "listener_connected": connected,
                "last_source_seq": self.last_seq,
                "kakao_version": self.kakao_version,
            },
        )

    def iris(self, enrollment_epoch):
        if self.iris_token and self.iris_epoch == enrollment_epoch:
            try:
                healthy(self.iris_token)
                return self.iris_token
            except (OSError, ValueError, RuntimeError):
                pass
        self.iris_token = ensure_started(enrollment_epoch)
        self.iris_epoch = enrollment_epoch
        return self.iris_token

    def tick(self):
        if not self.connected:
            cli.connect()
            self.connected = True
        snap = enrollment.require_approved()
        config = snap.config
        self.account_ref = account_identity(config)
        self.kakao_version = snap.kakao_version
        self.epoch = identity(config)
        progress = self.api("/internal/v1/iris/cursor?" + urlencode({"epoch": self.epoch}))
        self.last_seq = progress["after"]
        token = self.iris(config["enrollment_epoch"])
        page = request(
            "http://127.0.0.1:3000/collector/rows?" + urlencode({"after": self.last_seq}),
            token=token,
        )
        if page["build"] != BUILD or page["enrollment_epoch"] != config["enrollment_epoch"]:
            raise RuntimeError("iris_identity_mismatch")
        if progress["database_id"] not in (None, page["database_id"]):
            raise RuntimeError("iris_database_changed_requires_new_epoch")
        if int(page["high_water"]) < self.last_seq:
            raise RuntimeError("iris_database_regressed_requires_new_epoch")
        # Check again after querying. Never ingest a page after observing revocation.
        if page["rows"] and enrollment.require_approved().config != config:
            raise RuntimeError("enrollment_changed")
        self.database_id = page["database_id"]
        events = [make_event(config, self.database_id, row) for row in page["rows"]]
        seqs = [e["source_seq"] for e in events]
        if seqs != sorted(set(seqs)) or any(s <= self.last_seq for s in seqs):
            raise RuntimeError("iris_invalid_page_order")
        if time.monotonic() - self.send_checked > 10:
            self.send_checked = time.monotonic()
            try:
                self.send_ready = notification_reply_ready()
            except (OSError, subprocess.TimeoutExpired):
                self.send_ready = None
        self.heartbeat(True, True)
        if events:
            self.commit(events)
            self.heartbeat(True, True)
        self.has_more = bool(page.get("has_more"))
        # Metadata is refreshed independently: names must not change a committed row's identity.
        if time.monotonic() - self.metadata_checked > 10:
            self.metadata_checked = time.monotonic()
            try:
                self.refresh_metadata(config, token)
            except (OSError, ValueError, KeyError, RuntimeError):
                print('{"iris_metadata":"unavailable","action":"check_profile_lookup"}', flush=True)
        self.send_pending(config)
        return len(events)

    def send_pending(self, config):
        if enrollment.require_approved().config != config:
            raise RuntimeError("enrollment_changed")
        item = self.api(
            "/internal/v1/outgoing/claim",
            {
                "enrollment_epoch": self.epoch,
                "database_id": self.database_id,
                "account_ref": self.account_ref,
            },
        )["item"]
        if item is None:
            return
        status = "failed"
        try:
            if (
                enrollment.require_approved().config != config
                or item["epoch"] != self.epoch
                or item["database_id"] != self.database_id
                or item["account_ref"] != account_identity(config)
            ):
                raise RuntimeError("send_enrollment_mismatch")
            status = "unknown"  # Any loss after beginning HTTP is ambiguous; do not retry.
            result = request(
                "http://127.0.0.1:3000/collector/send",
                {
                    "request_id": item["request_id"],
                    "chat_id": item["chat_id"],
                    "text": item["text"],
                    "database_id": self.database_id,
                    "enrollment_epoch": config["enrollment_epoch"],
                    "approved_user_id": config["approved_user_id"],
                },
                self.iris_token,
            )
            if result.get("status") in {"failed", "unknown"}:
                status = result["status"]
            elif (
                result.get("status") == "submitted"
                and result.get("build") == BUILD
                and result.get("request_id") == item["request_id"]
                and result.get("enrollment_epoch") == config["enrollment_epoch"]
                and result.get("database_id") == self.database_id
            ):
                status = "submitted"
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
            pass
        self.api("/internal/v1/outgoing/" + item["request_id"] + "/result", {"status": status})

    def commit(self, events):
        """Send rows in order. The cursor only moves past rows the server stored."""
        events = list(events)
        position = 0
        while position < len(events):
            chunk, size = [], 0
            for event in events[position : position + 100]:
                encoded = len(json.dumps(event, ensure_ascii=False).encode())
                if chunk and size + encoded > MAX_BATCH_BYTES:
                    break
                chunk.append(event)
                size += encoded
            results = self.api(
                "/internal/v1/observations:batch", {"schema_version": 1, "events": chunk}
            )["results"]
            if len(results) != len(chunk):
                raise RuntimeError("iris_row_rejected")
            for offset, (event, ack) in enumerate(zip(chunk, results)):
                if (
                    ack.get("status") in ("committed", "duplicate")
                    and ack.get("event_id") == event["event_id"]
                ):
                    self.last_seq = event["source_seq"]
                    continue
                if ack.get("reason") == "invalid_event" and event["kind"] == "db_row":
                    # Keep later rows moving: store this one as unreadable and resend from it.
                    events[position + offset] = skipped(event)
                    position += offset
                    break
                raise RuntimeError("iris_row_rejected")
            else:
                position += len(chunk)

    def refresh_metadata(self, config, token):
        targets = self.api(
            "/internal/v1/iris/metadata-targets?" + urlencode({"epoch": self.epoch})
        )["items"]
        if not targets:
            return
        result = request("http://127.0.0.1:3000/collector/metadata", {"targets": targets}, token)
        if (
            result["build"] != BUILD
            or result["enrollment_epoch"] != config["enrollment_epoch"]
            or result["database_id"] != self.database_id
        ):
            raise RuntimeError("iris_metadata_identity_mismatch")
        self.api(
            "/internal/v1/iris/metadata",
            {
                "device_id": config["device_id"],
                "enrollment_epoch": self.epoch,
                "database_id": self.database_id,
                "items": result["items"],
                "self_identity_source": result.get("self_identity_source"),
            },
        )


def watch():
    collector = Collector()
    while True:
        try:
            count = collector.tick()
            print(json.dumps({"iris": "polling", "committed_rows": count}), flush=True)
            time.sleep(0.2 if collector.has_more else 3)
        except (
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            collector.reset()
            try:
                stop()
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            try:
                collector.heartbeat(False, False)
            except (OSError, ValueError, RuntimeError):
                pass
            # Only fixed reason codes are logged: transport errors can carry upstream content.
            reason = str(exc) if re.fullmatch(r"[a-z_]{3,64}", str(exc)) else "unavailable"
            print(json.dumps({"iris": "locked_or_unavailable", "reason": reason}), flush=True)
            time.sleep(10)
