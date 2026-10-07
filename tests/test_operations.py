import argparse
import io
import json
import os
import sqlite3
import tarfile
from unittest.mock import Mock

import pytest
from cryptography.exceptions import InvalidTag

from ops import access, backup, cli, doctor, expose, install, lima, snapshot


@pytest.mark.parametrize("system,legacy", [("Linux", False), ("Linux", True), ("Darwin", True)])
def test_expose_uses_shared_https_and_migrates_only_owned_routes(
    tmp_path, monkeypatch, system, legacy
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.platform, "system", lambda: system)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(expose, "tailscale_binary", lambda: "tailscale")
    monkeypatch.setattr(access, "connect", Mock())
    monkeypatch.setattr(lima, "mac", Mock())
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/mac.json").write_text(json.dumps({"mcp_port": 28787}))
    host = "bridge.example.ts.net"
    config = (
        {"Web": {host + ":8443": {"Handlers": {"/": {"Proxy": "https://localhost:8443"}}}}}
        if legacy
        else {}
    )
    if legacy:
        (tmp_path / ".bridge/expose.json").write_text(
            json.dumps({"hostname": host, "config": config})
        )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1:] == ["status", "--json"]:
            return json.dumps({"BackendState": "Running", "Self": {"DNSName": host + "."}})
        if command[1:] == ["serve", "status", "--json"]:
            return json.dumps(config)
        if command[1] == "funnel":
            config.setdefault("Web", {})[host + ":443"] = {
                "Handlers": {"/": {"Proxy": command[-1]}}
            }
        if command[1:] == ["serve", "--https=8443", "off"]:
            del config["Web"][host + ":8443"]
        return ""

    monkeypatch.setattr(cli, "run", run)
    args = argparse.Namespace(local=False)
    expose.expose(args)
    port = 28787 if system == "Darwin" else 18787
    assert ["tailscale", "funnel", "--bg", "--https=443", f"http://127.0.0.1:{port}"] in calls
    assert list(config["Web"]) == [host + ":443"]
    assert (tmp_path / ".bridge/admin-url").read_text() == "https://" + host
    assert (tmp_path / ".bridge/public-url").read_text() == "https://" + host
    calls.clear()
    expose.expose(args)
    assert not any("off" in command for command in calls)
    # An unrelated route added later must prevent all mutations.
    config["Web"][host + ":10000"] = {"Handlers": {"/": {"Proxy": "http://localhost:9999"}}}
    calls.clear()
    with pytest.raises(RuntimeError, match="그대로 두었습니다"):
        expose.expose(args)
    assert all(command[-1] == "--json" for command in calls)


def test_mac_passkey_setup_uses_saved_shared_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/mac.json").write_text(
        json.dumps({"vm": "test", "directory": "/srv/bridge"})
    )
    (tmp_path / ".bridge/admin-url").write_text("https://bridge.example.ts.net")
    execute = Mock(return_value="https://bridge.example.ts.net/admin/")
    monkeypatch.setattr(cli, "run", execute)
    access.passkey_setup(
        argparse.Namespace(local=False, url=None, public_url=None, enroll=False, link_only=True)
    )
    assert execute.call_args.args[0][-2:] == ["--url", "https://bridge.example.ts.net"]


def test_release_manifest_requires_immutable_official_refs(tmp_path):
    path = tmp_path / "release.json"
    data = {
        "schema": 1,
        "version": "v0.2.0",
        "images": {
            kind: "ghcr.io/rokrokss/kakaotalk-bridge-" + kind + "@sha256:" + "a" * 64
            for kind in ("server", "device", "gateway")
        },
    }
    path.write_text(json.dumps(data))
    assert cli.manifest(path)["server"].endswith("a" * 64)
    for bad in (
        "evil.example/server@sha256:" + "a" * 64,
        "ghcr.io/example/another-project-server@sha256:" + "a" * 64,
        "ghcr.io/rokrokss/kakaotalk-bridge-server:latest",
    ):
        data["images"]["server"] = bad
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            cli.manifest(path)


