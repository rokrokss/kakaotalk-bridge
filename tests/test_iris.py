import hashlib
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from device import iris
from server.app import create_app
from server.config import Settings
from server.maintenance import backup, restore
from server.models import Observation
from server.store import Store
from tests.test_api import DEVICE, INGEST, READ, auth, event

CONFIG = {
    "device_id": "personal-tablet",
    "collector_mode": "iris",
    "enrollment_epoch": "d0ca9a35-a86f-4f7f-b0b2-c2c1a0b1c36b",
    "secondary_login_version": 123,
    "device_fingerprint": "test-build",
}


def row(log_id=10, **changes):
    return {
        "log_id": str(log_id),
        "chat_id": "9007199254740993",
        "sender_id": "123",
        "message": "알림을 끈 방의 메시지",
        "message_type": "1",
        "created_at": 1791072000,
        "origin": "SYNCMSG",
        "is_mine": False,
        "truncated": False,
        **changes,
    }


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    app = create_app(Settings(str(tmp_path / "iris.db"), INGEST, READ, DEVICE))
    with TestClient(app) as client:

        def api(path, payload=None):
            response = (
                client.get(path, headers=auth(INGEST))
                if payload is None
                else client.post(path, json=payload, headers=auth(INGEST))
            )
            response.raise_for_status()
            return response.json()

        collector = iris.Collector(api)
        monkeypatch.setattr(iris.cli, "connect", Mock())
        monkeypatch.setattr(iris, "check_enrollment", lambda: deepcopy(CONFIG))
        monkeypatch.setattr(iris, "ensure_started", Mock(return_value="a" * 43))
        page = {
            "build": iris.BUILD,
            "enrollment_epoch": CONFIG["enrollment_epoch"],
            "database_id": "1:100",
            "high_water": "11",
            "rows": [row(), row(11)],
        }

        def response(url, payload=None, token=None):
            assert token == "a" * 43
            if payload is None:
                return deepcopy(page)
            assert url == "http://127.0.0.1:3000/collector/metadata"
            assert 1 <= len(payload["targets"]) <= 50
            return {
                key: value for key, value in page.items() if key not in ("rows", "high_water")
            } | {"items": []}

        monkeypatch.setattr(iris, "request", response)
        yield collector, client, page


def test_iris_end_to_end_ids_history_and_repeat_text(pipeline):
    collector, client, page = pipeline
    assert collector.tick() == 2
    items = client.get("/v1/messages", headers=auth()).json()["items"]
    assert len(items) == 2 and items[0]["body"] == items[1]["body"]
    assert all(i["source"] == "iris_db" and not i["ambiguity"] for i in items)
    assert items[0]["conversation_ref"].endswith(":9007199254740993")
    assert items[0]["database_ref"]["origin"] == "SYNCMSG"  # History not filtered out.
    assert items[0]["database_ref"]["is_mine"] is False
    assert client.get("/v1/checkpoint", headers=auth()).json()["cursor"] == 2
    filtered = client.get(
        "/v1/messages", params={"conversation_ref": items[0]["conversation_ref"]}, headers=auth()
    ).json()
    assert len(filtered["items"]) == 2
    assert (
        client.get("/v1/conversations", headers=auth()).json()["items"][0]["identity_confidence"]
        == "database_id"
    )
    status = client.get("/v1/status", headers=auth()).json()
    assert status["state"] == "collecting_partial"
    assert status["coverage"]["scope"] == "redroid_local_database_rows"
    assert not status["coverage"]["complete"]
    assert not status["coverage"]["phone_session_monitoring"]
    page["rows"] = []
    assert collector.tick() == 0


def test_lost_ack_restarts_from_server_commit(pipeline, monkeypatch):
    collector, client, page = pipeline
    real_api = collector.api

    def lost_ack(path, payload=None):
        result = real_api(path, payload)
        if path.endswith("observations:batch"):
            raise OSError("ACK lost after commit")
        return result

    collector.api = lost_ack
    with pytest.raises(OSError):
        collector.tick()
    assert (
        client.app.state.store.iris_progress("personal-tablet", iris.identity(CONFIG))["after"]
        == 10
    )
    page["rows"] = [row(11)]
    # New process has no local cursor or persistent outbox dependency.
    restarted = iris.Collector(real_api)
    assert restarted.tick() == 1
    assert len(client.get("/v1/messages", headers=auth()).json()["items"]) == 2


def test_poison_row_blocks_later_cursor(pipeline):
    collector, client, page = pipeline
    page["rows"][0]["message"] = "x" * 16385
    with pytest.raises(RuntimeError, match="iris_row_rejected"):
        collector.tick()
    assert (
        client.app.state.store.iris_progress("personal-tablet", iris.identity(CONFIG))["after"] == 0
    )
    assert client.get("/v1/messages", headers=auth()).json()["items"] == []


