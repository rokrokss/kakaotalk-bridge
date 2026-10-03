import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from device import cli, iris, login_guard
from device.session_status import enrollment_evidence, screen_evidence
from tests.test_login_guard import screen
from webui.device import Android

SIGNATURE = {"kakao_version": 1234, "fingerprint": "test"}


def config():
    return {
        "collector_mode": "iris",
        "secondary_login_version": 1234,
        "device_fingerprint": "test",
        "enrollment_epoch": "epoch",
        "phone_session_confirmed_at": time.time() - 10,
        "tablet_session_confirmed_at": time.time() - 20,
        "token": "must-never-return",
        "ca_pem": "private-config",
    }


def test_ui_classification_never_echoes_inputs_or_infers_phone_from_chat():
    evidence = screen_evidence(screen())
    assert evidence == {"state": "login_required", "secondary_option": "selected"}
    assert screen_evidence(screen(checked="false"))["secondary_option"] == "not_verified"
    assert screen_evidence(screen(package="other.app"))["state"] == "not_visible"
    assert screen_evidence("malformed private-text")["state"] == "unknown"
    chat = '<hierarchy><node package="com.kakao.talk" text="친구 채팅 더보기 로그인 로그아웃 비밀번호"/></hierarchy>'
    assert screen_evidence(chat)["state"] == "unknown"
    tabs = '<hierarchy><node package="com.kakao.talk" class="android.widget.TabWidget">'
    tabs += "".join(
        f'<node package="com.kakao.talk" text="{t}" clickable="true"/>'
        for t in ["친구", "채팅", "더보기"]
    )
    tabs += "</node></hierarchy>"
    assert screen_evidence(tabs)["state"] == "main_screen_observed"


def test_phone_evidence_is_scoped_dated_and_never_automatically_confirmed():
    current = config()
    result = enrollment_evidence(current, {}, SIGNATURE)
    assert result["collection_approval"] == "approved"
    assert result["phone"]["state"] == "operator_confirmed"
    assert result["phone"]["automatic"] is False
    assert "must-never-return" not in json.dumps(result)
    assert (
        enrollment_evidence(current, {}, {**SIGNATURE, "kakao_version": 999})["phone"]["state"]
        == "unknown"
    )
    assert enrollment_evidence(current, {}, None)["collection_approval"] == "unknown"
    current["phone_session_confirmed_at"] = time.time() - 86401
    assert enrollment_evidence(current, {}, SIGNATURE)["phone"]["state"] == "recheck_due"
    for invalid in [True, float("nan"), float("inf"), time.time() + 60, "private-text"]:
        current["phone_session_confirmed_at"] = invalid
        assert enrollment_evidence(current, {}, SIGNATURE)["phone"]["state"] == "unknown"
    current.update(
        secondary_login_version=0,
        phone_session_report="lost",
        phone_session_reported_at=time.time(),
    )
    assert enrollment_evidence(current, {}, SIGNATURE)["phone"]["state"] == "reported_lost"


def test_precheck_expiry_and_epoch_change_are_visible():
    current = config()
    proof = {"epoch": "epoch", "signature": SIGNATURE, "checked_at": time.time()}
    assert enrollment_evidence(current, proof, SIGNATURE)["precheck"]["state"] == "valid"
    for changed in [{**proof, "epoch": "old"}, {**proof, "checked_at": time.time() - 1801}]:
        assert enrollment_evidence(current, changed, SIGNATURE)["precheck"]["state"] == "expired"


def test_device_inspection_cleans_private_xml_and_does_not_click_or_launch(monkeypatch):
    monkeypatch.setattr(cli, "sample", lambda: {"state": "android_ready", "kakao_installed": True})
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: SIGNATURE)
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        if args == ("shell", "cat", cli.REMOTE_CONFIG):
            return json.dumps(config())
        if args[:2] == ("shell", "cat"):
            return screen().replace(
                'class="android.widget.EditText"',
                'class="android.widget.EditText" text="private-password"',
            )
        return ""

    monkeypatch.setattr(cli, "adb", adb)
    result = Android().session_status()
    assert result["screen"]["state"] == "login_required"
    assert "private-password" not in json.dumps(result)
    assert "must-never-return" not in json.dumps(result)
    assert calls[-1][:3] == ("shell", "rm", "-rf")
    assert any(c[:4] == ("shell", "mkdir", "-m", "700") for c in calls)
    assert all("input" not in c and "am" not in c for c in calls)


def test_phone_logout_revokes_gate_before_stopping_and_cannot_be_reenabled_by_recheck(monkeypatch):
    current = config()
    operations = []
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(cli, "adb", lambda *a, **k: json.dumps(current))
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: SIGNATURE)
    monkeypatch.setattr("webui.device.Path.unlink", lambda *a, **k: None)

    def provision(value):
        operations.append("revoke")
        current.update(deepcopy(value))

    monkeypatch.setattr(cli, "provision_file", provision)
    monkeypatch.setattr(iris, "stop", lambda: operations.append("stop"))
    Android().record_phone(False)
    assert operations == ["revoke", "stop"]
    assert current["secondary_login_version"] == 0
    assert current["phone_session_report"] == "lost"
    with pytest.raises(RuntimeError, match="secondary_confirmation_required"):
        Android().record_phone(True)
    assert operations == ["revoke", "stop"]


def test_phone_recheck_persists_time_without_changing_tablet_confirmation(monkeypatch):
    current = config()
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(cli, "adb", lambda *a, **k: json.dumps(current))
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: SIGNATURE)
    save = Mock()
    monkeypatch.setattr(cli, "provision_file", save)
    Android().record_phone(True)
    stored = save.call_args.args[0]
    assert stored["phone_session_confirmed_at"] > current["phone_session_confirmed_at"]
    assert stored["tablet_session_confirmed_at"] == current["tablet_session_confirmed_at"]
    assert stored["secondary_login_version"] == 1234


def test_disconnected_inspection_does_not_claim_phone_logout(monkeypatch):
    monkeypatch.setattr(cli, "sample", lambda: {"state": "offline"})
    result = Android().session_status()
    assert result["device"] == "offline" and result["phone"]["state"] == "unknown"
    assert result["collection_approval"] == "unknown"


def test_iris_confirmation_records_both_sessions_without_leaving_kakao(monkeypatch, tmp_path):
    current = config()
    current["secondary_login_version"] = 0
    proof = tmp_path / "prelogin.json"
    proof.write_text(
        json.dumps({"epoch": "epoch", "signature": SIGNATURE, "checked_at": time.time()})
    )
    monkeypatch.setattr(cli, "Path", lambda path: proof)
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: SIGNATURE)
    calls = []

    def adb(*args):
        calls.append(args)
        return json.dumps(current)

    monkeypatch.setattr(cli, "adb", adb)
    save, launch = Mock(), Mock()
    monkeypatch.setattr(cli, "provision_file", save)
    monkeypatch.setattr(cli, "provision", launch)
    cli.confirm_secondary(phone_active=True, tablet_active=True)
    stored = save.call_args.args[0]
    assert stored["secondary_login_version"] == 1234
    assert stored["phone_session_report"] == "active"
    assert stored["phone_session_confirmed_at"] > 0
    assert stored["tablet_session_confirmed_at"] > 0
    assert not proof.exists()
    launch.assert_not_called()
    assert calls == [("shell", "cat", cli.REMOTE_CONFIG)]
