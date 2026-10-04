"""Bounded nickname evidence from retained KakaoTalk system events, never ordinary text."""

import json


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def members(body):
    if len(body) > 16384:
        return []
    try:
        feed = json.loads(body, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        return []
    if not isinstance(feed, dict) or type(feed.get("feedType")) is not int:
        return []
    kind = feed["feedType"]
    if kind == 2:
        items, source = [feed.get("member")], "open_chat_feed.leave"
    elif kind == 4:
        items, source = feed.get("members"), "open_chat_feed.join"
    else:
        return []
    if not isinstance(items, list) or len(items) > 100:
        return []
    found, ambiguous = {}, set()
    for item in items:
        if not isinstance(item, dict):
            continue
        user, name = item.get("userId"), item.get("nickName")
        if type(user) is not int or not 0 < user <= 9223372036854775807:
            continue
        if not isinstance(name, str) or not name.strip() or len(name) > 512:
            continue
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in name):
            continue
        name = name.strip()
        if user in found and found[user] != name:
            ambiguous.add(user)
        found[user] = name
    return [(str(user), name, source) for user, name in found.items() if user not in ambiguous]


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS historical_sender_names (
      message_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
      conversation_ref TEXT NOT NULL, sender_ref TEXT NOT NULL,
      name TEXT NOT NULL, name_source TEXT NOT NULL, observed_ms INTEGER NOT NULL,
      PRIMARY KEY(message_id,sender_ref)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS history_sender_latest ON historical_sender_names
      (conversation_ref,sender_ref,observed_ms DESC,message_id DESC)""")
    index_new(db)


def changed(db):
    db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='identity_revision'")


def index_new(db, observation_id=None):
    """Backfill once, then index new rows inside the ingestion transaction."""
    after = db.execute("SELECT value FROM metadata WHERE key='name_history_index_v1'").fetchone()
    high = db.execute("SELECT COALESCE(MAX(message_id),0) FROM message_lookup").fetchone()[0]
    floor = int(after[0]) if after and int(after[0]) <= high else 0
    selection = (
        "m.message_id>? AND m.message_id<=?" if observation_id is None else "c.observation_id=?"
    )
    rows = db.execute(
        f"""SELECT m.*,c.body FROM message_lookup m JOIN candidates c ON c.id=m.message_id
        WHERE {selection} AND m.source='iris_db'
          AND m.message_type='0' AND c.truncated=0
          AND m.sent_ms BETWEEN 1 AND 253402300799999 ORDER BY m.message_id""",
        (floor, high) if observation_id is None else (observation_id,),
    )
    inserted = False
    for row in rows:
        for user, name, source in members(row["body"]):
            db.execute(
                "INSERT OR IGNORE INTO historical_sender_names VALUES(?,?,?,?,?,?)",
                (
                    row["message_id"],
                    row["conversation_ref"],
                    f"{row['device_id']}:{row['epoch']}:{user}",
                    name,
                    source,
                    row["sent_ms"],
                ),
            )
            inserted = True
    db.execute(
        "INSERT INTO metadata VALUES('name_history_index_v1',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(high),),
    )
    if inserted:
        changed(db)


# Historical evidence never changes current-profile metadata or its refresh schedule.
JOINS = """
  LEFT JOIN identities s ON s.conversation_ref=m.conversation_ref AND s.sender_ref=m.sender_ref
  LEFT JOIN rooms r ON r.conversation_ref=m.conversation_ref
  LEFT JOIN historical_sender_names h ON h.sender_ref=m.sender_ref AND h.message_id=(
    SELECT n.message_id FROM historical_sender_names n
    WHERE n.conversation_ref=m.conversation_ref AND n.sender_ref=m.sender_ref
      AND r.kind IN ('OM','OD') AND m.is_mine=0 AND COALESCE(s.status,'pending')!='resolved'
    ORDER BY n.observed_ms DESC,n.message_id DESC LIMIT 1)
"""
NAME = "CASE WHEN s.status='resolved' THEN s.name ELSE h.name END"
STATUS = "CASE WHEN h.name IS NOT NULL THEN 'historical' ELSE COALESCE(s.status,'pending') END"