def test_replay_uses_row_identity_not_poll_timestamp(pipeline):
    collector, _client, _page = pipeline
    collector.tick()
    replay = iris.make_event(CONFIG, "1:100", row())
    result = collector.api(
        "/internal/v1/observations:batch", {"schema_version": 1, "events": [replay]}
    )
    assert result["results"][0]["status"] == "duplicate"
    replay["payload"]["messages"][0]["body"] = "edited"
    result = collector.api(
        "/internal/v1/observations:batch", {"schema_version": 1, "events": [replay]}
    )
    assert result["results"][0]["reason"] == "event_id_conflict"


@pytest.mark.parametrize("change", [{"database_id": "1:200"}, {"high_water": "9"}])
def test_database_replacement_or_rollback_is_blocked(pipeline, change):
    collector, _client, page = pipeline
    collector.tick()
    page.update(change, rows=[])
    with pytest.raises(RuntimeError, match="requires_new_epoch"):
        collector.tick()


def test_revocation_after_fetch_blocks_ingestion(pipeline, monkeypatch):
    collector, client, _page = pipeline
    check = Mock(side_effect=[deepcopy(CONFIG), RuntimeError("revoked")])
    monkeypatch.setattr(iris, "check_enrollment", check)
    with pytest.raises(RuntimeError, match="revoked"):
        collector.tick()
    assert client.get("/v1/messages", headers=auth()).json()["items"] == []


def test_unconfirmed_never_starts_or_reads_iris(pipeline, monkeypatch):
    collector, _client, _page = pipeline
    monkeypatch.setattr(iris, "check_enrollment", Mock(side_effect=RuntimeError("locked")))
    with pytest.raises(RuntimeError, match="locked"):
        collector.tick()
    iris.ensure_started.assert_not_called()


def test_api_rejects_wrong_source_or_unconfirmed_iris(pipeline):
    collector, client, _page = pipeline
    collector.tick()
    wrong_source = client.post(
        "/internal/v1/observations:batch",
        headers=auth(INGEST),
        json={"schema_version": 1, "events": [event()]},
    )
    assert wrong_source.status_code == 423
    collector.heartbeat(False, False)
    response = client.post(
        "/internal/v1/observations:batch",
        headers=auth(INGEST),
        json={"schema_version": 1, "events": [iris.make_event(CONFIG, "1:100", row(12))]},
    )
    assert response.status_code == 423


def test_iris_cursor_survives_retention_and_encrypted_restore(pipeline, tmp_path, monkeypatch):
    collector, client, _page = pipeline
    collector.tick()
    store = client.app.state.store
    with store.connect() as db:
        db.execute("UPDATE observations SET received_at='2000-01-01T00:00:00+00:00'")
        db.execute("UPDATE candidates SET received_at='2000-01-01T00:00:00+00:00'")
    store.prune(30)
    key = tmp_path / "key"
    key.write_text("a1" * 32)
    monkeypatch.setenv("BACKUP_KEY_FILE", str(key))
    backup(store.path, str(tmp_path / "iris.kcb"))
    restore(str(tmp_path / "iris.kcb"), str(tmp_path / "restored.db"))
    restored = Store(str(tmp_path / "restored.db"))
    assert restored.messages()["items"] == []
    assert restored.iris_progress("personal-tablet", iris.identity(CONFIG)) == {
        "after": 11,
        "database_id": "1:100",
    }


