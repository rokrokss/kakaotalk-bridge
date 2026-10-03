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


def event(seq=1, **changes):
    return {
        "event_id": str(uuid4()),
        "device_id": "personal-tablet",
        "enrollment_epoch": "d0ca9a35-a86f-4f7f-b0b2-c2c1a0b1c36b",
        "source_seq": seq,
        "source": "notification",
        "kind": "posted",
        "package_name": "com.kakao.talk",
        "notification_key": "a-room-key",
        "observed_at": "2026-10-04T00:00:00Z",
        "payload": {"title": "테스트방", "text": "안녕하세요"},
        **changes,
    }


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
            "enrollment_epoch": event()["enrollment_epoch"],
            "listener_connected": True,
            "secondary_login_confirmed": True,
            "outbox_depth": 0,
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
    assert (
        client.get("/v1/messages", params={"conversation_ref": "unrelated"}, headers=auth()).json()[
            "items"
        ]
        == []
    )


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
    changed = {**original, "payload": {"text": "different"}}
    assert post(client, changed).json()["results"][0]["reason"] == "event_id_conflict"
    assert post(client, event()).json()["results"][0]["reason"] == "source_seq_conflict"


def test_poison_event_does_not_block_valid_events(client):
    invalid = event(package_name="another.app")
    response = post(client, invalid, event(seq=2))
    assert [r["status"] for r in response.json()["results"]] == ["rejected", "committed"]
    assert "안녕하세요" not in response.text


def test_wrong_device_fails_closed(client):
    assert post(client, event(device_id="someone-else")).status_code == 403


def test_group_summary_and_removal_are_not_messages(client):
    assert (
        post(
            client,
            event(payload={"text": "3 new messages", "is_group_summary": True}),
            event(seq=2, kind="removed"),
        ).status_code
        == 200
    )
    assert client.get("/v1/messages", headers=auth()).json()["items"] == []


def test_structured_messages_keep_identical_occurrences_and_cursor(client):
    item = {"body": "똑같은 말", "sender": "친구", "timestamp": 1000}
    post(client, event(payload={"messages": [item, item, {**item, "body": "다음"}]}))
    page = client.get("/v1/messages?limit=2", headers=auth()).json()
    assert len(page["items"]) == 2 and page["has_more"]
    second = client.get(f"/v1/messages?after={page['next_cursor']}&limit=2", headers=auth()).json()
    assert [i["body"] for i in second["items"]] == ["다음"]
    assert not second["has_more"]
    assert not second["coverage"]["complete"]


def test_search_is_literal_and_bounded(client):
    post(client, event(payload={"text": "' OR 1=1 --"}), event(seq=2))
    assert (
        len(client.get("/v1/search", params={"q": "' OR 1=1 --"}, headers=auth()).json()["items"])
        == 1
    )
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
        "outbox_depth": 0,
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
