import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from device import cli, enrollment, iris, setup
from tests.test_enrollment import snap


def test_prepare_does_not_mutate_existing_tablet(monkeypatch):
    monkeypatch.setattr(setup, "status", lambda: {"state": "android_ready", "enrolled": True})
    adb = Mock()
    monkeypatch.setattr(cli, "adb", adb)
    assert setup.prepare() is False
    adb.assert_not_called()


def test_prepare_refuses_incomplete_android(monkeypatch):
    monkeypatch.setattr(setup, "status", lambda: {"state": "booting"})
    adb = Mock()
    monkeypatch.setattr(cli, "adb", adb)
    with pytest.raises(RuntimeError, match="android_not_ready"):
        setup.prepare()
    adb.assert_not_called()


def test_locale_restart_waits_for_a_new_boot_before_opening_store(monkeypatch):
    monkeypatch.setattr(
        setup,
        "status",
        lambda: {"state": "needs_setup", "locale": "en-US", "aurora_installed": True},
    )
    adb = Mock(
        side_effect=lambda *a, **k: (
            "package:android" if a[1:4] == ("pm", "list", "packages") else "0"
        )
    )
    monkeypatch.setattr(cli, "adb", adb)
    sample = Mock(side_effect=[{"state": "booting"}, {"state": "needs_setup"}])
    monkeypatch.setattr(cli, "sample", sample)
    monkeypatch.setattr(setup.time, "sleep", Mock())
    opened = Mock()
    monkeypatch.setattr(setup, "open_store", opened)
    assert setup.prepare() is True
    calls = [call.args for call in adb.call_args_list]
    assert calls.index(("shell", "setprop", "sys.boot_completed", "0")) < calls.index(
        ("shell", "stop")
    )
    assert sample.call_count == 2
    opened.assert_called_once()


def test_wrong_aurora_artifact_is_never_installed(monkeypatch, tmp_path):
    import io

    monkeypatch.setattr(setup, "status", lambda: {"state": "needs_setup", "locale": "ko-KR"})
    monkeypatch.setattr(setup, "Path", lambda path: tmp_path / path.removeprefix("/"))
    adb = Mock(return_value="0")
    monkeypatch.setattr(cli, "adb", adb)
    monkeypatch.setattr(setup, "urlopen", lambda *a, **k: io.BytesIO(b"untrusted APK"))
    # Use the original Path for the private download folder while redirecting the state check.
    monkeypatch.setattr(
        setup,
        "Path",
        lambda path: tmp_path / "state.json" if path == "/state/enrollment.json" else Path(path),
    )
    with pytest.raises(RuntimeError, match="aurora_artifact_unverified"):
        setup.prepare()
    assert all("install" not in call.args for call in adb.call_args_list)


@pytest.mark.parametrize(
    ("prefs", "listing"),
    [
        ("", False),
        ('<map>\n    <boolean name="PREFERENCE_INTRO" value="true" />\n</map>', False),
        ('<map>\n    <boolean name="ACCOUNT_SIGNED_IN" value="true" />\n</map>', True),
    ],
)
def test_store_opens_kakaotalk_listing_only_after_aurora_login(monkeypatch, prefs, listing):
    monkeypatch.setattr(cli, "connect", Mock())

    def adb(*args, **kwargs):
        if "resolve-activity" in args:
            return "priority=0\ncom.aurora.store/.ComposeActivity"
        return prefs if args[:2] == ("shell", "cat") else ""

    adb = Mock(side_effect=adb)
    monkeypatch.setattr(cli, "adb", adb)
    assert setup.open_store() is listing
    calls = [call.args for call in adb.call_args_list]
    grant = ("shell", "appops", "set", "com.aurora.store", "REQUEST_INSTALL_PACKAGES", "allow")
    start = calls[-1]
    assert calls.index(grant) < calls.index(start)
    assert start[:3] == ("shell", "am", "start")
    assert start[-2:] == ("-n", "com.aurora.store/.ComposeActivity")
    assert ("com.kakao.talk" in start) is listing


