import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from device import cli, setup


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


def test_preserve_bootstrap_keeps_identity_proof_and_approval(monkeypatch, tmp_path):
    identity = {"device_id": "personal-tablet", "enrollment_epoch": "e"}
    host = tmp_path / "enrollment.json"
    host.write_text(json.dumps(identity))
    proof = tmp_path / "prelogin.json"
    proof.write_text("existing proof")
    original_path = Path
    monkeypatch.setattr(
        cli, "Path", lambda p: host if p == "/state/enrollment.json" else original_path(p)
    )
    monkeypatch.setattr(cli, "sample", lambda: {"state": "android_ready"})
    monkeypatch.setattr(cli, "connect", Mock())
    calls = []

    def adb(*args, **kwargs):
        calls.append(args)
        if args == ("shell", "id", "-u"):
            return "0"
        if args[:3] == ("shell", "sh", "-c"):
            return "present"
        if args == ("shell", "cat", cli.REMOTE_CONFIG):
            return json.dumps({**identity, "secondary_login_version": 29260820})
        return ""

    monkeypatch.setattr(cli, "adb", adb)
    assert cli.bootstrap(preserve=True) is False
    assert json.loads(host.read_text()) == identity
    assert proof.read_text() == "existing proof"
    assert all(call[0] not in ("install", "install-multiple", "push") for call in calls)


def test_publisher_signature_is_required(monkeypatch):
    result = Mock(returncode=0, stdout="Signer #1 certificate SHA-256 digest: " + "0" * 64)
    monkeypatch.setattr(setup.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match="kakao_signature_unverified"):
        setup.verify_kakao(["/tmp/test.apk"])
    result.stdout = "Signer #1 certificate SHA-256 digest: " + setup.KAKAO_SIGNER
    setup.verify_kakao(["/tmp/test.apk"])
