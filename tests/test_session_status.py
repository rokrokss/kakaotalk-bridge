import json
import time
from unittest.mock import Mock

import pytest

from device import cli, enrollment, iris
from device.session_status import evidence, screen_evidence
from tests.test_enrollment import CONFIG, snap
from webui.device import Android


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


def test_login_screen_reports_whether_the_secondary_option_is_selected():
    assert screen_evidence(screen()) == {"state": "login_required", "secondary_option": "selected"}


@pytest.mark.parametrize(
    "xml",
    [
        screen(checked="false"),
        screen(option=False),
        screen(enabled="false"),
        screen().replace('checkable="true"', 'checkable="false"'),
        screen().replace(
            "</node></hierarchy>",
            screen().split("<hierarchy>")[1].split("</hierarchy>")[0] + "</node></hierarchy>",
        ),
    ],
)
def test_unchecked_missing_or_ambiguous_option_is_not_verified(xml):
    assert screen_evidence(xml)["secondary_option"] == "not_verified"


def test_ui_classification_never_echoes_inputs_or_infers_phone_from_chat():
    assert screen_evidence(screen(package="other.app"))["state"] == "not_visible"
    assert screen_evidence("malformed private-text")["state"] == "unknown"
    assert screen_evidence(screen().replace('text="로그인"', 'text="채팅"'))["state"] == "unknown"
    chat = '<hierarchy><node package="com.kakao.talk" text="친구 채팅 더보기 로그인 로그아웃 비밀번호"/></hierarchy>'
    assert screen_evidence(chat)["state"] == "unknown"
    tabs = '<hierarchy><node package="com.kakao.talk" class="android.widget.TabWidget">'
    tabs += "".join(
        f'<node package="com.kakao.talk" text="{t}" clickable="true"/>'
        for t in ["친구", "채팅", "더보기"]
    )
    tabs += "</node></hierarchy>"
    assert screen_evidence(tabs)["state"] == "main_screen_observed"


def test_evidence_is_scoped_dated_and_never_returns_account_ids():
    result = evidence(snap())
    assert result["collection_approval"] == "approved"
    assert result["kakao"] == {"login": "logged_in", "version": 29260820}
    assert result["phone"]["state"] == "operator_confirmed"
    assert result["phone"]["automatic"] is False
    assert "123" not in json.dumps(result)
    assert evidence(snap(account_ids=()))["kakao"]["login"] == "kakao_login_required"
    changed = evidence(snap(account_ids=(456,)))
    assert changed["collection_approval"] == "locked"
    assert changed["approval_reason"] == "account_changed"
    assert changed["phone"]["state"] == "unknown"
    assert evidence(None)["collection_approval"] == "unknown"
    stale = {**CONFIG, "phone_session_confirmed_at": time.time() - 86401}
    assert evidence(snap(stale))["phone"]["state"] == "recheck_due"
    for invalid in [True, float("nan"), float("inf"), time.time() + 60, "private-text"]:
        assert (
            evidence(snap({**CONFIG, "phone_session_confirmed_at": invalid}))["phone"]["state"]
            == "unknown"
        )
    lost = {**CONFIG, "phone_session_report": "lost", "phone_session_reported_at": time.time()}
    assert evidence(snap(lost))["phone"]["state"] == "reported_lost"


def test_device_inspection_cleans_private_xml_and_does_not_click_or_launch(monkeypatch):
    monkeypatch.setattr(cli, "sample", lambda: {"state": "android_ready", "kakao_installed": True})
    monkeypatch.setattr(enrollment, "current", lambda adb=None: snap())
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("shell", "cat"):
            return screen().replace(
                'class="android.widget.EditText"',
                'class="android.widget.EditText" text="private-password"',
            )
        return ""

    monkeypatch.setattr(cli, "adb", adb)
    result = Android().session_status()
    assert result["screen"]["state"] == "login_required"
    assert result["collection_approval"] == "approved"
    assert "private-password" not in json.dumps(result)
    assert calls[-1][:3] == ("shell", "rm", "-rf")
    assert any(c[:4] == ("shell", "mkdir", "-m", "700") for c in calls)
    assert all("input" not in c and "am" not in c for c in calls)


def test_phone_logout_revokes_before_stopping_iris(monkeypatch):
    operations = []
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(
        enrollment, "record_phone", lambda active: operations.append(("record", active))
    )
    monkeypatch.setattr(iris, "stop", lambda: operations.append("stop"))
    Android().record_phone(False)
    assert operations == [("record", False), "stop"]
    Android().record_phone(True)
    assert operations[-1] == ("record", True)


def test_disconnected_inspection_does_not_claim_phone_logout(monkeypatch):
    monkeypatch.setattr(cli, "sample", lambda: {"state": "offline"})
    result = Android().session_status()
    assert result["device"] == "offline" and result["phone"]["state"] == "unknown"
    assert result["collection_approval"] == "unknown"


def test_approval_from_the_admin_screen_does_not_leave_kakaotalk(monkeypatch):
    approve = Mock()
    monkeypatch.setattr(cli, "connect", lambda: None)
    monkeypatch.setattr(enrollment, "approve", approve)
    Android().approve(True)
    approve.assert_called_once_with(True)