@pytest.mark.parametrize(
    ("sample", "prefs", "expected"),
    [
        ({"kakao_installed": False}, "", False),
        ({"kakao_installed": False}, '<boolean name="ACCOUNT_SIGNED_IN" value="true" />', True),
        ({"kakao_installed": True}, '<boolean name="ACCOUNT_SIGNED_IN" value="true" />', None),
    ],
)
def test_status_reports_aurora_login_only_while_kakaotalk_is_missing(
    monkeypatch, sample, prefs, expected
):
    monkeypatch.setattr(cli, "sample", lambda: {"state": "needs_setup", **sample})
    monkeypatch.setattr(cli, "is_installed", lambda package: True)
    monkeypatch.setattr(setup, "enrolled", lambda: False)
    monkeypatch.setattr(
        cli, "adb", lambda *args, **kwargs: prefs if args[:2] == ("shell", "cat") else "ko-KR"
    )
    assert setup.status().get("aurora_signed_in") is expected


def test_preserve_bootstrap_keeps_identity_and_approval(monkeypatch, tmp_path):
    identity = {"device_id": "personal-tablet", "enrollment_epoch": "e"}
    host = tmp_path / "enrollment.json"
    host.write_text(json.dumps(identity))
    original_path = Path
    monkeypatch.setattr(
        cli, "Path", lambda p: host if p == "/state/enrollment.json" else original_path(p)
    )
    monkeypatch.setattr(cli, "sample", lambda: {"state": "android_ready"})
    monkeypatch.setattr(cli, "connect", Mock())
    monkeypatch.setattr(
        enrollment, "snapshot", lambda adb=None: snap({**identity, "approved_user_id": "123"})
    )
    write = Mock()
    monkeypatch.setattr(enrollment, "write", write)
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        return "0" if args == ("shell", "id", "-u") else ""

    monkeypatch.setattr(cli, "adb", adb)
    assert cli.bootstrap(preserve=True) is False
    assert json.loads(host.read_text()) == identity
    write.assert_not_called()
    assert all(call[0] not in ("install", "install-multiple", "push") for call in calls)


def test_new_enrollment_starts_locked_without_secrets_on_the_device(monkeypatch, tmp_path):
    host = tmp_path / "enrollment.json"
    original_path = Path
    monkeypatch.setattr(
        cli, "Path", lambda p: host if p == "/state/enrollment.json" else original_path(p)
    )
    monkeypatch.setattr(cli, "sample", lambda: {"state": "android_ready"})
    monkeypatch.setattr(cli, "connect", Mock())
    monkeypatch.setattr(cli, "is_installed", lambda package: True)
    monkeypatch.setattr(enrollment, "snapshot", lambda adb=None: snap(None))
    monkeypatch.setattr(iris, "stop", Mock())
    write = Mock()
    monkeypatch.setattr(enrollment, "write", write)
    monkeypatch.setattr(
        cli, "adb", lambda *args, **kwargs: "0" if args == ("shell", "id", "-u") else ""
    )
    assert cli.bootstrap() is True
    written = write.call_args.args[0]
    assert set(written) == {"device_id", "enrollment_epoch"}
    assert written == json.loads(host.read_text())


def test_publisher_signature_is_required(monkeypatch):
    result = Mock(returncode=0, stdout="Signer #1 certificate SHA-256 digest: " + "0" * 64)
    monkeypatch.setattr(setup.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match="kakao_signature_unverified"):
        setup.verify_kakao(["/tmp/test.apk"])
    result.stdout = "Signer #1 certificate SHA-256 digest: " + setup.KAKAO_SIGNER
    setup.verify_kakao(["/tmp/test.apk"])


def test_installed_apk_verification_accepts_android_randomized_paths(monkeypatch):
    remote = "/data/app/~~random==/com.kakao.talk-identifier==/base.apk"
    adb = Mock(return_value="package:" + remote)
    monkeypatch.setattr(cli, "adb", adb)
    verify = Mock()
    monkeypatch.setattr(setup, "verify_kakao", verify)
    setup.verify_installed_kakao()
    assert adb.call_args.args[:2] == ("pull", remote)
    verify.assert_called_once()
