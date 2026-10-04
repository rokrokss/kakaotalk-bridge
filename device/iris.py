"""Poll the restricted Iris endpoint through loopback ADB; commit before advancing."""

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

from device import cli, login_guard

BUILD = "iris-ee1dc978-collector-v4"
REMOTE_APK = "/data/local/tmp/kakaocollector-iris.apk"
PID_FILE = "/data/local/tmp/kakaocollector-iris.pid"
ENTRY = "party.qwer.iris.CollectorMain"
AUTH_DIR = "/data/kakaocollector-iris"
AUTH_FILE = AUTH_DIR + "/auth.json"


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


def check_enrollment():
    config = json.loads(cli.adb("shell", "cat", cli.REMOTE_CONFIG))
    if config.get("collector_mode") != "iris":
        raise RuntimeError("iris_setup_required")
    if config["device_id"] != os.getenv("DEVICE_ID", "personal-tablet"):
        raise RuntimeError("device_identity_changed")
    signature = login_guard.device_signature(cli.adb)
    if (
        config.get("secondary_login_version", 0) <= 0
        or config["secondary_login_version"] != signature["kakao_version"]
        or config.get("device_fingerprint") != signature["fingerprint"]
    ):
        raise RuntimeError("secondary_login_confirmation_required")
    return config


def stop():
    pid = cli.adb("shell", "cat", PID_FILE, check=False)
    if pid.isdecimal():
        cmdline = cli.adb("shell", "cat", f"/proc/{pid}/cmdline", check=False)
        if ENTRY in cmdline:
            cli.adb("shell", "kill", pid, check=False)
    cli.adb("shell", "rm", "-f", PID_FILE, check=False)


def ensure_auth(config):
    """Provision a root-only, enrollment-bound credential; never put it in argv/logs."""
    raw = cli.adb("shell", "cat", AUTH_FILE, check=False)
    try:
        record = json.loads(raw)
    except ValueError:
        record = {}
    if record.get("enrollment_epoch") == config["enrollment_epoch"] and re.fullmatch(
        r"[A-Za-z0-9_-]{43}", record.get("token", "")
    ):
        return record["token"]
    record = {"enrollment_epoch": config["enrollment_epoch"], "token": secrets.token_urlsafe(32)}
    cli.adb("shell", "mkdir", "-p", AUTH_DIR)
    cli.adb("shell", "chown", "0:0", AUTH_DIR)
    cli.adb("shell", "chmod", "0700", AUTH_DIR)
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "auth.json"
        local.write_text(json.dumps(record))
        local.chmod(0o600)
        cli.adb("push", str(local), AUTH_FILE + ".next")
    cli.adb("shell", "chown", "0:0", AUTH_FILE + ".next")
    cli.adb("shell", "chmod", "0600", AUTH_FILE + ".next")
    if check_enrollment() != config:
        cli.adb("shell", "rm", "-f", AUTH_FILE + ".next", check=False)
        raise RuntimeError("enrollment_changed")
    cli.adb("shell", "mv", AUTH_FILE + ".next", AUTH_FILE)
    return record["token"]


def ensure_started(config=None):
    config = config or check_enrollment()
    token = ensure_auth(config)
    expected = hashlib.sha256(Path("/opt/iris.apk").read_bytes()).hexdigest()
    actual = cli.adb("shell", "sha256sum", REMOTE_APK).split()[0]
    if actual != expected:
        raise RuntimeError("iris_binary_changed_rerun_bootstrap")
    cli.adb("forward", "tcp:3000", "tcp:3000")

    def healthy():
        # Authenticate the listener before sending a bearer credential: an Android
        # app can otherwise bind the loopback port while Iris is stopped.
        challenge = secrets.token_hex(32)
        info = request(
            "http://127.0.0.1:3000/collector/health?" + urlencode({"challenge": challenge})
        )
        proof = hmac.new(
            token.encode(), (challenge + ":" + BUILD).encode(), hashlib.sha256
        ).hexdigest()
        if info.get("build") != BUILD or not hmac.compare_digest(str(info.get("proof", "")), proof):
            raise RuntimeError("unexpected_iris_server")
        return token

    try:
        return healthy()
    except OSError:
        pass
    stop()
    # All shell fragments are constants. No credentials or user content enters this command.
    cli.adb(
        "shell",
        f"CLASSPATH={REMOTE_APK} app_process / {ENTRY} >/dev/null 2>&1 & echo $! > {PID_FILE}",
    )
    for _ in range(10):
        try:
            return healthy()
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("iris_start_failed")


