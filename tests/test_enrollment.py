import base64
import json
import time
from dataclasses import replace

import pytest

from device import enrollment
from device.enrollment import MARK, Snapshot


def varint(value):
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def entry(key, value):
    item = b"\x0a" + varint(len(key)) + key.encode() + b"\x12" + varint(len(value)) + value
    return b"\x0a" + varint(len(item)) + item


def long_value(number):
    return b"\x20" + varint(number)


def string_value(text):
    return b"\x2a" + varint(len(text)) + text.encode()


STORE = (
    entry("memochat_user_id", long_value(123))
    + entry("old_user_id", long_value(123))
    + entry("pch", string_value("opaque"))
    + entry("accountId", long_value(999))
)
CONFIG = {
    "device_id": "personal-tablet",
    "enrollment_epoch": "d0ca9a35-a86f-4f7f-b0b2-c2c1a0b1c36b",
    "approved_user_id": "123",
    "device_fingerprint": "build-1",
    "phone_session_confirmed_at": time.time() - 10,
    "phone_session_report": "active",
}


def snap(config=CONFIG, **changes):
    values = {
        "config": dict(config) if config is not None else None,
        "legacy": False,
        "characteristics": "tablet",
        "fingerprint": "build-1",
        "width": 1200,
        "height": 1920,
        "dpi": 240,
        "kakao_version": 29260820,
        "account_ids": (123, 123),
    }
    return Snapshot(**{**values, **changes})


def device_output(config=CONFIG, path=enrollment.ENROLLMENT, store=STORE, version="29260820"):
    stored = f"{path}\n{json.dumps(config)}" if config is not None else ""
    return MARK.join(
        [
            stored + "\n",
            "\ntablet\nbuild-1\n",
            "\nPhysical size: 1200x1920\nPhysical density: 240\n",
            f"\npackage:com.kakao.talk versionCode:{version}\n" if version else "\n",
            "\n" + (base64.b64encode(store).decode() if store else "") + "\n",
            "\n",
        ]
    )


def test_account_ids_read_only_the_two_long_id_keys():
    assert enrollment.account_ids(STORE) == (123, 123)
    assert enrollment.account_ids(entry("old_user_id", string_value("123"))) == ()
    assert enrollment.account_ids(b"") == ()
    with pytest.raises(ValueError):
        enrollment.account_ids(STORE[:-1])


def test_snapshot_reads_everything_in_one_adb_call():
    calls = []

    def adb(*args):
        calls.append(args)
        return device_output()

    state = enrollment.snapshot(adb)
    assert len(calls) == 1 and calls[0][0] == "shell"
    assert state.config == CONFIG and not state.legacy
    assert (state.width, state.height, state.dpi) == (1200, 1920, 240)
    assert state.kakao_version == 29260820 and state.account_ids == (123, 123)
    legacy = enrollment.snapshot(lambda *a: device_output(path=enrollment.LEGACY_ENROLLMENT))
    assert legacy.legacy
    missing = enrollment.snapshot(lambda *a: device_output(config=None, store=b"", version=""))
    assert missing.config is None and missing.account_ids == () and missing.kakao_version is None
    with pytest.raises(RuntimeError, match="device_state_unavailable"):
        enrollment.snapshot(lambda *a: "truncated")


def test_approval_follows_the_account_not_the_app_version():
    assert enrollment.approval(snap()) == ("approved", None)
    assert enrollment.approval(snap(kakao_version=29990000)) == ("approved", None)


@pytest.mark.parametrize(
    "state, reason",
    [
        (snap(account_ids=(456, 456)), "account_changed"),
        (snap(account_ids=()), "kakao_login_required"),
        (snap(account_ids=(123, 456)), "account_ambiguous"),
        (snap(fingerprint="build-2"), "android_changed"),
        (snap({**CONFIG, "phone_session_report": "lost"}), "phone_reported_lost"),
        (snap({**CONFIG, "approved_user_id": None}), "approval_required"),
        (snap(characteristics="phone"), "not_tablet"),
        (snap(width=600, height=800), "display_too_small"),
        (snap(None), "not_enrolled"),
    ],
)
def test_approval_locks_for_each_reason(state, reason):
    assert enrollment.approval(state) == ("locked", reason)


