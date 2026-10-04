import json
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from device import cli, login_guard
from device.login_guard import confirm, device_signature, inspect_option, prelogin
from server.app import create_app
from server.config import Settings
from tests.test_api import DEVICE, INGEST, READ, auth, event, post


def screen(checked="true", option=True, package="com.kakao.talk", enabled="true"):
    checkbox = (
        f'<node package="{package}" text="다른 기기와 함께 사용" checkable="true" checked="{checked}" enabled="{enabled}"/>'
        if option
        else ""
    )
    return f'''<hierarchy><node package="{package}">
      <node package="{package}" class="android.widget.EditText"/>
      <node package="{package}" text="로그인" clickable="true"/>
      {checkbox}
    </node></hierarchy>'''


def test_selected_secondary_option_passes():
    inspect_option(screen())


@pytest.mark.parametrize(
    "xml",
    [
        screen(checked="false"),
        screen(option=False),
        screen(package="other.app"),
        screen(enabled="false"),
        screen().replace('checkable="true"', 'checkable="false"'),
        screen().replace('text="로그인"', 'text="채팅"'),
    ],
)
def test_missing_unchecked_or_ambiguous_options_block(xml):
    with pytest.raises(RuntimeError, match="BLOCKED"):
        inspect_option(xml)


def fake_adb(*args, **kwargs):
    return {
        ("shell", "getprop", "ro.build.characteristics"): "tablet",
        ("shell", "wm", "size"): "Physical size: 1200x1920",
        ("shell", "wm", "density"): "Physical density: 240",
        ("shell", "dumpsys", "package", "com.kakao.talk"): "versionCode=1234 minSdk=30",
        ("shell", "getprop", "ro.build.fingerprint"): "test-fingerprint",
        ("shell", "cat", "/data/local/tmp/kakaocollector-login-check.xml"): screen(),
    }.get(args, "")


def test_prelogin_only_inspects_and_cleans_up():
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        return fake_adb(*args, **kwargs)

    proof = prelogin(spy)
    assert proof["signature"]["kakao_version"] == 1234
    assert all("input" not in c and "am" not in c for c in calls)
    assert calls[-1][:3] == ("shell", "rm", "-f")


@pytest.mark.parametrize("approved", [True, False])
def test_rechecking_preserves_approval_and_proof_on_existing_login(monkeypatch, tmp_path, approved):
    signature = device_signature(fake_adb)
    config = {
        "collector_mode": "iris",
        "secondary_login_version": 1234 if approved else 0,
        "device_fingerprint": signature["fingerprint"],
        "enrollment_epoch": "test-epoch",
    }
    proof = tmp_path / "prelogin.json"
    proof.write_text("previous proof")
    monkeypatch.setattr(cli, "Path", lambda path: proof)
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(cli, "adb", lambda *args: json.dumps(config))
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: signature)
    inspect = Mock(side_effect=RuntimeError("BLOCKED: not a login screen"))
    save = Mock()
    monkeypatch.setattr(login_guard, "prelogin", inspect)
    monkeypatch.setattr(cli, "provision_file", save)
    if approved:
        assert cli.login_check() is False
        inspect.assert_not_called()
    else:
        with pytest.raises(RuntimeError, match="not a login screen"):
            cli.login_check()
    save.assert_not_called()
    assert proof.read_text() == "previous proof"


def test_successful_login_check_records_current_option_without_opening_apps(monkeypatch, tmp_path):
    signature = device_signature(fake_adb)
    config = {"enrollment_epoch": "test-epoch", "secondary_login_version": 0}
    proof = tmp_path / "prelogin.json"
    monkeypatch.setattr(cli, "Path", lambda path: proof)
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(cli, "adb", lambda *args: json.dumps(config))
    monkeypatch.setattr(login_guard, "device_signature", lambda adb: signature)
    monkeypatch.setattr(
        login_guard, "prelogin", lambda adb: {"checked_at": time.time(), "signature": signature}
    )
    save, launch = Mock(), Mock()
    monkeypatch.setattr(cli, "provision_file", save)
    monkeypatch.setattr(cli, "provision", launch)
    assert cli.login_check() is True
    assert json.loads(proof.read_text())["epoch"] == "test-epoch"
    assert proof.stat().st_mode & 0o777 == 0o600
    save.assert_called_once_with(config)
    launch.assert_not_called()


def test_confirmation_requires_both_sessions_and_current_prelogin_evidence():
    signature = device_signature(fake_adb)
    proof = {"checked_at": time.time(), "signature": signature}
    for phone, tablet in [(False, False), (False, True), (True, False)]:
        with pytest.raises(RuntimeError):
            confirm(proof, signature, phone, tablet)
    with pytest.raises(RuntimeError):
        confirm({**proof, "checked_at": time.time() - 1801}, signature, True, True)
    with pytest.raises(RuntimeError):
        confirm(proof, {**signature, "kakao_version": 1235}, True, True)
    assert confirm(proof, signature, True, True)["secondary_login_version"] == 1234


def test_api_denies_collection_until_explicit_confirmation(tmp_path):
    app = create_app(Settings(str(tmp_path / "locked.db"), INGEST, READ, DEVICE))
    with TestClient(app) as client:
        record = event()
        assert post(client, record).status_code == 423
        heartbeat = {
            "device_id": record["device_id"],
            "enrollment_epoch": record["enrollment_epoch"],
            "listener_connected": True,
            "outbox_depth": 0,
            "last_source_seq": 1,
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
