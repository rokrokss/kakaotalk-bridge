import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest

from device import iris
from server.maintenance import backup, restore
from server.outgoing import Claim, Outgoing, SendMessage
from server.store import Store
from tests.test_api import DEVICE, INGEST, READ, auth
from tests.test_iris import CONFIG
from tests.test_iris import pipeline as iris_pipeline

pipeline = iris_pipeline

SEND = "s" * 64


@pytest.fixture
def sending(pipeline):
    collector, client, page = pipeline
    collector.tick()
    ref = client.get("/v2/conversations", headers=auth()).json()["items"][0]["ref"]
    page["rows"] = []
    return (
        collector,
        client,
        page,
        {
            "request_id": str(uuid4()),
            "conversation_ref": ref,
            "text": "안녕하세요 👋\n두 번째 줄",
        },
    )


def enqueue(client, body, token=SEND):
    return client.post("/v1/outgoing", headers=auth(token), json=body)


def status(client, body):
    return client.get("/v1/outgoing/" + body["request_id"], headers=auth(SEND)).json()


def test_send_requires_separate_credential_and_exact_current_room(sending):
    _, client, _, body = sending
    for token in ("", READ, INGEST, DEVICE):
        assert enqueue(client, body, token).status_code == 401
        assert (
            client.get("/v1/outgoing/" + body["request_id"], headers=auth(token)).status_code == 401
        )
    for ref in (
        "some room name",
        "123",
        body["conversation_ref"].replace("personal-tablet", "other"),
    ):
        assert enqueue(client, {**body, "conversation_ref": ref}).status_code == 409
    result = enqueue(client, body)
    assert result.status_code == 200
    assert result.json()["status"] == "queued"
    assert result.json()["delivery_confirmed"] is False
    assert body["text"] not in result.text


@pytest.mark.parametrize("text", ["", "  \n", "a\0b", "a" * 4001, "😀" * 2001, "\ud800"])
def test_invalid_text_never_enters_queue(sending, text):
    _, client, _, body = sending
    response = client.post(
        "/v1/outgoing",
        headers={**auth(SEND), "Content-Type": "application/json"},
        content=json.dumps({**body, "text": text}),
    )
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_concurrent_retries_and_claims_are_single_attempt(sending):
    collector, client, _, body = sending
    outgoing = client.app.state.outgoing
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: outgoing.enqueue(SendMessage(**body)), range(16)))
    assert all(result["status"] == "queued" for result in results)
    assert enqueue(client, {**body, "text": "different"}).status_code == 409
    claim = Claim(enrollment_epoch=collector.epoch, database_id=collector.database_id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: outgoing.claim(claim), range(16)))
    assert sum(row["item"] is not None for row in claimed) == 1
    assert enqueue(client, body).json()["status"] == "dispatching"
    with outgoing.store.connect() as db:
        assert db.execute("SELECT text FROM outgoing").fetchone()[0] is None
        db.execute("UPDATE outgoing SET updated_at=0")
    assert status(client, body)["status"] == "unknown"
    assert outgoing.claim(claim) == {"item": None}
    assert enqueue(client, body).json()["status"] == "unknown"


@pytest.mark.parametrize(
    "change",
    [
        {"listener_connected": False},
        {"secondary_login_confirmed": False},
        {"supports_message_send": False},
        {"enrollment_epoch": str(uuid4())},
        {"database_id": "1:999"},
    ],
)
def test_stale_login_or_changed_database_cannot_send(sending, change):
    _, client, _, body = sending
    with client.app.state.store.connect() as db:
        data = json.loads(db.execute("SELECT body FROM statuses WHERE kind='bridge'").fetchone()[0])
        db.execute("UPDATE statuses SET body=? WHERE kind='bridge'", (json.dumps(data | change),))
    assert enqueue(client, body).status_code in (409, 423)


def test_expiry_prevents_delayed_delivery(sending):
    collector, client, _, body = sending
    assert enqueue(client, body).status_code == 200
    with client.app.state.store.connect() as db:
        db.execute("UPDATE outgoing SET created_at=0")
    collector.send_pending(CONFIG)
    assert status(client, body)["status"] == "failed"
    assert status(client, body)["reason"] == "queue_expired"
    assert enqueue(client, body).json()["status"] == "failed"


def test_worker_passes_exact_unicode_text_and_checks_response_identity(sending, monkeypatch):
    collector, client, _, body = sending
    assert enqueue(client, body).status_code == 200
    calls = []

    def send(url, payload=None, token=None):
        calls.append(payload)
        assert url.endswith("/collector/send") and token == "a" * 43
        assert payload["text"] == body["text"]
        assert payload["chat_id"] == "9007199254740993"
        assert payload["enrollment_epoch"] == CONFIG["enrollment_epoch"]
        return {**payload, "status": "submitted", "build": iris.BUILD}

    monkeypatch.setattr(iris, "request", send)
    collector.send_pending(CONFIG)
    collector.send_pending(CONFIG)
    assert len(calls) == 1
    assert status(client, body)["status"] == "submitted"
    assert not status(client, body)["delivery_confirmed"]
    assert enqueue(client, body).json()["status"] == "submitted"