def test_legacy_notification_digest_survives_model_extension(tmp_path):
    store = Store(str(tmp_path / "legacy.db"))
    record = Observation.model_validate(event())
    store.ingest(record)
    old_body = record.model_dump(mode="json", exclude={"database_ref"})
    digest = hashlib.sha256(
        json.dumps(old_body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with store.connect() as db:
        db.execute("UPDATE observations SET digest=?", (digest,))
    assert store.ingest(record) == "duplicate"


@pytest.mark.parametrize(
    "change",
    [
        {"collector_mode": "notification"},
        {"secondary_login_version": 0},
        {"secondary_login_version": 124},
        {"device_fingerprint": "other-build"},
        {"device_id": "other-account-device"},
    ],
)
def test_runtime_gate_rejects_changed_registration(monkeypatch, change):
    config = {**CONFIG, **change}
    monkeypatch.setattr(iris.cli, "adb", lambda *args: json.dumps(config))
    monkeypatch.setattr(
        iris.login_guard,
        "device_signature",
        lambda adb: {"kakao_version": 123, "fingerprint": "test-build"},
    )
    with pytest.raises(RuntimeError):
        iris.check_enrollment()


def test_runtime_gate_accepts_matching_iris_registration(monkeypatch):
    monkeypatch.setattr(iris.cli, "adb", lambda *args: json.dumps(CONFIG))
    monkeypatch.setattr(
        iris.login_guard,
        "device_signature",
        lambda adb: {"kakao_version": 123, "fingerprint": "test-build"},
    )
    assert iris.check_enrollment() == CONFIG


def test_explicit_iris_upgrade_verifies_previous_and_staged_apk(monkeypatch):
    calls = []
    old = "1" * 64
    new = hashlib.sha256(b"candidate apk").hexdigest()

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("shell", "sha256sum"):
            return (new if args[-1].endswith(".next") else old) + " file"
        return ""

    monkeypatch.setattr(iris.cli, "adb", adb)
    monkeypatch.setattr(iris.cli, "connect", lambda: None)
    monkeypatch.setattr(iris, "check_enrollment", lambda: CONFIG)
    monkeypatch.setattr(iris.Path, "read_bytes", lambda self: b"candidate apk")
    monkeypatch.setattr(iris, "stop", lambda: calls.append(("stop-iris-only",)))
    monkeypatch.setattr(iris, "ensure_started", lambda: calls.append(("start-iris-only",)))
    with pytest.raises(RuntimeError, match="previous_binary_mismatch"):
        iris.upgrade_binary("2" * 64)
    assert not any(c[0] == "stop-iris-only" for c in calls)
    assert iris.upgrade_binary(old)["sha256"] == new
    assert ("shell", "mv", iris.REMOTE_APK + ".next", iris.REMOTE_APK) in calls
    assert not any("am" in c or "pm" in c for c in calls)


def test_explicit_iris_upgrade_restores_previous_apk_on_start_failure(monkeypatch):
    calls = []
    old = "1" * 64
    new = hashlib.sha256(b"candidate").hexdigest()
    monkeypatch.setattr(iris.cli, "connect", lambda: None)
    monkeypatch.setattr(iris, "check_enrollment", lambda: CONFIG)
    monkeypatch.setattr(iris.Path, "read_bytes", lambda self: b"candidate")

    def adb(*args, **kwargs):
        calls.append(args)
        return (
            ((new if args[-1].endswith(".next") else old) + " file")
            if args[:2] == ("shell", "sha256sum")
            else ""
        )

    monkeypatch.setattr(iris.cli, "adb", adb)
    monkeypatch.setattr(iris, "stop", lambda: None)
    monkeypatch.setattr(iris, "ensure_started", Mock(side_effect=RuntimeError("start_failed")))
    with pytest.raises(RuntimeError, match="start_failed"):
        iris.upgrade_binary(old)
    assert ("shell", "cp", iris.REMOTE_APK + ".backup-" + old, iris.REMOTE_APK) in calls


def test_iris_credentials_are_private_and_rotate_with_enrollment(monkeypatch):
    calls, pushed = [], []
    remote = {"enrollment_epoch": "old", "token": "b" * 43}

    def adb(*args, **kwargs):
        calls.append(args)
        if args == ("shell", "cat", iris.AUTH_FILE):
            return json.dumps(remote)
        if args[0] == "push":
            source = iris.Path(args[1])
            assert source.stat().st_mode & 0o777 == 0o600
            pushed.append(json.loads(source.read_text()))
        return ""

    monkeypatch.setattr(iris.cli, "adb", adb)
    monkeypatch.setattr(iris, "check_enrollment", lambda: CONFIG)
    token = iris.ensure_auth(CONFIG)
    assert token != remote["token"] and len(token) == 43
    assert pushed == [{"enrollment_epoch": CONFIG["enrollment_epoch"], "token": token}]
    assert ("shell", "chmod", "0700", iris.AUTH_DIR) in calls
    assert ("shell", "chmod", "0600", iris.AUTH_FILE + ".next") in calls
    assert all(token not in " ".join(args) for args in calls)
    remote.update(pushed[0])
    assert iris.ensure_auth(CONFIG) == token
    assert len(pushed) == 1


def test_iris_never_sends_bearer_to_an_impostor_listener(monkeypatch):
    token = "a" * 43
    monkeypatch.setattr(iris, "ensure_auth", lambda config: token)
    monkeypatch.setattr(iris.Path, "read_bytes", lambda path: b"apk")
    monkeypatch.setattr(iris.cli, "adb", lambda *a, **k: hashlib.sha256(b"apk").hexdigest())

    def impostor(url, payload=None, token=None):
        assert token is None
        assert "/collector/health?challenge=" in url
        return {"build": iris.BUILD, "proof": "0" * 64}

    monkeypatch.setattr(iris, "request", impostor)
    with pytest.raises(RuntimeError, match="unexpected_iris_server"):
        iris.ensure_started(CONFIG)
