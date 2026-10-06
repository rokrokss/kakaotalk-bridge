from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.models import Observation

INGEST, READ, DEVICE = "i" * 64, "r" * 64, "d" * 64


def auth(token=READ):
    return {"Authorization": f"Bearer {token}"}


EPOCH = "d0ca9a35-a86f-4f7f-b0b2-c2c1a0b1c36b"
DATABASE = "1:100"


def event(seq=1, body="안녕하세요", **changes):
    return {
        "event_id": str(uuid4()),
        "device_id": "personal-tablet",
        "enrollment_epoch": EPOCH,
        "source_seq": seq,
        "source": "iris_db",
        "kind": "db_row",
        "package_name": "com.kakao.talk",
        "notification_key": "iris:42",
        "observed_at": "2026-10-04T00:00:00Z",
        "payload": {"messages": [{"body": body, "sender": "7", "timestamp": 1791072000000}]},
        "database_ref": {
            "database_id": DATABASE,
            "log_id": str(seq),
            "chat_id": "42",
            "sender_id": "7",
            "message_type": "1",
        },
        **changes,
    }


def skipped_event(seq, reason="decrypt_failed"):
    record = event(seq, kind="db_row_skipped")
    record["payload"] = {"messages": []}
    record["database_ref"]["skip_reason"] = reason
    return record


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(str(tmp_path / "test.db"), INGEST, READ, DEVICE))
    with TestClient(app) as c:
        approve_fixture(c)
        yield c


def approve_fixture(client):
    return client.post(
        "/internal/v1/heartbeat",
        headers=auth(INGEST),
        json={
            "device_id": "personal-tablet",
            "enrollment_epoch": EPOCH,
            "database_id": DATABASE,
            "listener_connected": True,
            "secondary_login_confirmed": True,
            "last_source_seq": 0,
        },
    )


def post(client, *events):
    return client.post(
        "/internal/v1/observations:batch",
        headers=auth(INGEST),
        json={"schema_version": 1, "events": events},
    )


def test_auth_scopes_and_no_message_echo(client):
    for token in ["", INGEST, DEVICE]:
        assert client.get("/v1/messages", headers=auth(token)).status_code == 401
    assert client.get("/v1/messages", headers=auth()).status_code == 200
    response = client.post(
        "/internal/v1/observations:batch",
        headers=auth(READ),
        json={"schema_version": 1, "events": [event()]},
    )
    assert response.status_code == 401
    response = client.post(
        "/internal/v1/observations:batch",
        headers=auth(INGEST),
        json={"private_message": "secret text"},
    )
    assert response.status_code == 422
    assert "secret text" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_checkpoint_is_read_scoped_and_tracks_committed_messages(client):
    assert client.get("/v1/checkpoint", headers=auth(INGEST)).status_code == 401
    before = client.get("/v1/checkpoint", headers=auth()).json()
    assert before["cursor"] == 0
    post(client, event())
    after = client.get("/v1/checkpoint", headers=auth()).json()
    assert after["cursor"] == 1 and after["cursor_epoch"] == before["cursor_epoch"]


def test_lost_ack_retry_and_real_repeated_text(client):
    original = event()
    assert post(client, original).json()["results"][0]["status"] == "committed"
    assert post(client, original).json()["results"][0]["status"] == "duplicate"
    assert post(client, event(seq=2)).json()["results"][0]["status"] == "committed"
    items = client.get("/v1/messages", headers=auth()).json()["items"]
    assert len(items) == 2
    assert [i["body"] for i in items] == ["안녕하세요", "안녕하세요"]


def test_conflicting_id_or_seq_is_not_silently_acked(client):
    original = event()
    post(client, original)
    changed = {**original, "payload": {"messages": [{"body": "different", "sender": "7"}]}}
    assert post(client, changed).json()["results"][0]["reason"] == "event_id_conflict"
    assert post(client, event()).json()["results"][0]["reason"] == "source_seq_conflict"


def test_rejected_row_holds_back_later_rows(client):
    invalid = event(package_name="another.app")
    response = post(client, invalid, event(seq=2))
    assert [r["status"] for r in response.json()["results"]] == ["rejected", "not_processed"]
    assert "안녕하세요" not in response.text
    assert client.get("/v1/messages", headers=auth()).json()["items"] == []
    store = client.app.state.store
    assert store.iris_progress("personal-tablet", EPOCH)["after"] == 0


def test_wrong_device_fails_closed(client):
    assert post(client, event(device_id="someone-else")).status_code == 403


def test_skipped_rows_advance_cursor_without_becoming_messages(client):
    response = post(client, event(), skipped_event(2), event(seq=3, body="다음"))
    assert [r["status"] for r in response.json()["results"]] == ["committed"] * 3
    items = client.get("/v1/messages", headers=auth()).json()["items"]
    assert [i["body"] for i in items] == ["안녕하세요", "다음"]
    store = client.app.state.store
    assert store.iris_progress("personal-tablet", EPOCH)["after"] == 3
    assert client.get("/v1/status", headers=auth()).json()["coverage"]["skipped_rows"] == 1
    assert post(client, skipped_event(4)).json()["results"][0]["status"] == "committed"
    assert client.get("/v1/status", headers=auth()).json()["coverage"]["skipped_rows"] == 2
    unmarked = skipped_event(5)
    del unmarked["database_ref"]["skip_reason"]
    assert post(client, unmarked).json()["results"][0]["reason"] == "invalid_event"