def test_admin_uses_private_serve_url_and_allows_tunnel_override(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    pairing = Mock(return_value="test-pair-code")
    monkeypatch.setattr(access, "admin_code", pairing)
    monkeypatch.setattr(access, "admin_info", lambda: {"origin": None})
    monkeypatch.setattr(backup, "recover_activation", Mock())
    opener = Mock()
    monkeypatch.setattr(access, "open_admin_page", opener)
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/admin-url").write_text("https://bridge.example.ts.net:8443")
    monkeypatch.setattr(cli.sys, "argv", ["bridge", "admin"])
    cli.main()
    opener.assert_called_once_with("https://bridge.example.ts.net:8443/admin/")
    pairing.assert_not_called()
    monkeypatch.setattr(cli.sys, "argv", ["bridge", "admin", "--url", "https://localhost:18443"])
    cli.main()
    opener.assert_called_with("https://localhost:18443")
    monkeypatch.setattr(access, "open_admin", opener)
    monkeypatch.setattr(cli.sys, "argv", ["bridge", "admin", "--recovery"])
    cli.main()
    pairing.assert_called_once()
    opener.assert_called_with("test-pair-code", "https://bridge.example.ts.net:8443/admin/")


def test_env_update_preserves_identity_and_rejects_shell_syntax(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DEVICE_ID=my-tablet\n# preserved\nDOT_PUBLIC_URL=https://old.test\n"
    )
    cli.env_update({"DOT_PUBLIC_URL": "https://new.test"})
    assert cli.read_env()["DEVICE_ID"] == "my-tablet"
    assert "# preserved" in (tmp_path / ".env").read_text()
    with pytest.raises(ValueError):
        cli.env_update({"DOT_PUBLIC_URL": "$(echo not-a-url)"})


def test_existing_keys_are_not_regenerated_when_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/ingest_token").write_text("existing")
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(RuntimeError, match="인증 키가 없거나 비어"):
        install.init_secrets(False)
    run.assert_not_called()


def test_legacy_mode_migration_preserves_installation_and_explicit_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    path = tmp_path / ".env"
    path.write_text("ADMIN_AUTH_MODE=kakao\nDOT_APPROVAL_MODE=kakao\nDEVICE_ID=existing\n")
    install.migrate_auth_modes()
    assert cli.read_env() == {
        "ADMIN_AUTH_MODE": "passkey",
        "DOT_APPROVAL_MODE": "passkey",
        "DEVICE_ID": "existing",
    }
    unchanged = path.read_bytes()
    install.migrate_auth_modes()
    assert path.read_bytes() == unchanged
    path.write_text("ADMIN_AUTH_MODE=local\nDOT_APPROVAL_MODE=admin\n")
    install.migrate_auth_modes()
    assert cli.read_env() == {"ADMIN_AUTH_MODE": "local", "DOT_APPROVAL_MODE": "admin"}


def source_tree(root):
    volumes = root / "snapshot"
    project = root / "project"
    for name in snapshot.VOLUMES:
        (volumes / name).mkdir(parents=True)
    (project / "secrets").mkdir(parents=True)
    (project / ".env").write_text("DEVICE_ID=personal-tablet\n")
    (project / "secrets/backup_key").write_text("01" * 32)
    (volumes / "android-data/private").write_text("private message fixture")
    (volumes / "android-data/link").symlink_to("/data/private")
    db = sqlite3.connect(volumes / "collector-data/collector.db")
    db.executescript(
        "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT); INSERT INTO metadata VALUES('cursor_epoch','old'); CREATE TABLE gaps(started_at TEXT, ended_at TEXT, reason TEXT);"
    )
    db.close()
    for name in ("admin-state/admin.db", "dot-state/dot.db", "passkey-state/passkeys.db"):
        db = sqlite3.connect(volumes / name)
        db.executescript(
            "CREATE TABLE records(kind TEXT,id TEXT,value BLOB); INSERT INTO records VALUES('session','old','secret'); INSERT INTO records VALUES('settings','profile','same'); INSERT INTO records VALUES('owner','password','keep');"
        )
        db.executescript(
            "INSERT INTO records VALUES('kakao-flow','old','pending'); INSERT INTO records VALUES('kakao-enroll','old','pending'); INSERT INTO records VALUES('kakao','config','retire provider config');"
        )
        if name.startswith("passkey"):
            db.executescript(
                "INSERT INTO records VALUES('passkey','config','keep rp');"
                "INSERT INTO records VALUES('credential','registered','keep public key');"
                "INSERT INTO records VALUES('ceremony','pending','remove');"
                "INSERT INTO records VALUES('enroll','unused','remove');"
            )
        db.close()
    return volumes, project


def destination_tree(root):
    volumes, project, work = root / "snapshot", root / "project", root / "work"
    for name in snapshot.VOLUMES:
        (volumes / name).mkdir(parents=True)
    project.mkdir(parents=True)
    work.mkdir(parents=True)
    return volumes, project, work


def test_full_snapshot_roundtrip_and_authentication_before_restore(tmp_path):
    volumes, project = source_tree(tmp_path / "original")
    with sqlite3.connect(volumes / "collector-data/collector.db") as db:
        db.executescript(
            "CREATE TABLE outgoing(status TEXT, reason TEXT, text TEXT);"
            "INSERT INTO outgoing VALUES('queued',NULL,'unsent text');"
            "INSERT INTO outgoing VALUES('dispatching',NULL,NULL);"
            "INSERT INTO outgoing VALUES('submitted',NULL,NULL);"
        )
    output = io.BytesIO()
    key = b"k" * 32
    snapshot.create(output, key, volumes, project)
    encrypted = output.getvalue()
    assert b"private message fixture" not in encrypted
    destination, configuration, work = destination_tree(tmp_path / "restored")
    tampered = bytearray(encrypted)
    tampered[64] ^= 1
    with pytest.raises(InvalidTag):
        snapshot.restore(io.BytesIO(tampered), key, destination, configuration, work)
    assert not list(configuration.iterdir())
    assert not list((destination / "android-data").iterdir())
    assert not list(work.iterdir())
    snapshot.restore(io.BytesIO(encrypted), key, destination, configuration, work)
    assert (destination / "android-data/private").read_text() == "private message fixture"
    assert os.readlink(destination / "android-data/link") == "/data/private"
    with sqlite3.connect(destination / "collector-data/collector.db") as db:
        assert db.execute("SELECT status,text FROM outgoing").fetchall() == [
            ("unknown", None),
            ("unknown", None),
            ("submitted", None),
        ]
        assert (
            db.execute("SELECT value FROM metadata WHERE key='cursor_epoch'").fetchone()[0] != "old"
        )
    with sqlite3.connect(destination / "admin-state/admin.db") as db:
        assert not db.execute("SELECT 1 FROM records WHERE kind='session'").fetchall()
        assert db.execute("SELECT 1 FROM records WHERE kind='owner'").fetchone()
        assert not db.execute("SELECT 1 FROM records WHERE kind='kakao'").fetchone()
        assert not db.execute("SELECT 1 FROM records WHERE kind='kakao-flow'").fetchone()
        assert not db.execute("SELECT 1 FROM records WHERE kind='kakao-enroll'").fetchone()
    with sqlite3.connect(destination / "dot-state/dot.db") as db:
        assert {row[0] for row in db.execute("SELECT kind FROM records")} == {"settings"}
    with sqlite3.connect(destination / "passkey-state/passkeys.db") as db:
        assert set(db.execute("SELECT kind,value FROM records")) == {
            ("passkey", "keep rp"),
            ("credential", "keep public key"),
        }


def test_archive_path_and_link_traversal_rejected(tmp_path):
    for name in ("/project/secrets/key", "project/../escape", "snapshot/unknown/file"):
        with pytest.raises(ValueError):
            snapshot.member_target(
                tarfile.TarInfo(name), tmp_path / "snapshot", tmp_path / "project"
            )
    info = tarfile.TarInfo("project/secrets/token")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    with pytest.raises(ValueError):
        snapshot.member_target(info, tmp_path / "snapshot", tmp_path / "project")


def test_restore_never_runs_against_running_stack(tmp_path, monkeypatch):
    archive, key = tmp_path / "backup", tmp_path / "key"
    archive.touch()
    key.touch()
    monkeypatch.setattr(cli, "compose", Mock(return_value="api\nadmin"))
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    with pytest.raises(RuntimeError, match="서비스를 중지하세요"):
        backup.restore(archive, key)
    run.assert_not_called()


def test_restore_activation_rolls_back_partial_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/key").write_text("old")
    (tmp_path / ".env").write_text("DEVICE_ID=old\n")
    stage = tmp_path / ".bridge/restore-test"
    (stage / "secrets").mkdir(parents=True)
    (stage / "secrets/key").write_text("new")
    (stage / ".env").write_text("DEVICE_ID=new\n")
    real_atomic = cli.atomic

    def fail_override(path, data):
        if path.name == "volumes.yaml":
            raise OSError("test disk failure")
        real_atomic(path, data)

    monkeypatch.setattr(cli, "atomic", fail_override)
    with pytest.raises(OSError):
        backup.activate_restore(stage, {"android-data": "new_volume"})
    assert (tmp_path / "secrets/key").read_text() == "old"
    assert (tmp_path / ".env").read_text() == "DEVICE_ID=old\n"
    assert not (tmp_path / ".bridge/restore-activation.json").exists()


def test_source_refresh_removes_stale_code_and_rolls_back_without_touching_keys(tmp_path):
    from ops import source

    root = tmp_path / "runtime"
    (root / "ops").mkdir(parents=True)
    (root / "ops/deleted.py").write_text("old")
    (root / "secrets").mkdir()
    (root / "secrets/key").write_text("keep")
    incoming = tmp_path / "incoming"
    (incoming / "ops").mkdir(parents=True)
    (incoming / "ops/cli.py").write_text("new")
    (incoming / "compose.yaml").write_text("services: {}")
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.add(incoming / "ops", arcname="ops")
        archive.add(incoming / "compose.yaml", arcname="compose.yaml")
    source.apply(root, path)
    assert not (root / "ops/deleted.py").exists()
    assert (root / "ops/cli.py").read_text() == "new"
    assert (root / "secrets/key").read_text() == "keep"
    source.rollback(root)
    assert (root / "ops/deleted.py").read_text() == "old"
    assert not (root / "ops/cli.py").exists()
    assert (root / "secrets/key").read_text() == "keep"


def test_rejected_source_archive_changes_nothing_and_leaves_no_scratch(tmp_path):
    from ops import source

    root = tmp_path / "runtime"
    (root / "ops").mkdir(parents=True)
    (root / "ops/cli.py").write_text("old")
    unsafe = tmp_path / ".env.example"
    unsafe.write_text("X=1")
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.add(unsafe, arcname=".env.example")
    with pytest.raises(RuntimeError, match="허용되지 않는 경로"):
        source.apply(root, path)
    assert (root / "ops/cli.py").read_text() == "old"
    assert list((root / ".bridge").iterdir()) == []


def test_source_image_identity_changes_for_dependencies_and_renames(tmp_path, monkeypatch):
    from argparse import Namespace

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "requirements.lock").write_text("dependency version one")
    (tmp_path / "module.py").write_text("content")
    args = Namespace(source=True, manifest=None)
    first = install.image_config(args)
    (tmp_path / "requirements.lock").write_text("dependency version two")
    second = install.image_config(args)
    assert first != second
    (tmp_path / "module.py").rename(tmp_path / "renamed.py")
    assert second != install.image_config(args)
    unchanged = install.image_config(args)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/private").write_text("not part of image identity")
    assert unchanged == install.image_config(args)


