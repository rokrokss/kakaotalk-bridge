import hashlib
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from device import iris
from device.enrollment import Snapshot
from server.app import create_app
from server.config import Settings
from server.maintenance import backup, restore
from server.models import Observation
from server.store import Store, digest
from tests.test_api import DEVICE, INGEST, READ, auth, event

CONFIG = {
    "device_id": "personal-tablet",
    "enrollment_epoch": "d0ca9a35-a86f-4f7f-b0b2-c2c1a0b1c36b",
    "approved_user_id": "123",
    "device_fingerprint": "test-build",
}


def snapshot(config=CONFIG):
    return Snapshot(
        config=deepcopy(config),
        legacy=False,
        characteristics="tablet",
        fingerprint="test-build",
        width=1200,
        height=1920,
        dpi=240,
        kakao_version=29260820,
        account_ids=(123,),
    )


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


@pytest.fixture(autouse=True)
def fresh_apk_hash():
    iris.local_apk_sha.cache_clear()
    yield
    iris.local_apk_sha.cache_clear()


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
        monkeypatch.setattr(iris.enrollment, "require_approved", lambda: snapshot())
        monkeypatch.setattr(iris, "ensure_started", Mock(return_value="a" * 43))
        monkeypatch.setattr(iris, "healthy", Mock())
        page = {
            "build": iris.BUILD,
            "enrollment_epoch": CONFIG["enrollment_epoch"],
            "database_id": "1:100",
            "high_water": "11",
            "has_more": False,
            "rows": [row(), row(11)],
        }

        def response(url, payload=None, token=None):
            assert token == "a" * 43
            if payload is None:
                return deepcopy(page)
            assert url == "http://127.0.0.1:3000/collector/metadata"
            assert 1 <= len(payload["targets"]) <= 50
            return {
                key: value
                for key, value in page.items()
                if key not in ("rows", "high_water", "has_more")
            } | {"items": [], "self_identity_source": "local_account"}

        monkeypatch.setattr(iris, "request", response)
        yield collector, client, page


def messages(client):
    return client.get("/v1/messages", headers=auth()).json()["items"]


def test_iris_end_to_end_ids_history_and_repeat_text(pipeline):
    collector, client, page = pipeline
    assert collector.tick() == 2
    items = messages(client)
    assert len(items) == 2 and items[0]["body"] == items[1]["body"]
    assert all(i["source"] == "iris_db" and not i["ambiguity"] for i in items)
    assert items[0]["conversation_ref"].endswith(":9007199254740993")
    assert items[0]["database_ref"]["origin"] == "SYNCMSG"  # History not filtered out.
    assert items[0]["database_ref"]["is_mine"] is False
    assert client.get("/v1/checkpoint", headers=auth()).json()["cursor"] == 2
    status = client.get("/v1/status", headers=auth()).json()
    assert status["state"] == "collecting_partial"
    assert status["bridge"]["kakao_version"] == 29260820
    assert status["coverage"]["scope"] == "redroid_local_database_rows"
    assert not status["coverage"]["complete"]
    assert not status["coverage"]["phone_session_monitoring"]
    assert status["identity_metadata"]["self_identity_source"] == "local_account"
    page["rows"] = []
    assert collector.tick() == 0


def test_page_commits_in_one_request(pipeline):
    collector, _client, page = pipeline
    batches = []
    real_api = collector.api

    def counting(path, payload=None):
        if path.endswith("observations:batch"):
            batches.append(len(payload["events"]))
        return real_api(path, payload)

    collector.api = counting
    collector.tick()
    assert batches == [2]
    page["rows"] = [row(seq, message="가" * 16000) for seq in range(12, 112)]
    page["high_water"] = "111"
    collector.tick()
    # Large pages are split under the API body limit, still in order.
    assert sum(batches[1:]) == 100 and len(batches) > 2


def test_lost_ack_restarts_from_server_commit(pipeline):
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
    store = client.app.state.store
    assert store.iris_progress("personal-tablet", iris.identity(CONFIG))["after"] == 11
    page["rows"] = [row(12)]
    page["high_water"] = "12"
    # New process has no local cursor or persistent outbox dependency.
    restarted = iris.Collector(real_api)
    assert restarted.tick() == 1
    assert len(messages(client)) == 3


