import argparse
import json
import os
import socket
import subprocess
import sys
import tarfile
from unittest.mock import Mock

import pytest

from ops import cli, onboarding


def options(*extra):
    parser = argparse.ArgumentParser()
    onboarding.add_arguments(parser)
    return parser.parse_args(extra)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(onboarding.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(onboarding.platform, "machine", lambda: "arm64")
    return tmp_path


def test_plan_never_installs_opens_browser_or_writes_state(home, monkeypatch, capsys):
    execute = Mock(side_effect=AssertionError("no commands in a plan"))
    monkeypatch.setattr(cli, "run", execute)
    monkeypatch.setattr(onboarding.webbrowser, "open", execute)
    onboarding.up(options("--plan"))
    assert not list(home.iterdir())
    assert "setup plan (no changes)" in capsys.readouterr().out


def fake_runtime(monkeypatch, *, installed=False):
    runtime = Mock()
    runtime.prefix = []
    runtime.installed.return_value = installed
    runtime.call.return_value = "https://bridge.test:8443/admin/#passkey-setup=" + "a" * 43
    monkeypatch.setattr(onboarding, "Runtime", lambda: runtime)
    monkeypatch.setattr(onboarding, "prepare_mac", Mock())
    monkeypatch.setattr(onboarding, "connect_network", Mock())
    return runtime


def test_first_run_installs_then_waits_before_browser(home, monkeypatch):
    runtime = fake_runtime(monkeypatch)
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    onboarding.up(options())
    assert runtime.call.call_args_list[0].args == (
        "install",
        "--source",
        "--vm",
        "kakaotalk-bridge",
    )
    assert runtime.wait_ready.call_count == 2
    opened.assert_called_once_with(runtime.call.return_value)
    assert json.loads((home / ".bridge/onboarding.json").read_text())["state"] == "ready"
    assert "passkey" not in (home / ".bridge/onboarding.json").read_text()


def test_returning_user_starts_without_reinstall_or_new_registration(home, monkeypatch):
    runtime = fake_runtime(monkeypatch, installed=True)
    runtime.call.return_value = "https://bridge.test:8443/admin/"
    (home / ".env").write_text("KEEP=original")
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    onboarding.up(options("--no-browser"))
    assert runtime.call.call_args_list[0].args == ("start",)
    assert runtime.call.call_args_list[-1].args == ("passkey-login", "--link-only")
    assert (home / ".env").read_text() == "KEEP=original"
    opened.assert_not_called()


def test_failure_is_resumable_without_persisting_auth_links(home, monkeypatch):
    runtime = fake_runtime(monkeypatch)
    runtime.wait_ready.side_effect = RuntimeError("not ready")
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    with pytest.raises(RuntimeError, match="not ready"):
        onboarding.up(options())
    assert json.loads((home / ".bridge/onboarding.json").read_text()) == {
        "step": "runtime",
        "state": "interrupted",
    }
    opened.assert_not_called()
    runtime.installed.return_value = True
    runtime.wait_ready.side_effect = None
    runtime.call.reset_mock()
    onboarding.up(options())
    assert runtime.call.call_args_list[0].args == ("start",)


def test_installation_lock_prevents_two_mutating_runs(home):
    with (
        onboarding.installation_lock(),
        pytest.raises(RuntimeError, match="already running"),
        onboarding.installation_lock(),
    ):
        pytest.fail("second lock acquired")
    with onboarding.installation_lock():
        pass


@pytest.mark.parametrize(
    "url",
    ["http://example.test", "https://a.test/#passkey-setup=short", "https://a.test/?token=secret"],
)
def test_bad_registration_response_never_opens_browser(home, monkeypatch, url):
    runtime = Mock()
    runtime.call.return_value = url
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    with pytest.raises((ValueError, RuntimeError)):
        onboarding.open_setup(options(), runtime)
    opened.assert_not_called()


def test_custom_proxy_requires_matching_admin_and_public_hosts(home):
    with pytest.raises(ValueError, match="both"):
        onboarding.validate(options("--admin-url", "https://private.test"))
    with pytest.raises(ValueError, match="same hostname"):
        onboarding.validate(
            options("--admin-url", "https://a.test", "--public-url", "https://b.test")
        )


def test_shared_proxy_uses_one_origin_for_setup_and_mcp(home, monkeypatch):
    args = options("--url", "https://bridge.test", "--no-browser")
    onboarding.validate(args)
    runtime = Mock(return_value=None)
    runtime.call.return_value = "https://bridge.test/admin/"
    onboarding.connect_network(args, runtime)
    onboarding.open_setup(args, runtime)
    assert runtime.call.call_args_list[0].args == ("connect", "--url", "https://bridge.test")
    assert runtime.call.call_args_list[1].args == (
        "passkey-login",
        "--link-only",
        "--url",
        "https://bridge.test",
        "--public-url",
        "https://bridge.test",
    )
    with pytest.raises(ValueError, match="alone"):
        onboarding.validate(
            options("--url", "https://bridge.test", "--admin-url", "https://bridge.test")
        )


def test_existing_proxy_skips_tailscale(home, monkeypatch):
    runtime = Mock()
    monkeypatch.setattr(cli, "tailscale_binary", Mock(side_effect=AssertionError("not needed")))
    onboarding.connect_network(
        options("--admin-url", "https://a.test:8443", "--public-url", "https://a.test"), runtime
    )
    runtime.call.assert_called_once_with("connect", "--url", "https://a.test", capture=True)


def test_missing_wsl_binder_stops_before_installing_anything(home, monkeypatch):
    monkeypatch.setattr(onboarding.platform, "release", lambda: "6.6-microsoft-standard-WSL2")
    monkeypatch.setattr(onboarding, "binder_ready", lambda: False)
    execute = Mock(side_effect=AssertionError("no changes"))
    monkeypatch.setattr(cli, "run", execute)
    with pytest.raises(RuntimeError, match="No changes were made"):
        onboarding.prepare_linux(options())


def test_no_install_does_not_bootstrap_missing_mac_tools(home, monkeypatch):
    monkeypatch.setattr(onboarding.os, "geteuid", lambda: 501)
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: None)
    execute = Mock()
    monkeypatch.setattr(onboarding, "install_script", execute)
    with pytest.raises(RuntimeError, match="--no-install"):
        onboarding.prepare_mac(options("--no-install"))
    execute.assert_not_called()