def test_previous_release_approval_carries_over_to_the_signed_in_account():
    legacy = {
        "device_id": "personal-tablet",
        "enrollment_epoch": CONFIG["enrollment_epoch"],
        "url": "https://172.29.87.3:8443",
        "token": "ingest-secret",
        "ca_pem": "pem",
        "collector_mode": "iris",
        "secondary_login_version": 29260820,
        "device_fingerprint": "build-1",
        "phone_session_confirmed_at": 1000.0,
        "tablet_session_confirmed_at": 900.0,
        "phone_session_report": "active",
    }
    config = enrollment.migrated(snap(legacy, legacy=True))
    assert config["approved_user_id"] == "123" and config["approved_at"] == 900.0
    assert not {"url", "token", "ca_pem", "collector_mode", "secondary_login_version"} & set(config)
    assert enrollment.approval(snap(config)) == ("approved", None)
    lost = enrollment.migrated(snap({**legacy, "secondary_login_version": 0}, legacy=True))
    assert "approved_user_id" not in lost


def test_legacy_enrollment_is_moved_out_of_the_keyboard_app(monkeypatch):
    states = [snap({"enrollment_epoch": "e", "secondary_login_version": 1}, legacy=True), snap()]
    writes = []
    monkeypatch.setattr(enrollment, "snapshot", lambda adb=None: states.pop(0))
    monkeypatch.setattr(enrollment, "write", lambda config, adb=None: writes.append(config))
    assert enrollment.current() == snap()
    assert writes == [
        {
            "enrollment_epoch": "e",
            "approved_user_id": "123",
            "approved_at": writes[0]["approved_at"],
        }
    ]


def test_write_keeps_contents_off_the_command_line():
    calls = []

    def adb(*args):
        calls.append(args)
        if args[0] == "push":
            source = enrollment.Path(args[1])
            assert source.stat().st_mode & 0o777 == 0o600
            assert json.loads(source.read_text()) == CONFIG
        return ""

    enrollment.write(CONFIG, adb)
    assert [c[0] for c in calls] == ["shell", "push", "shell"]
    assert calls[1][2] == enrollment.ENROLLMENT + ".next"
    # The legacy copy outlives an update rollback (see device.iris).
    assert enrollment.LEGACY_ENROLLMENT not in " ".join(" ".join(c) for c in calls)
    assert all("personal-tablet" not in " ".join(c) for c in calls)


def test_approve_requires_phone_check_and_a_signed_in_tablet(monkeypatch):
    writes = []
    monkeypatch.setattr(enrollment, "write", lambda config, adb=None: writes.append(config))
    unapproved = {k: v for k, v in CONFIG.items() if k != "approved_user_id"}
    monkeypatch.setattr(enrollment, "current", lambda adb=None: snap(unapproved, account_ids=()))
    with pytest.raises(RuntimeError, match="phone_confirmation_required"):
        enrollment.approve(False)
    with pytest.raises(RuntimeError, match="kakao_login_required"):
        enrollment.approve(True)
    assert writes == []
    monkeypatch.setattr(enrollment, "current", lambda adb=None: snap(unapproved))
    enrollment.approve(True)
    assert writes[0]["approved_user_id"] == "123"
    assert writes[0]["device_fingerprint"] == "build-1"
    assert writes[0]["phone_session_report"] == "active"


def test_phone_logout_revokes_and_recheck_needs_an_active_approval(monkeypatch):
    stored = {"config": dict(CONFIG)}
    monkeypatch.setattr(enrollment, "current", lambda adb=None: snap(stored["config"]))
    monkeypatch.setattr(enrollment, "write", lambda config, adb=None: stored.update(config=config))
    enrollment.record_phone(True)
    assert stored["config"]["phone_session_confirmed_at"] > CONFIG["phone_session_confirmed_at"]
    enrollment.record_phone(False)
    assert stored["config"]["approved_user_id"] is None
    assert stored["config"]["phone_session_report"] == "lost"
    with pytest.raises(RuntimeError, match="secondary_confirmation_required"):
        enrollment.record_phone(True)


def test_require_approved_checks_the_device_identity(monkeypatch):
    monkeypatch.setattr(enrollment, "current", lambda adb=None: snap())
    assert enrollment.require_approved().config == CONFIG
    monkeypatch.setattr(
        enrollment, "current", lambda adb=None: snap({**CONFIG, "device_id": "other"})
    )
    with pytest.raises(RuntimeError, match="device_identity_changed"):
        enrollment.require_approved()
    monkeypatch.setattr(enrollment, "current", lambda adb=None: replace(snap(), account_ids=(9,)))
    with pytest.raises(RuntimeError, match="account_changed"):
        enrollment.require_approved()
