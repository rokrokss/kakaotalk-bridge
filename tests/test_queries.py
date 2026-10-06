import jsonschema
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from device import iris
from dot_plugin.app import create_app as mcp_app
from dot_plugin.collector import QueryError
from dot_plugin.config import Config
from server.app import create_app
from server.config import Settings
from server.models import Observation
from server.queries import Queries
from server.store import Store
from tests.test_api import DEVICE, INGEST, READ, auth
from tests.test_dot_plugin import BASE, call, link, rpc
from tests.test_iris import CONFIG, row


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(str(tmp_path / "queries.db"), INGEST, READ, DEVICE))
    with TestClient(app) as client:
        yield client


def add(api, log, *, time=1791072000, room="101", user="201", mine=False, text="hello"):
    event = iris.make_event(
        CONFIG,
        "1:100",
        row(log, created_at=time, chat_id=room, sender_id=user, is_mine=mine, message=text),
    )
    api.app.state.store.ingest(Observation.model_validate(event))
    return api.app.state.store.checkpoint()["cursor"]


def metadata(api, room="101", user="201", name="Alice", title="Team"):
    epoch = iris.identity(CONFIG)
    headers = auth(INGEST)
    api.post(
        "/internal/v1/heartbeat",
        headers=headers,
        json={
            "device_id": CONFIG["device_id"],
            "enrollment_epoch": epoch,
            "source": "iris_db",
            "database_id": "1:100",
            "listener_connected": True,
            "secondary_login_confirmed": True,
            "last_source_seq": 10,
        },
    )
    label = lambda value: {"name": value, "status": "resolved", "name_source": "test_fixture"}
    payload = {
        "device_id": CONFIG["device_id"],
        "enrollment_epoch": epoch,
        "database_id": "1:100",
        "items": [
            {
                "chat_id": room,
                "user_id": user,
                "kind": "test_group",
                "sender": label(name),
                "conversation": label(title),
            }
        ],
    }
    result = api.post("/internal/v1/iris/metadata", headers=headers, json=payload)
    assert result.status_code == 200, result.text
    return payload


def get(api, path="/v2/messages", **params):
    result = api.get(path, params=params, headers=auth())
    assert result.status_code == 200, result.text
    return result.json()


def test_recent_is_sent_time_not_ingestion_and_filters_apply_before_limit(api):
    old = add(api, 1, time=1791072000, room="101")
    newest = add(api, 2, time=1791072600, room="101", mine=True, text="hello %")
    add(api, 3, time=1791072300, room="202", user="202")
    late = add(api, 4, time=1791072000, room="101")
    metadata(api)
    rows = get(api, limit=10)["items"]
    assert [x["message_id"] for x in rows] == [newest, 3, late, old]
    room = rows[0]["conversation"]["ref"]
    sender = rows[0]["sender"]["ref"]
    assert rows[0]["sender"]["name"] == "Alice" and rows[0]["conversation"]["name"] == "Team"
    assert rows[0]["sent_at"] == "2026-10-04T00:10:00Z"
    assert rows[0]["collected_at"] != rows[0]["sent_at"]
    assert len(get(api, sender_name="Alice")["items"]) == 3
    assert get(api, sender_name="Nonexistent")["items"] == []
    filtered = get(api, limit=3, conversation_ref=room)["items"]
    assert [x["message_id"] for x in filtered] == [newest, late, old]
    combined = get(
        api,
        q="%",
        conversation_ref=room,
        sender_ref=sender,
        since="2026-10-04T04:10:00+04:00",
        until="2026-10-04T04:11:00+04:00",
    )
    assert [x["message_id"] for x in combined["items"]] == [newest]
    assert not get(api, q="%", include_mine=False)["items"]
    assert not get(api, since="2026-10-04T00:00:00Z", until="2026-10-04T00:10:00Z", q="%")["items"]