def test_unstorable_row_is_recorded_and_later_rows_continue(pipeline):
    collector, client, page = pipeline
    page["rows"][0]["message"] = "x" * 16385
    assert collector.tick() == 2
    store = client.app.state.store
    assert store.iris_progress("personal-tablet", iris.identity(CONFIG))["after"] == 11
    assert [i["body"] for i in messages(client)] == ["알림을 끈 방의 메시지"]
    assert client.get("/v1/status", headers=auth()).json()["coverage"]["skipped_rows"] == 1


def test_rows_iris_could_not_decode_advance_without_messages(pipeline):
    collector, client, page = pipeline
    page["rows"][0] = {
        "log_id": "10",
        "chat_id": "9007199254740993",
        "sender_id": "123",
        "message_type": "1",
        "created_at": 1791072000,
        "skipped": "decrypt_failed",
    }
    assert collector.tick() == 2
    assert len(messages(client)) == 1
    with client.app.state.store.connect() as db:
        stored = json.loads(
            db.execute("SELECT body FROM observations WHERE source_seq=10").fetchone()[0]
        )
    assert stored["kind"] == "db_row_skipped"
    assert stored["database_ref"]["skip_reason"] == "decrypt_failed"
    assert stored["payload"]["messages"] == []


def test_rejected_skip_marker_still_stops_collection(pipeline):
    collector, _client, _page = pipeline
    collector.api = Mock(
        side_effect=lambda path, payload=None: (
            {"after": 0, "database_id": None}
            if "cursor" in path
            else {"results": [{"index": 0, "status": "rejected", "reason": "invalid_event"}] * 2}
            if path.endswith("observations:batch")
            else {}
        )
    )
    with pytest.raises(RuntimeError, match="iris_row_rejected"):
        collector.tick()


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


def test_digest_matches_rows_committed_by_the_previous_release():
    # Digests computed by v0.1.0, which serialized the retired notification fields.
    expected = {
        "10": "14bdd2600896cf3492e1e560489c5abe6ce08d6e5485838ce47439414f61d6da",
        "11": "2304942c55cc20addc15fb3a865bf8f8915d40021a61b7d20ead77b5d98da268",
    }
    for record in (row(), row(11, is_mine=True, truncated=True, origin="", message="")):
        event = Observation.model_validate(iris.make_event(CONFIG, "1:100", record))
        assert digest(event) == expected[record["log_id"]]


@pytest.mark.parametrize("change", [{"database_id": "1:200"}, {"high_water": "9"}])
def test_database_replacement_or_rollback_is_blocked(pipeline, change):
    collector, _client, page = pipeline
    collector.tick()
    page.update(change, rows=[])
    with pytest.raises(RuntimeError, match="requires_new_epoch"):
        collector.tick()


def test_revocation_after_fetch_blocks_ingestion(pipeline, monkeypatch):
    collector, client, _page = pipeline
    check = Mock(side_effect=[snapshot(), RuntimeError("revoked")])
    monkeypatch.setattr(iris.enrollment, "require_approved", check)
    with pytest.raises(RuntimeError, match="revoked"):
        collector.tick()
    assert messages(client) == []


def test_unapproved_never_starts_or_reads_iris(pipeline, monkeypatch):
    collector, _client, _page = pipeline
    monkeypatch.setattr(
        iris.enrollment, "require_approved", Mock(side_effect=RuntimeError("approval_required"))
    )
    with pytest.raises(RuntimeError, match="approval_required"):
        collector.tick()
    iris.ensure_started.assert_not_called()


def test_api_rejects_rows_from_another_enrollment_or_unapproved_collector(pipeline):
    collector, client, _page = pipeline
    collector.tick()
    other = client.post(
        "/internal/v1/observations:batch",
        headers=auth(INGEST),
        json={
            "schema_version": 1,
            "events": [event(enrollment_epoch="0e7d6f4c-6a90-4a8e-8e4f-7d0f7b8b7c1a")],
        },
    )
    assert other.status_code == 423
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


def apk_device(monkeypatch, remote_sha, health):
    """Fake ADB device for start-up tests. Returns the recorded calls."""
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("shell", "sha256sum"):
            return (
                hashlib.sha256(b"current apk").hexdigest()
                if args[2].endswith(".next")
                else remote_sha
            ) + " file"
        if args == ("shell", "cat", iris.AUTH_FILE):
            return json.dumps({"enrollment_epoch": CONFIG["enrollment_epoch"], "token": "a" * 43})
        return ""

    monkeypatch.setattr(iris.cli, "adb", adb)
    monkeypatch.setattr(iris.Path, "read_bytes", lambda self: b"current apk")
    monkeypatch.setattr(iris, "healthy", health)
    monkeypatch.setattr(iris.time, "sleep", lambda seconds: None)
    return calls


