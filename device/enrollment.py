"""Tablet enrollment and collection approval, bound to the KakaoTalk account on the tablet.

Approval records which KakaoTalk account the operator confirmed. It survives KakaoTalk
updates, and stops when a different account logs in, Android changes, or the phone is
reported as logged out. One ADB round trip reads everything the gate needs.
"""

import base64
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from device import cli

HOME = "/data/kakaotalk-bridge"
ENROLLMENT = HOME + "/enrollment.json"
ACCOUNT_STORE = "/data/data/com.kakao.talk/files/datastore/LocalUser_DataStore.pref.preferences_pb"
# KakaoTalk keeps the signed-in user's ID under these LocalUser DataStore keys.
ACCOUNT_KEYS = ("memochat_user_id", "old_user_id")
MARK = "@@kakaotalk-bridge@@"
SNAPSHOT = f"""
cat {ENROLLMENT} 2>/dev/null
echo; echo {MARK}
getprop ro.build.characteristics; getprop ro.build.fingerprint
echo {MARK}
wm size; wm density
echo {MARK}
pm list packages --show-versioncode com.kakao.talk
echo {MARK}
base64 -w 0 {ACCOUNT_STORE} 2>/dev/null
echo; echo {MARK}
"""


@dataclass(frozen=True)
class Snapshot:
    config: dict | None
    characteristics: str
    fingerprint: str
    width: int | None
    height: int | None
    dpi: int | None
    kakao_version: int | None
    account_ids: tuple[int, ...]


def _varint(data, pos):
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError("invalid_preferences")
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
        shift += 7


def _fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, kind = tag >> 3, tag & 7
        if kind == 0:
            value, pos = _varint(data, pos)
        elif kind == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise ValueError("invalid_preferences")
            value, pos = data[pos : pos + length], pos + length
        elif kind in (1, 5):
            size = 8 if kind == 1 else 4
            value, pos = data[pos : pos + size], pos + size
        else:
            raise ValueError("invalid_preferences")
        yield number, kind, value


def account_ids(preferences: bytes) -> tuple[int, ...]:
    """User IDs from a DataStore PreferenceMap; only the two account keys are decoded."""
    ids = []
    for number, kind, entry in _fields(preferences):
        if number != 1 or kind != 2:
            continue
        key = value = None
        for field, field_kind, content in _fields(entry):
            if field == 1 and field_kind == 2:
                key = content.decode()
            elif field == 2 and field_kind == 2:
                value = content
        if key not in ACCOUNT_KEYS or value is None:
            continue
        for field, field_kind, content in _fields(value):
            # Value.long is field 4; any other type is not an account ID.
            if field == 4 and field_kind == 0 and 0 < content < 2**63:
                ids.append(content)
    return tuple(ids)


def snapshot(adb=None) -> Snapshot:
    adb = adb or cli.adb
    parts = adb("shell", SNAPSHOT).split(MARK)
    if len(parts) < 6:
        raise RuntimeError("device_state_unavailable")
    stored = parts[0].strip()
    config = json.loads(stored) if stored else None
    props = parts[1].strip().splitlines() + ["", ""]
    sizes = re.findall(r"(\d+)x(\d+)", parts[2])
    densities = re.findall(r"density:\s*(\d+)", parts[2])
    version = re.search(r"versionCode:(\d+)", parts[3])
    store = parts[4].strip()
    return Snapshot(
        config=config,
        characteristics=props[0].strip(),
        fingerprint=props[1].strip(),
        width=int(sizes[-1][0]) if sizes else None,
        height=int(sizes[-1][1]) if sizes else None,
        dpi=int(densities[-1]) if densities else None,
        kakao_version=int(version[1]) if version else None,
        account_ids=account_ids(base64.b64decode(store)) if store else (),
    )


def device_problem(snap: Snapshot):
    if "tablet" not in snap.characteristics.split(","):
        return "not_tablet"
    if not (snap.width and snap.height and snap.dpi) or not snap.fingerprint:
        return "device_state_unavailable"
    # KakaoTalk only offers secondary-device login on tablet-sized displays.
    if min(snap.width, snap.height) * 160 / snap.dpi < 600:
        return "display_too_small"
    return None


def account(snap: Snapshot):
    """The signed-in user ID, or None with the reason it is unknown."""
    ids = set(snap.account_ids)
    if not ids:
        return None, "kakao_login_required"
    if len(ids) > 1:
        return None, "account_ambiguous"
    return str(ids.pop()), None


def approval(snap: Snapshot):
    config = snap.config or {}
    if not config.get("enrollment_epoch"):
        return "locked", "not_enrolled"
    problem = device_problem(snap)
    if problem:
        return "locked", problem
    if config.get("phone_session_report") == "lost":
        return "locked", "phone_reported_lost"
    if not config.get("approved_user_id"):
        return "locked", "approval_required"
    if config.get("device_fingerprint") != snap.fingerprint:
        return "locked", "android_changed"
    user, reason = account(snap)
    if user is None:
        return "locked", reason
    if user != config["approved_user_id"]:
        return "locked", "account_changed"
    return "approved", None


def write(config, adb=None):
    adb = adb or cli.adb
    staged = ENROLLMENT + ".next"
    # The file travels as a file, never as an ADB argument or logged shell command.
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "enrollment.json"
        local.write_text(json.dumps(config))
        local.chmod(0o600)
        adb("shell", f"mkdir -p {HOME} && chown 0:0 {HOME} && chmod 700 {HOME}")
        adb("push", str(local), staged)
    adb("shell", f"chown 0:0 {staged} && chmod 600 {staged} && mv {staged} {ENROLLMENT}")


def require_approved(adb=None) -> Snapshot:
    snap = snapshot(adb)
    state, reason = approval(snap)
    if state != "approved":
        raise RuntimeError(reason)
    if snap.config.get("device_id") != os.getenv("DEVICE_ID", "personal-tablet"):
        raise RuntimeError("device_identity_changed")
    return snap


def approve(phone_active, adb=None):
    """Record the operator's check that the phone stayed signed in after the tablet login."""
    if not phone_active:
        raise RuntimeError("phone_confirmation_required")
    snap = snapshot(adb)
    if not snap.config:
        raise RuntimeError("not_enrolled")
    problem = device_problem(snap)
    if problem:
        raise RuntimeError(problem)
    user, reason = account(snap)
    if user is None:
        raise RuntimeError(reason)
    now = time.time()
    write(
        {
            **snap.config,
            "approved_user_id": user,
            "approved_at": now,
            "device_fingerprint": snap.fingerprint,
            "phone_session_confirmed_at": now,
            "phone_session_report": "active",
            "phone_session_reported_at": now,
        },
        adb,
    )


def record_phone(active, adb=None):
    snap = snapshot(adb)
    config = dict(snap.config or {})
    now = time.time()
    if active:
        if approval(snap)[0] != "approved" or not config.get("phone_session_confirmed_at"):
            raise RuntimeError("secondary_confirmation_required")
        config["phone_session_confirmed_at"] = now
    else:
        config["approved_user_id"] = None
    config.update(
        phone_session_report="active" if active else "lost", phone_session_reported_at=now
    )
    write(config, adb)