def test_default_admin_mode_starts_private_passkey_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("DOT_PUBLIC_URL=https://unset.invalid\n")
    assert "dot-control" in cli.services()
    assert "dot-plugin" not in cli.services()


def test_android_builder_repairs_broken_arm_emulation_then_verifies(monkeypatch):
    monkeypatch.setattr(cli.platform, "machine", lambda: "aarch64")
    execute = Mock(side_effect=[RuntimeError("emulator crash"), "", ""])
    monkeypatch.setattr(cli, "run", execute)
    install.prepare_android_builder()
    commands = [call.args[0] for call in execute.call_args_list]
    assert commands[0] == commands[2]
    assert "--privileged" in commands[1]
    assert commands[1][-4:] == ["--uninstall", "qemu-x86_64", "--install", "amd64"]
    assert "@sha256:" in commands[1][-5]


def test_android_builder_preserves_working_emulation_and_skips_intel(monkeypatch):
    execute = Mock(return_value="")
    monkeypatch.setattr(cli, "run", execute)
    monkeypatch.setattr(cli.platform, "machine", lambda: "aarch64")
    install.prepare_android_builder()
    assert execute.call_count == 1
    assert "--privileged" not in execute.call_args.args[0]
    monkeypatch.setattr(cli.platform, "machine", lambda: "x86_64")
    install.prepare_android_builder()
    assert execute.call_count == 1