def test_docker_remote_context_is_rejected_even_with_local_host_override(home, monkeypatch):
    monkeypatch.setattr(onboarding.platform, "system", lambda: "Linux")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setattr(
        cli,
        "run",
        Mock(return_value=json.dumps([{"Endpoints": {"docker": {"Host": "ssh://remote"}}}])),
    )
    with pytest.raises(RuntimeError, match="context points elsewhere"):
        onboarding.Runtime()


def test_source_archive_without_git_excludes_state_builds_and_symlinks(home):
    for filename in [
        "ops/cli.py",
        "compose.yaml",
        "secrets/key",
        "ops/.env",
        "android/.gradle/cache",
        "android/bridge/build/debug.apk",
        "artifacts/private",
        "deploy/test.local.plist",
    ]:
        path = home / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test")
    (home / "ops/private").symlink_to(home / "secrets", target_is_directory=True)
    archive = home / "output.tar.gz"
    cli.package_source(archive)
    with tarfile.open(archive) as bundle:
        assert set(bundle.getnames()) == {"ops/cli.py", "compose.yaml"}


def test_mac_start_wakes_vm_before_running_compose(home, monkeypatch):
    (home / ".bridge").mkdir()
    (home / ".bridge/mac.json").write_text(
        json.dumps({"vm": "existing", "directory": "/srv/bridge", "admin_port": 18443})
    )
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/limactl")
    execute = Mock()
    monkeypatch.setattr(cli, "run", execute)
    cli.mac(argparse.Namespace(command="start"))
    assert execute.call_args_list[0].args[0] == ["limactl", "start", "--tty=false", "existing"]
    assert execute.call_args_list[1].args[0][-2:] == ["--local", "start"]


def test_repeated_apk_import_preserves_identical_set_and_rejects_mixing(home, monkeypatch):
    source = home / "provided"
    source.mkdir()
    (source / "base.apk").write_bytes(b"synthetic package")
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "recover_activation", Mock())
    monkeypatch.setattr(cli.sys, "argv", ["bridge", "import-apks", str(source)])
    cli.main()
    imported = home / "inputs/kakao/0.apk"
    original = imported.stat().st_mtime_ns
    cli.main()
    assert imported.stat().st_mtime_ns == original
    (source / "split.apk").write_bytes(b"different package")
    with pytest.raises(SystemExit):
        cli.main()
    assert imported.read_bytes() == b"synthetic package"
    assert len(list(imported.parent.iterdir())) == 1


def test_shell_entry_reuses_installation_with_spaces_and_forwards_arguments(tmp_path):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "install.sh"
    target = tmp_path / "my bridge"
    target.mkdir()
    (target / "bridge").write_text("import json, sys; print(json.dumps(sys.argv[1:]))")
    sentinel = target / ".env"
    sentinel.write_text("identity unchanged")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3.14").symlink_to(sys.executable)
    curl = binaries / "curl"
    curl.write_text("#!/bin/sh\necho 'Unexpected download' >&2\nexit 99\n")
    curl.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script), "--no-browser", "--apk-folder", "/a path/apks"],
        env={
            **os.environ,
            "BRIDGE_HOME": str(target),
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        },
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == [
        "up",
        "--no-browser",
        "--apk-folder",
        "/a path/apks",
    ]
    assert sentinel.read_text() == "identity unchanged"


def test_signed_out_network_status_is_not_treated_as_a_daemon_failure(monkeypatch):
    monkeypatch.setattr(
        onboarding.subprocess,
        "run",
        Mock(return_value=Mock(returncode=1, stdout='{"BackendState":"NeedsLogin"}')),
    )
    assert (
        onboarding.network_status(["tailscale", "status", "--json"])["BackendState"] == "NeedsLogin"
    )


def test_occupied_default_port_is_automatic_but_explicit_port_is_not():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        assert cli.available_port(port) != port
        with pytest.raises(RuntimeError, match="already in use"):
            cli.available_port(port, port)


def test_failed_first_vm_boot_retains_selected_ports_for_retry(home, monkeypatch):
    (home / "deploy").mkdir()
    (home / "deploy/lima.yaml").write_text("hostPort: 18443\n  - guestPortRange:\n")
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/limactl")
    choose = Mock(side_effect=[39443, 38787])
    monkeypatch.setattr(cli, "available_port", choose)

    def execute(args, **kwargs):
        if args[1] == "list":
            return ""
        if args[1] == "start":
            raise RuntimeError("provisioning interrupted")
        pytest.fail("Should not reach source transfer")

    monkeypatch.setattr(cli, "run", execute)
    args = argparse.Namespace(command="install", vm="fresh-test", admin_port=None, mcp_port=None)
    with pytest.raises(RuntimeError, match="interrupted"):
        cli.mac(args)
    saved = json.loads((home / ".bridge/mac.json").read_text())
    assert (saved["admin_port"], saved["mcp_port"]) == (39443, 38787)
    with pytest.raises(RuntimeError, match="interrupted"):
        cli.mac(args)
    assert choose.call_count == 2