def test_event_cursor_pages_keep_identical_occurrences(client):
    post(client, event(body="똑같은 말"), event(seq=2, body="똑같은 말"), event(seq=3, body="다음"))
    page = client.get("/v1/messages?limit=2", headers=auth()).json()
    assert [i["body"] for i in page["items"]] == ["똑같은 말", "똑같은 말"] and page["has_more"]
    second = client.get(f"/v1/messages?after={page['next_cursor']}&limit=2", headers=auth()).json()
    assert [i["body"] for i in second["items"]] == ["다음"]
    assert not second["has_more"]
    assert not second["coverage"]["complete"]
    assert client.get("/v1/messages?limit=201", headers=auth()).status_code == 422
    assert client.get("/v1/messages?after=-1", headers=auth()).status_code == 422


def test_payload_size_limit(client):
    response = client.post(
        "/internal/v1/observations:batch", headers=auth(INGEST), content=b"a" * (1024 * 1024 + 1)
    )
    assert response.status_code == 413


def test_concurrent_retries_are_idempotent(client):
    store = client.app.state.store
    record = Observation.model_validate(event())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.ingest(record), range(20)))
    assert results.count("committed") == 1
    assert results.count("duplicate") == 19


def test_database_failure_never_acks(client, monkeypatch):
    import sqlite3

    def fail(record):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(client.app.state.store, "ingest", fail)
    response = post(client, event())
    assert response.status_code == 503
    assert "committed" not in response.text


def test_heartbeat_is_not_login_or_full_coverage(client):
    heartbeat = {
        "device_id": "personal-tablet",
        "enrollment_epoch": str(uuid4()),
        "listener_connected": True,
        "last_source_seq": 0,
    }
    client.post("/internal/v1/heartbeat", json=heartbeat, headers=auth(INGEST))
    status = client.get("/v1/status", headers=auth()).json()
    assert status["state"] == "needs_attention"
    assert status["coverage"]["login_verified"] is False
    assert status["coverage"]["complete"] is False
    with client.app.state.store.connect() as db:
        old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        db.execute("UPDATE statuses SET received_at=? WHERE kind='bridge'", (old,))
    status = client.get("/v1/status", headers=auth()).json()
    assert status["state"] == "needs_attention"
    assert status["coverage"]["gaps"][0]["reason"] == "heartbeat_stale"
    client.post("/internal/v1/heartbeat", json=heartbeat, headers=auth(INGEST))
    assert any(
        g["reason"] == "heartbeat_gap"
        for g in client.get("/v1/status", headers=auth()).json()["coverage"]["gaps"]
    )


def test_retention_removes_text_and_reports_cursor_gap(client):
    post(client, event())
    store = client.app.state.store
    with store.connect() as db:
        db.execute("UPDATE observations SET received_at='2000-01-01T00:00:00+00:00'")
        db.execute("UPDATE candidates SET received_at='2000-01-01T00:00:00+00:00'")
    store.prune(30)
    result = client.get("/v1/messages", headers=auth()).json()
    assert result["items"] == []
    assert result["coverage"]["pruned_through_cursor"] > 0


def test_restart_preserves_data(tmp_path):
    settings = Settings(str(tmp_path / "persistent.db"), INGEST, READ, DEVICE)
    with TestClient(create_app(settings)) as first:
        approve_fixture(first)
        original = event()
        post(first, original)
    with TestClient(create_app(settings)) as second:
        assert len(second.get("/v1/messages", headers=auth()).json()["items"]) == 1
        assert post(second, original).json()["results"][0]["status"] == "duplicate"


def test_api_denies_collection_until_approved(tmp_path):
    app = create_app(Settings(str(tmp_path / "locked.db"), INGEST, READ, DEVICE))
    with TestClient(app) as client:
        record = event()
        assert post(client, record).status_code == 423
        heartbeat = {
            "device_id": "personal-tablet",
            "enrollment_epoch": EPOCH,
            "database_id": DATABASE,
            "listener_connected": True,
            "last_source_seq": 0,
        }
        client.post("/internal/v1/heartbeat", json=heartbeat, headers=auth(INGEST))
        assert post(client, record).status_code == 423
        assert client.get("/v1/messages", headers=auth()).json()["items"] == []
        heartbeat["secondary_login_confirmed"] = True
        client.post("/internal/v1/heartbeat", json=heartbeat, headers=auth(INGEST))
        assert post(client, record).status_code == 200
        heartbeat["secondary_login_confirmed"] = False
        client.post("/internal/v1/heartbeat", json=heartbeat, headers=auth(INGEST))
        assert post(client, event(seq=2)).status_code == 423