def test_cursor_is_stable_bound_to_query_and_tamper_evident(api):
    for n in range(1, 7):
        add(api, n, time=1791072000 + n)
    first = get(api, limit=2)
    cursor = first["next_cursor"]
    add(api, 7, time=1791072010)
    add(api, 8, time=1791072003)  # Delayed history is excluded from this snapshot too.
    second = get(api, limit=2, cursor=cursor)
    third = get(api, limit=2, cursor=second["next_cursor"])
    assert [x["message_id"] for p in [first, second, third] for x in p["items"]] == [
        6,
        5,
        4,
        3,
        2,
        1,
    ]
    assert not third["has_more"] and third["next_cursor"] is None
    for bad in (cursor + "x", "garbage"):
        assert api.get("/v2/messages", params={"cursor": bad}, headers=auth()).status_code == 400
    assert (
        api.get(
            "/v2/messages", params={"cursor": cursor, "q": "changed"}, headers=auth()
        ).status_code
        == 400
    )
    with api.app.state.store.connect() as db:
        db.execute("UPDATE metadata SET value='reset' WHERE key='cursor_epoch'")
    assert api.get("/v2/messages", params={"cursor": cursor}, headers=auth()).status_code == 400


def test_rooms_are_unique_and_context_stays_in_room(api):
    a = add(api, 1, time=1791072000)
    b = add(api, 2, time=1791072300)
    add(api, 3, time=1791072301, room="202")
    c = add(api, 4, time=1791072400)
    metadata(api)
    metadata(api, room="202", title="Other")
    rooms = get(api, "/v2/conversations", limit=1)
    assert rooms["items"][0]["name"] == "Team" and rooms["items"][0]["message_count"] == 3
    other = get(api, "/v2/conversations", limit=1, cursor=rooms["next_cursor"])
    assert other["items"][0]["name"] == "Other" and not other["has_more"]
    assert len(get(api, "/v2/conversations", q="Team")["items"]) == 1
    context = get(api, "/v2/context", message_id=b, before=1, after=1)
    assert [x["message_id"] for x in context["items"]] == [a, b, c]
    assert not context["has_more_before"] and not context["has_more_after"]
    assert api.get("/v2/context", params={"message_id": 999}, headers=auth()).status_code == 400


def test_name_scope_updates_without_reingesting_and_metadata_auth(api):
    add(api, 1)
    add(api, 2, room="202")
    before = get(api)["items"]
    assert all(x["sender"]["name_status"] == "pending" for x in before)
    body = metadata(api, name="Name in room A")
    metadata(api, room="202", name="Name in room B", title="Other")
    rows = get(api)["items"]
    assert [x["sender"]["name"] for x in rows] == ["Name in room B", "Name in room A"]
    count = api.app.state.store.checkpoint()["cursor"]
    metadata(api, name="Updated name")
    assert api.app.state.store.checkpoint()["cursor"] == count
    assert get(api)["items"][1]["sender"]["name"] == "Updated name"
    assert api.post("/internal/v1/iris/metadata", headers=auth(READ), json=body).status_code == 401
    body["items"][0]["user_id"] = "999"
    assert (
        api.post("/internal/v1/iris/metadata", headers=auth(INGEST), json=body).status_code == 409
    )
    body["database_id"] = "wrong"
    assert (
        api.post("/internal/v1/iris/metadata", headers=auth(INGEST), json=body).status_code == 423
    )
    assert get(api, "/v1/status")["identity_metadata"]["states"][0]["sender_status"] == "resolved"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"since": "2026-10-04T00:00:00"},
        {"since": "bad"},
        {"since": "2026-10-05T00:00:00Z", "until": "2026-10-04T00:00:00Z"},
    ],
)
def test_query_rejects_bad_bounds_and_ambiguous_timezone(api, params):
    assert api.get("/v2/messages", params=params, headers=auth()).status_code in (400, 422)
    assert api.get("/v2/messages", params={}, headers=auth(INGEST)).status_code == 401


def test_additive_index_backfill_and_unknown_timestamp(api):
    add(api, 1, time=0)
    with api.app.state.store.connect() as db:
        db.execute("DELETE FROM message_lookup")
    restarted = Store(api.app.state.store.path)
    item = Queries(restarted).messages()["items"][0]
    assert item["sent_at"] is None and item["collected_at"]
    assert not Queries(restarted).messages(since="2026-01-01T00:00:00Z")["items"]