def upgrade_binary(expected_sha):
    """Explicit component migration; caller must first stop iris-collector."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha or ""):
        raise ValueError("An exact previous Iris APK SHA-256 is required")
    cli.connect()
    config = check_enrollment()
    actual = cli.adb("shell", "sha256sum", REMOTE_APK).split()[0]
    if actual != expected_sha:
        raise RuntimeError("iris_previous_binary_mismatch")
    staged, backup = REMOTE_APK + ".next", REMOTE_APK + ".backup-" + actual
    wanted = hashlib.sha256(Path("/opt/iris.apk").read_bytes()).hexdigest()
    cli.adb("push", "/opt/iris.apk", staged)
    try:
        if cli.adb("shell", "sha256sum", staged).split()[0] != wanted:
            raise RuntimeError("iris_upload_checksum_mismatch")
        if check_enrollment() != config:
            raise RuntimeError("enrollment_changed")
        cli.adb("shell", "chmod", "0444", staged)
        cli.adb("shell", "cp", REMOTE_APK, backup)
        stop()
        cli.adb("shell", "mv", staged, REMOTE_APK)
        try:
            ensure_started()
        except BaseException:
            stop()
            cli.adb("shell", "cp", backup, REMOTE_APK)
            raise
    finally:
        cli.adb("shell", "rm", "-f", staged, check=False)
    return {"build": BUILD, "previous_sha256": actual, "sha256": wanted}


def make_event(config, database_id, row):
    log_id = int(row["log_id"])
    if not 0 < log_id <= 9223372036854775807:
        raise RuntimeError("unsupported_log_id")
    epoch = identity(config)
    return {
        "event_id": str(uuid.uuid5(uuid.UUID(epoch), f"{database_id}:{log_id}")),
        "device_id": config["device_id"],
        "enrollment_epoch": epoch,
        "source_seq": log_id,
        "source": "iris_db",
        "kind": "db_row",
        "package_name": "com.kakao.talk",
        "notification_key": "iris:" + row["chat_id"],
        "observed_at": datetime.now(UTC).isoformat(),
        "payload": {
            "messages": [
                {
                    "body": row["message"],
                    "sender": row["sender_id"],
                    "timestamp": max(0, int(row["created_at"])) * 1000,
                }
            ],
            "truncated": row["truncated"],
        },
        "database_ref": {
            "database_id": database_id,
            **{
                k: row[k]
                for k in ("log_id", "chat_id", "sender_id", "message_type", "origin", "is_mine")
            },
        },
    }


class Collector:
    def __init__(self, api=None):
        self.api = api or self.api_request
        self.epoch = str(uuid.UUID(int=0))
        self.last_seq = 0
        self.database_id = None
        self.metadata_checked = 0
        self.iris_token = None

    def api_request(self, path, payload=None):
        return request(
            os.getenv("API_URL", "http://api:8000") + path,
            payload,
            Path("/run/secrets/ingest_token").read_text().strip(),
        )

    def heartbeat(self, allowed, connected):
        self.api(
            "/internal/v1/heartbeat",
            {
                "device_id": os.getenv("DEVICE_ID", "personal-tablet"),
                "enrollment_epoch": self.epoch,
                "source": "iris_db",
                "database_id": self.database_id,
                "secondary_login_confirmed": allowed,
                "listener_connected": connected,
                "outbox_depth": 0,
                "last_source_seq": self.last_seq,
            },
        )

    def tick(self):
        cli.connect()
        config = check_enrollment()
        self.epoch = identity(config)
        progress = self.api("/internal/v1/iris/cursor?" + urlencode({"epoch": self.epoch}))
        self.last_seq = progress["after"]
        self.iris_token = ensure_started(config)
        page = request(
            "http://127.0.0.1:3000/collector/rows?" + urlencode({"after": self.last_seq}),
            token=self.iris_token,
        )
        if page["build"] != BUILD or page["enrollment_epoch"] != config["enrollment_epoch"]:
            raise RuntimeError("iris_identity_mismatch")
        if progress["database_id"] not in (None, page["database_id"]):
            raise RuntimeError("iris_database_changed_requires_new_epoch")
        if int(page["high_water"]) < self.last_seq:
            raise RuntimeError("iris_database_regressed_requires_new_epoch")
        # Check again after querying. Never ingest a page after observing revocation.
        if check_enrollment() != config:
            raise RuntimeError("enrollment_changed")
        self.database_id = page["database_id"]
        events = [make_event(config, self.database_id, row) for row in page["rows"]]
        seqs = [e["source_seq"] for e in events]
        if seqs != sorted(set(seqs)) or any(s <= self.last_seq for s in seqs):
            raise RuntimeError("iris_invalid_page_order")
        self.heartbeat(True, True)
        # One event at a time: a rejected row must not be skipped by a later committed cursor.
        for event in events:
            if check_enrollment() != config:
                raise RuntimeError("enrollment_changed")
            result = self.api(
                "/internal/v1/observations:batch", {"schema_version": 1, "events": [event]}
            )
            ack = result["results"][0]
            if ack.get("event_id") != event["event_id"] or ack.get("status") not in (
                "committed",
                "duplicate",
            ):
                raise RuntimeError("iris_row_rejected")
            self.last_seq = event["source_seq"]
        self.heartbeat(True, True)
        # Metadata is refreshed independently: names must not change a committed row's identity.
        if time.monotonic() - self.metadata_checked > 10:
            self.metadata_checked = time.monotonic()
            try:
                self.refresh_metadata(config)
            except (OSError, ValueError, KeyError, RuntimeError):
                print('{"iris_metadata":"unavailable","action":"check_profile_lookup"}', flush=True)
        return len(events)

    def refresh_metadata(self, config):
        targets = self.api(
            "/internal/v1/iris/metadata-targets?" + urlencode({"epoch": self.epoch})
        )["items"]
        if not targets:
            return
        if check_enrollment() != config:
            raise RuntimeError("enrollment_changed")
        result = request(
            "http://127.0.0.1:3000/collector/metadata", {"targets": targets}, self.iris_token
        )
        if (
            result["build"] != BUILD
            or result["enrollment_epoch"] != config["enrollment_epoch"]
            or result["database_id"] != self.database_id
        ):
            raise RuntimeError("iris_metadata_identity_mismatch")
        if check_enrollment() != config:
            raise RuntimeError("enrollment_changed")
        self.api(
            "/internal/v1/iris/metadata",
            {
                "device_id": config["device_id"],
                "enrollment_epoch": self.epoch,
                "database_id": self.database_id,
                "items": result["items"],
            },
        )


def watch():
    collector = Collector()
    while True:
        try:
            count = collector.tick()
            print(json.dumps({"iris": "polling", "committed_rows": count}), flush=True)
            time.sleep(0.2 if count == 50 else 3)
        except (
            OSError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ):
            # No exception interpolation: transport errors can include sensitive upstream content.
            try:
                stop()
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            try:
                collector.heartbeat(False, False)
            except (OSError, ValueError, RuntimeError):
                pass
            print(
                '{"iris":"locked_or_unavailable","action":"check_setup_login_and_database"}',
                flush=True,
            )
            time.sleep(10)
