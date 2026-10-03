import time

import pytest
from fastapi.testclient import TestClient

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