@pytest.mark.parametrize(
    "volume, expected",
    [("kakaotalk-collector_android-data\n", "kakaotalk-collector"), ("", "kakaotalk-bridge")],
)
def test_install_without_project_name_keeps_existing_volumes(
    tmp_path, monkeypatch, volume, expected
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("HTTPS_PORT=8443\n")
    calls = []
    monkeypatch.setattr(cli, "run", lambda args, **kwargs: calls.append(args) or volume)
    cli.pin_project_name.cache_clear()
    try:
        cli.pin_project_name()
    finally:
        cli.pin_project_name.cache_clear()
    assert cli.read_env()["COMPOSE_PROJECT_NAME"] == expected
    assert calls[0][:3] == ["docker", "volume", "ls"]


def test_project_name_already_set_is_never_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=custom\n")
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("no Docker call expected"))
    cli.pin_project_name.cache_clear()
    try:
        cli.pin_project_name()
    finally:
        cli.pin_project_name.cache_clear()
    assert cli.read_env()["COMPOSE_PROJECT_NAME"] == "custom"


def test_doctor_prints_a_korean_summary_and_json_on_request(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=kakaotalk-bridge\n")
    monkeypatch.setattr(cli, "run", lambda args, **kwargs: "linux/aarch64")
    rows = [{"Service": name, "State": "running", "Health": ""} for name in cli.SERVICES]
    rows[1] = {"Service": "api", "State": "exited", "Health": ""}
    monkeypatch.setattr(cli, "compose", lambda *args, **kwargs: json.dumps(rows))
    monkeypatch.setattr(cli.Path, "exists", lambda self: True)
    assert doctor.doctor() is False
    text = capsys.readouterr().out
    assert "KakaoTalk Bridge 상태 점검" in text and "api: 중지됨" in text
    assert "확인이 필요한 항목" in text and "{" not in text
    doctor.doctor(report="json")
    assert json.loads(capsys.readouterr().out)["services"][1]["State"] == "exited"


def test_shared_code_is_readable_but_private_state_is_untouched(tmp_path):
    from ops.source import share_code

    (tmp_path / "ops").mkdir(mode=0o700)
    (tmp_path / "ops/cli.py").write_text("code")
    (tmp_path / "bridge").write_text("#!/usr/bin/env python3")
    (tmp_path / "secrets").mkdir(mode=0o700)
    (tmp_path / "secrets/admin_token").write_text("secret")
    for path, mode in (("ops/cli.py", 0o600), ("bridge", 0o700), ("secrets/admin_token", 0o600)):
        (tmp_path / path).chmod(mode)
    (tmp_path / ".env").write_text("HTTPS_PORT=8443\n")
    (tmp_path / ".env").chmod(0o600)
    (tmp_path / ".env.local").write_text("private")
    (tmp_path / ".env.local").chmod(0o600)
    share_code(tmp_path)
    mode = lambda path: oct((tmp_path / path).stat().st_mode & 0o777)
    assert mode("ops") == "0o755" and mode("ops/cli.py") == "0o644" and mode("bridge") == "0o755"
    assert mode(".env") == "0o644" and mode(".env.local") == "0o600"
    assert mode("secrets") == "0o700" and mode("secrets/admin_token") == "0o600"


@pytest.mark.parametrize(
    "days, ok, text", [(400, True, "까지"), (10, True, "곧 만료"), (-1, False, "만료됨")]
)
def test_doctor_reports_certificate_expiry(tmp_path, monkeypatch, days, ok, text):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/tls_cert.pem").write_text("certificate")
    end = (datetime.now(UTC) + timedelta(days=days, hours=1)).strftime("%b %d %H:%M:%S %Y GMT")
    monkeypatch.setattr(cli, "run", lambda *a, **k: "notAfter=" + end)
    report = doctor.certificate()
    assert report["ok"] is ok and abs(report["days"] - days) <= 1
    assert text in doctor.doctor_text(
        {
            "docker": {"ok": True},
            "compose": {"ok": True},
            "binder": {"ok": True},
            "missing_secrets": [],
            "services": [],
            "certificate": report,
        },
        set(),
        ok,
    )


@pytest.mark.parametrize("healthy", [True, False])
def test_update_provisions_send_key_before_compose_and_preserves_rollback(
    tmp_path, monkeypatch, healthy
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    for name in ("read_token", "ingest_token", "device_token"):
        (tmp_path / "secrets" / name).write_text(name * 8)
    env = tmp_path / ".env"
    old, new = "COLLECTOR_IMAGE=old\n", "COLLECTOR_IMAGE=new\n"
    env.write_text(old)
    before = {p.name: p.read_bytes() for p in (tmp_path / "secrets").iterdir()}
    calls = []

    def prepare(args):
        assert len((tmp_path / "secrets/send_token").read_text().strip()) >= 32
        env.write_text(new)
        return old

    def backup_old(**kwargs):
        assert env.read_text() == old
        assert (tmp_path / "secrets/send_token").exists()

    monkeypatch.setattr(install, "prepare_images", prepare)
    monkeypatch.setattr(install, "image_config", lambda args: {"COLLECTOR_IMAGE": "helper"})
    monkeypatch.setattr(backup, "backup", backup_old)
    monkeypatch.setattr(doctor, "doctor", lambda **kwargs: healthy)
    monkeypatch.setattr(cli, "compose", lambda *args: calls.append(env.read_text()))
    monkeypatch.setattr(cli, "services", lambda: ["api", "iris-collector"])
    monkeypatch.setattr(cli, "share_code", Mock())
    monkeypatch.setattr(install.time, "sleep", lambda seconds: None)
    if healthy:
        install.update(argparse.Namespace())
        assert calls == [new]
        assert env.read_text() == new
    else:
        with pytest.raises(RuntimeError, match="이전 버전으로 되돌렸습니다"):
            install.update(argparse.Namespace())
        assert calls == [new, old]
        assert env.read_text() == old
    path = tmp_path / "secrets/send_token"
    first = path.read_bytes()
    install.ensure_send_secret()
    assert path.read_bytes() == first
    assert path.stat().st_mode & 0o777 == 0o444
    assert {name: (tmp_path / "secrets" / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("value", ["short", "read_token" * 8])
def test_invalid_send_key_stops_update_without_replacing_credentials(tmp_path, monkeypatch, value):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    for name in ("read_token", "ingest_token", "device_token"):
        (tmp_path / "secrets" / name).write_text(name * 8)
    path = tmp_path / "secrets/send_token"
    path.write_text(value)
    prepare = Mock()
    monkeypatch.setattr(install, "prepare_images", prepare)
    with pytest.raises(RuntimeError, match="send_token"):
        install.update(argparse.Namespace())
    prepare.assert_not_called()
    assert path.read_text() == value
