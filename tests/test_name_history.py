import json
from uuid import uuid4

import pytest

from device import iris
from server.models import Observation
from server.name_history import members
from server.queries import Queries
from tests import test_queries
from tests.test_api import INGEST, auth
from tests.test_iris import CONFIG, row
from tests.test_queries import add, get, metadata

api = test_queries.api


def feed(api, log, *, kind=2, user=201, name="Old Nick", config=None, **changes):
    person = {"userId": user, "nickName": name}
    body = (
        {"feedType": kind, "member": person}
        if kind == 2
        else {"feedType": kind, "members": [person]}
    )
    event = Observation.model_validate(
        iris.make_event(
            config or CONFIG,
            "1:100",
            row(
                log,
                chat_id="101",
                sender_id="999",
                message_type="0",
                message=json.dumps(body),
                **changes,
            ),
        )
    )
    store = api.app.state.store
    assert store.ingest(event) == "committed"
    return store.checkpoint()["cursor"], event


def missing(api, room="101", user="201", kind="OM", status="not_found"):
    payload = metadata(api, room=room, user=user)
    payload["items"][0].update(
        kind=kind, sender={"status": status, "reason": "profile_record_missing"}
    )
    assert (
        api.post("/internal/v1/iris/metadata", headers=auth(INGEST), json=payload).status_code
        == 200
    )
    return payload


def sender(api, message):
    return get(api, "/v2/context", message_id=message, before=0, after=0)["items"][0]["sender"]


def test_historical_name_latest_source_time_current_profile_precedence_and_refresh(api):
    message = add(api, 1)
    missing(api)
    feed(api, 2, name="Earliest", created_at=1791071000)
    proof, event = feed(api, 3, kind=4, name="Later", created_at=1791073000)
    feed(api, 4, name="Late import of older event", created_at=1791072000)
    got = sender(api, message)
    assert got["name"] == "Later" and got["name_status"] == "historical"
    assert got["name_observed_at"] == "2026-10-04T00:16:40Z"
    assert got["name_evidence_message_id"] == proof
    assert got["name_source"] == "open_chat_feed.join"
    assert got["name_reason"] == "historical_name_current_unverified"
    assert got["updated_at"] != got["name_observed_at"]
    store = api.app.state.store
    checkpoint = store.checkpoint()
    pending = store.messages()
    assert store.ingest(event) == "duplicate"
    missing(api, status="unavailable")
    assert sender(api, message)["name"] == "Later"
    with store.connect() as db:
        db.execute("UPDATE identities SET updated_at='2000-01-01T00:00:00Z'")
    assert any(
        x["user_id"] == "201"
        for x in Queries(store).metadata_targets(CONFIG["device_id"], iris.identity(CONFIG))
    )
    metadata(api, name="Current")
    current = sender(api, message)
    assert current["name"] == "Current" and current["name_status"] == "resolved"
    assert current["name_evidence_message_id"] is None and current["name_observed_at"] is None
    assert store.checkpoint() == checkpoint and store.messages() == pending


@pytest.mark.parametrize("kind", ["OM", "OD"])
def test_scoped_to_open_room_exact_sender_device_epoch_and_not_self(api, kind):
    target = add(api, 1)
    other_room = add(api, 2, room="202")
    other_user = add(api, 3, user="202")
    mine = add(api, 4, user="203", mine=True)
    unknown = add(api, 5, room="303")
    for room, user in [("101", "201"), ("202", "201"), ("101", "202"), ("101", "203")]:
        missing(api, room=room, user=user, kind=kind)
    feed(api, 6, config={**CONFIG, "device_id": "other-device"})
    feed(api, 7, config={**CONFIG, "enrollment_epoch": str(uuid4())})
    assert sender(api, target)["name"] is None
    feed(api, 8)
    feed(api, 9, user=203)
    assert sender(api, target)["name"] == "Old Nick"
    assert all(sender(api, m)["name"] is None for m in (other_room, other_user, mine, unknown))
    missing(api, kind="MultiChat")
    assert sender(api, target)["name"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"message_type": "1"},
        {"message_type": "26"},
        {"truncated": True},
        {"created_at": 0},
        {"created_at": 253402300800},
    ],
)
def test_only_complete_type_zero_with_known_event_time_is_evidence(api, changes):
    target = add(api, 1)
    missing(api)
    # Override defaults before constructing the transport row.
    person = {"feedType": 2, "member": {"userId": 201, "nickName": "Nope"}}
    data = (
        row(2, chat_id="101", sender_id="999", message_type="0", message=json.dumps(person))
        | changes
    )
    api.app.state.store.ingest(Observation.model_validate(iris.make_event(CONFIG, "1:100", data)))
    assert sender(api, target)["name"] is None