def test_running_current_build_is_reused_without_reinstalling(monkeypatch):
    calls = apk_device(monkeypatch, "0" * 64, Mock())
    assert iris.ensure_started(CONFIG["enrollment_epoch"]) == "a" * 43
    assert calls == [("shell", "cat", iris.AUTH_FILE)]


def test_older_or_stopped_iris_is_replaced_with_this_images_build(monkeypatch):
    health = Mock(side_effect=[RuntimeError("unexpected_iris_server"), OSError("starting"), None])
    calls = apk_device(monkeypatch, "0" * 64, health)
    assert iris.ensure_started(CONFIG["enrollment_epoch"]) == "a" * 43
    pushed = [c for c in calls if c[0] == "push"]
    assert pushed == [("push", iris.LOCAL_APK, iris.REMOTE_APK + ".next")]
    assert any(
        c[:2]
        == (
            "shell",
            f"chmod 0444 {iris.REMOTE_APK}.next && mv {iris.REMOTE_APK}.next {iris.REMOTE_APK}",
        )
        for c in calls
    )
    started = [c for c in calls if "app_process" in " ".join(c)]
    assert len(started) == 1 and iris.REMOTE_APK in started[0][1]
    stop = next(c for c in calls if "kill" in " ".join(c))
    assert iris.PID_FILE in stop[1] and iris.LEGACY_PID_FILE in stop[1]
    assert calls[-1][1].startswith("rm -rf /data/local/tmp/kakaocollector-iris.apk*")
    assert iris.enrollment.LEGACY_ENROLLMENT in calls[-1][1]


def test_same_build_already_on_device_is_not_uploaded_again(monkeypatch):
    current = hashlib.sha256(b"current apk").hexdigest()
    health = Mock(side_effect=[OSError("stopped"), None])
    calls = apk_device(monkeypatch, current, health)
    iris.ensure_started(CONFIG["enrollment_epoch"])
    assert not any(c[0] == "push" for c in calls)


def test_upload_checksum_mismatch_never_replaces_the_installed_build(monkeypatch):
    calls = apk_device(monkeypatch, "0" * 64, Mock(side_effect=OSError("stopped")))
    monkeypatch.setattr(iris.Path, "read_bytes", lambda self: b"different apk")
    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        iris.ensure_started(CONFIG["enrollment_epoch"])
    assert not any("mv" in " ".join(c) and iris.REMOTE_APK in " ".join(c) for c in calls[:-1])


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
    token = iris.ensure_auth(CONFIG["enrollment_epoch"])
    assert token != remote["token"] and len(token) == 43
    assert pushed == [{"enrollment_epoch": CONFIG["enrollment_epoch"], "token": token}]
    assert (
        "shell",
        f"mkdir -p {iris.HOME} && chown 0:0 {iris.HOME} && chmod 700 {iris.HOME}",
    ) in calls
    staged = iris.AUTH_FILE + ".next"
    assert (
        "shell",
        f"chown 0:0 {staged} && chmod 600 {staged} && mv {staged} {iris.AUTH_FILE}",
    ) in calls
    assert all(token not in " ".join(args) for args in calls)
    remote.update(pushed[0])
    assert iris.ensure_auth(CONFIG["enrollment_epoch"]) == token
    assert len(pushed) == 1


def test_iris_never_sends_bearer_to_an_impostor_listener(monkeypatch):
    monkeypatch.setattr(iris, "ensure_auth", lambda epoch: "a" * 43)
    monkeypatch.setattr(iris.Path, "read_bytes", lambda path: b"apk")
    monkeypatch.setattr(iris.cli, "adb", lambda *a, **k: hashlib.sha256(b"apk").hexdigest())

    def impostor(url, payload=None, token=None):
        assert token is None
        assert "/collector/health?challenge=" in url
        return {"build": iris.BUILD, "proof": "0" * 64}

    monkeypatch.setattr(iris, "request", impostor)
    with pytest.raises(RuntimeError, match="unexpected_iris_server"):
        iris.ensure_started(CONFIG["enrollment_epoch"])