def test_metadata_refresh_resolves_existing_messages_without_advancing_event_cursor(
    api, monkeypatch
):
    add(api, 1)
    metadata(api)
    with api.app.state.store.connect() as db:
        db.execute("DELETE FROM identities")
        db.execute("DELETE FROM rooms")
    collector = iris.Collector(
        lambda path, payload=None: (
            api.post(path, json=payload, headers=auth(INGEST))
            if payload is not None
            else api.get(path, headers=auth(INGEST))
        ).json()
    )
    collector.epoch = iris.identity(CONFIG)
    collector.database_id = "1:100"
    collector.iris_token = "a" * 43

    def fake(url, payload, token):
        assert token == collector.iris_token
        assert url == "http://127.0.0.1:3000/collector/metadata"
        assert len(payload["targets"]) == 1
        return {
            "build": iris.BUILD,
            "enrollment_epoch": CONFIG["enrollment_epoch"],
            "database_id": "1:100",
            "items": [
                {
                    "chat_id": "101",
                    "user_id": "201",
                    "kind": "OM",
                    "sender": {
                        "name": "Scoped Nick",
                        "status": "resolved",
                        "name_source": "open_chat_member",
                    },
                    "conversation": {
                        "name": "Open room",
                        "status": "resolved",
                        "name_source": "open_link",
                    },
                }
            ],
        }

    monkeypatch.setattr(iris, "request", fake)
    cursor = api.app.state.store.checkpoint()["cursor"]
    collector.refresh_metadata(CONFIG, collector.iris_token)
    assert get(api)["items"][0]["sender"]["name"] == "Scoped Nick"
    assert api.app.state.store.checkpoint()["cursor"] == cursor


@pytest.mark.parametrize("historical", [False, True])
def test_real_api_to_mcp_results_match_published_schemas(api, tmp_path, historical):
    add(api, 1)
    add(api, 2, text="needle")
    metadata(api)
    if historical:
        from tests.test_name_history import feed, missing

        missing(api)
        feed(api, 3)

    class Source:
        def get(self, path, **params):
            response = api.get(
                path, params={k: v for k, v in params.items() if v is not None}, headers=auth()
            )
            if response.status_code == 400:
                raise QueryError()
            response.raise_for_status()
            return response.json()

    config = Config(
        BASE, str(tmp_path / "dot.db"), "L" * 43, Fernet.generate_key(), approval_mode="key"
    )
    with TestClient(mcp_app(config, Source(), worker=False), base_url=BASE) as client:
        _, form = link(client)
        tokens = client.post("/token", data=form).json()
        client.headers["Authorization"] = "Bearer " + tokens["access_token"]
        definitions = {x["name"]: x for x in rpc(client, "tools/list")["result"]["tools"]}
        for name, args in [
            (
                "get_recent_messages",
                {"limit": 1, "sender_name": "Old Nick"} if historical else {"limit": 1},
            ),
            ("search_messages", {"q": "needle"}),
            ("list_conversations", {}),
            ("get_conversation_context", {"message_id": 2}),
        ]:
            result = call(client, name, **args)["result"]
            assert not result["isError"]
            jsonschema.validate(result["structuredContent"], definitions[name]["outputSchema"])
            if historical and name != "list_conversations":
                named = [
                    x for x in result["structuredContent"]["items"] if x["message_id"] in (1, 2)
                ]
                assert named and all(x["sender"]["name_status"] == "historical" for x in named)
        error = call(client, "get_recent_messages", cursor="invalid")["error"]
        assert error["message"] == "invalid_query_or_expired_cursor"


def test_collector_http400_is_actionable_and_does_not_echo_request(monkeypatch):
    import io
    from unittest.mock import Mock
    from urllib.error import HTTPError

    from dot_plugin.collector import Collector

    error = HTTPError(
        "http://api/v2/messages?q=private",
        400,
        "invalid",
        {},
        io.BytesIO(b'{"detail":"invalid_time_range"}'),
    )
    monkeypatch.setattr("dot_plugin.collector.urlopen", Mock(side_effect=error))
    collector = Collector(Mock(api_url="http://api", read_token="synthetic"))
    with pytest.raises(QueryError, match="invalid_query_or_expired_cursor"):
        collector.get("/v2/messages", q="private", cursor=None, include_mine=False)


def test_query_cursor_invalidates_on_retention_and_metadata_is_pruned(api):
    add(api, 1)
    add(api, 2)
    metadata(api)
    cursor = get(api, limit=1)["next_cursor"]
    with api.app.state.store.connect() as db:
        db.execute("UPDATE candidates SET received_at='2000-01-01T00:00:00Z'")
        db.execute("UPDATE observations SET received_at='2000-01-01T00:00:00Z'")
    api.app.state.store.prune(30)
    assert api.get("/v2/messages", params={"cursor": cursor}, headers=auth()).status_code == 400
    with api.app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM message_lookup").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM identities").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0