@pytest.mark.parametrize(
    "body",
    [
        "{",
        "[]",
        "null",
        '{"feedType":2,"feedType":4}',
        json.dumps({"feedType": 2, "member": {"userId": True, "nickName": "Wrong"}}),
        json.dumps({"feedType": 2, "member": {"userId": "201", "nickName": "Wrong"}}),
        json.dumps({"feedType": 2, "member": {"userId": 201.0, "nickName": "Wrong"}}),
        json.dumps({"feedType": 2, "member": {"userId": 2**63, "nickName": "Wrong"}}),
        json.dumps({"feedType": 2, "member": {"userId": 201, "nickName": " "}}),
        json.dumps({"feedType": 2, "member": {"userId": 201, "nickName": "x" * 513}}),
        json.dumps({"feedType": 2, "member": {"userId": 201, "nickName": "x\nFake"}}),
        json.dumps({"feedType": 2, "member": {"userId": 201, "nickName": "\ud800"}}),
        json.dumps({"feedType": 2.0, "member": {"userId": 201, "nickName": "Wrong"}}),
        json.dumps({"feedType": 25, "member": {"userId": 201, "nickName": "Wrong"}}),
        json.dumps({"feedType": 4, "members": [{"userId": 201, "nickName": "Wrong"}] * 101}),
        json.dumps(
            {
                "feedType": 4,
                "members": [{"userId": 201, "nickName": "A"}, {"userId": 201, "nickName": "B"}],
            }
        ),
        "[" * 1500 + "]" * 1500,
        " " * 16385,
    ],
)
def test_malformed_unsupported_or_ambiguous_names_are_ignored(body):
    assert members(body) == []


def test_join_parsing_preserves_large_integer_ids_and_deduplicates():
    person = {"userId": 9007199254740993, "nickName": " 이름 🙂 "}
    assert members(json.dumps({"feedType": 4, "members": [person, person]})) == [
        ("9007199254740993", "이름 🙂", "open_chat_feed.join")
    ]


def test_retention_deletes_name_evidence(api):
    target = add(api, 1)
    missing(api)
    old, _ = feed(api, 2, name="Old", created_at=1791071000)
    newer, _ = feed(api, 3, name="New", created_at=1791072000)
    store = api.app.state.store
    got = Queries(store).context(target, 0, 0)["items"][0]["sender"]
    assert got["name"] == "New" and got["name_evidence_message_id"] == newer
    with store.connect() as db:
        db.execute(
            "UPDATE observations SET received_at='2000-01-01' WHERE id=(SELECT observation_id FROM candidates WHERE id=?)",
            (newer,),
        )
        db.execute("UPDATE candidates SET received_at='2000-01-01' WHERE id=?", (newer,))
    store.prune(30)
    assert sender(api, target)["name_evidence_message_id"] == old
    with store.connect() as db:
        db.execute(
            "UPDATE observations SET received_at='2000-01-01' WHERE id=(SELECT observation_id FROM candidates WHERE id=?)",
            (old,),
        )
        db.execute("UPDATE candidates SET received_at='2000-01-01' WHERE id=?", (old,))
    store.prune(30)
    assert sender(api, target)["name"] is None
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM historical_sender_names").fetchone()[0] == 0


def test_name_search_status_and_cursors_consistently_use_history(api):
    add(api, 1, text="needle")
    add(api, 2, text="needle")
    missing(api)
    feed(api, 3)
    page = get(api, sender_name="Old Nick", q="needle", limit=1)
    assert page["has_more"] and page["items"][0]["sender"]["name_status"] == "historical"
    assert get(api, sender_name="Old Nick", q="needle", limit=1, cursor=page["next_cursor"])[
        "items"
    ]
    states = get(api, "/v1/status")["identity_metadata"]["states"]
    assert any(x["sender_status"] == "historical" and x["count"] == 1 for x in states)
    stable = get(api, limit=1)["next_cursor"]
    feed(api, 4, name="New Nick", created_at=1791072001)
    assert (
        api.get(
            "/v2/messages",
            headers=auth(),
            params={"sender_name": "Old Nick", "q": "needle", "cursor": page["next_cursor"]},
        ).status_code
        == 400
    )
    assert not get(api, sender_name="Old Nick")["items"]
    assert len(get(api, sender_name="New Nick")["items"]) == 2
    assert get(api, limit=1, cursor=stable)["items"]


def test_current_name_filtered_cursor_invalidated_only_on_display_change(api):
    add(api, 1)
    add(api, 2)
    metadata(api)
    page = get(api, sender_name="Alice", limit=1)
    metadata(api)
    assert get(api, sender_name="Alice", cursor=page["next_cursor"])["items"]
    metadata(api, name="Renamed")
    assert (
        api.get(
            "/v2/messages",
            headers=auth(),
            params={"sender_name": "Alice", "cursor": page["next_cursor"]},
        ).status_code
        == 400
    )


def test_conversation_name_cursor_invalidates_when_room_name_changes(api):
    add(api, 1)
    add(api, 2, room="202")
    metadata(api, title="Team A")
    metadata(api, room="202", title="Team B")
    page = get(api, "/v2/conversations", q="Team", limit=1)
    metadata(api, title="Renamed")
    assert (
        api.get(
            "/v2/conversations", headers=auth(), params={"q": "Team", "cursor": page["next_cursor"]}
        ).status_code
        == 400
    )


def test_equal_time_tie_is_deterministic_and_ingest_after_full_prune_still_indexes(api):
    target = add(api, 1)
    missing(api)
    feed(api, 2, name="First")
    proof, _ = feed(api, 3, name="Second")
    assert sender(api, target)["name_evidence_message_id"] == proof
    store = api.app.state.store
    with store.connect() as db:
        db.execute("UPDATE observations SET received_at='2000-01-01'")
        db.execute("UPDATE candidates SET received_at='2000-01-01'")
    store.prune(30)
    target = add(api, 4)
    missing(api)
    feed(api, 5, name="After prune")
    assert sender(api, target)["name"] == "After prune"