@pytest.mark.parametrize("outcome", ["timeout", "wrong_identity", "failed", "unknown", "lost_ack"])
def test_ambiguous_dispatch_and_ack_never_resend(sending, monkeypatch, outcome):
    collector, client, _, body = sending
    enqueue(client, body)
    calls = []

    def send(url, payload=None, token=None):
        calls.append(payload)
        if outcome == "timeout":
            raise TimeoutError("private body must not be echoed")
        return {
            **payload,
            "build": iris.BUILD,
            "request_id": "wrong" if outcome == "wrong_identity" else payload["request_id"],
            "status": outcome if outcome in {"failed", "unknown"} else "submitted",
        }

    monkeypatch.setattr(iris, "request", send)
    api = collector.api
    if outcome == "lost_ack":

        def lost_ack(path, payload=None):
            if path.endswith("/result"):
                raise OSError("lost response")
            return api(path, payload)

        collector.api = lost_ack
        with pytest.raises(OSError):
            collector.send_pending(CONFIG)
        collector.api = api
    else:
        collector.send_pending(CONFIG)
    collector.send_pending(CONFIG)
    assert len(calls) == 1
    assert status(client, body)["status"] == (
        "failed" if outcome == "failed" else "dispatching" if outcome == "lost_ack" else "unknown"
    )


def test_worker_rechecks_enrollment_after_claim(sending, monkeypatch):
    collector, client, _, body = sending
    enqueue(client, body)
    checks = iter([deepcopy(CONFIG), {**CONFIG, "secondary_login_version": 0}])
    monkeypatch.setattr(iris, "check_enrollment", lambda: next(checks))
    monkeypatch.setattr(iris, "request", lambda *a, **k: pytest.fail("must not send"))
    collector.send_pending(CONFIG)
    assert status(client, body)["status"] == "failed"


def test_restore_does_not_replay_pending_sends(sending, tmp_path, monkeypatch):
    _, client, _, body = sending
    enqueue(client, body)
    key = tmp_path / "key"
    key.write_text("a1" * 32)
    monkeypatch.setenv("BACKUP_KEY_FILE", str(key))
    backup(client.app.state.store.path, str(tmp_path / "backup.kcb"))
    restore(str(tmp_path / "backup.kcb"), str(tmp_path / "restored.db"))
    outgoing = Outgoing(Store(str(tmp_path / "restored.db")), client.app.state.outgoing.config)
    assert outgoing.status(body["request_id"])["status"] == "unknown"
    assert outgoing.enqueue(SendMessage(**body))["status"] == "unknown"


def test_rate_limit_and_stale_collector(sending):
    _, client, _, body = sending
    for _ in range(30):
        assert enqueue(client, body | {"request_id": str(uuid4())}).status_code == 200
    assert enqueue(client, body).status_code == 429
    with client.app.state.store.connect() as db:
        db.execute("UPDATE statuses SET received_at='2000-01-01T00:00:00+00:00'")
    assert enqueue(client, body).status_code == 423


def test_claim_rejects_old_identity_and_cancels_old_queue(sending):
    collector, client, _, body = sending
    enqueue(client, body)
    assert (
        client.post(
            "/internal/v1/outgoing/claim",
            headers=auth(READ),
            json={
                "enrollment_epoch": collector.epoch,
                "database_id": collector.database_id,
            },
        ).status_code
        == 401
    )
    wrong = client.post(
        "/internal/v1/outgoing/claim",
        headers=auth(INGEST),
        json={
            "enrollment_epoch": collector.epoch,
            "database_id": "other",
        },
    )
    assert wrong.status_code == 423
    with client.app.state.store.connect() as db:
        data = json.loads(db.execute("SELECT body FROM statuses WHERE kind='bridge'").fetchone()[0])
        db.execute(
            "UPDATE statuses SET body=? WHERE kind='bridge'",
            (json.dumps(data | {"database_id": "other"}),),
        )
    response = client.post(
        "/internal/v1/outgoing/claim",
        headers=auth(INGEST),
        json={
            "enrollment_epoch": collector.epoch,
            "database_id": "other",
        },
    )
    assert response.json() == {"item": None}
    assert status(client, body)["reason"] == "enrollment_changed"


def test_stdio_adapter_uses_send_credential_and_canonical_uuid(monkeypatch):
    from types import SimpleNamespace

    from server import mcp_adapter

    calls = []
    monkeypatch.setattr(
        mcp_adapter,
        "outgoing_client",
        lambda: SimpleNamespace(
            outgoing=lambda **kwargs: calls.append(kwargs) or {"status": "queued"}
        ),
    )
    assert mcp_adapter.send_message(
        "exact-ref", "한글\n👋", "A1234567-1234-1234-1234-123456789012"
    ) == {"status": "queued"}
    mcp_adapter.get_message_send_status("A1234567-1234-1234-1234-123456789012")
    assert calls == [
        {
            "body": {
                "request_id": "a1234567-1234-1234-1234-123456789012",
                "conversation_ref": "exact-ref",
                "text": "한글\n👋",
            }
        },
        {"request_id": "a1234567-1234-1234-1234-123456789012"},
    ]


def test_transport_authentication_and_sanitized_errors(monkeypatch):
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.error import HTTPError

    from dot_plugin import collector

    calls = []

    def upstream(request, timeout):
        calls.append(request)
        raise HTTPError(
            request.full_url, 409, "private", {}, BytesIO(b'{"error":"request_id_conflict"}')
        )

    monkeypatch.setattr(collector, "urlopen", upstream)
    source = collector.Collector(SimpleNamespace(api_url="http://synthetic", send_token=SEND))
    with pytest.raises(collector.QueryError, match="request_id_conflict"):
        source.outgoing(body={"text": "한글"})
    assert calls[0].headers["Authorization"] == "Bearer " + SEND
    assert calls[0].get_method() == "POST"
    assert json.loads(calls[0].data) == {"text": "한글"}
