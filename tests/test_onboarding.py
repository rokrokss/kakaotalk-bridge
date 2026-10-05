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
    assert "설정 계획 (변경 없음)" in capsys.readouterr().out


def fake_runtime(monkeypatch, *, installed=False):
    runtime = Mock()
    runtime.prefix = []
    runtime.installed.return_value = installed
    runtime.call.return_value = "https://bridge.test:8443/admin/#passkey-setup=" + "a" * 43
    monkeypatch.setattr(onboarding, "Runtime", lambda: runtime)
    monkeypatch.setattr(onboarding, "prepare_mac", Mock())
    monkeypatch.setattr(onboarding, "connect_network", Mock())
    return runtime


def test_first_run_installs_then_waits_before_browser(home, monkeypatch, capsys):
    runtime = fake_runtime(monkeypatch)
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    onboarding.up(options("--source"))
    assert runtime.call.call_args_list[0].args == (
        "install",
        "--source",
        "--vm",
        "kakaotalk-bridge",
    )
    assert runtime.wait_ready.call_count == 2
    assert ("setup-agent", "install") in [call.args for call in runtime.call.call_args_list]
    opened.assert_called_once_with(runtime.call.return_value)
    assert json.loads((home / ".bridge/onboarding.json").read_text())["state"] == "ready"
    assert "passkey" not in (home / ".bridge/onboarding.json").read_text()
    output = capsys.readouterr().out
    assert output.count("완료") == 4
    assert runtime.call.return_value in output
    assert all("passkey" not in log.read_text() for log in (home / ".bridge/logs").iterdir())


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


def test_missing_release_does_not_silently_build_source(home, monkeypatch):
    runtime = fake_runtime(monkeypatch)
    with pytest.raises(RuntimeError, match="explicit --source"):
        onboarding.up(options())
    runtime.call.assert_not_called()


@pytest.mark.parametrize("source", [False, True])
def test_fresh_shell_installer_passes_release_version_and_explicit_source(tmp_path, source):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "install.sh"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    target = tmp_path / "new bridge"
    helper = tmp_path / "helper.py"
    helper.write_text(
        "import pathlib,sys,json\n"
        "p=pathlib.Path(sys.argv[1]); p.mkdir()\n"
        "(p/'download-args.json').write_text(json.dumps(sys.argv[2:]))\n"
        "(p/'bridge').write_text('import json,sys; print(json.dumps(sys.argv[1:]))')\n"
    )
    curl = binaries / "curl"
    curl.write_text(
        f"#!{sys.executable}\nimport shutil,sys\n"
        f"shutil.copyfile({str(helper)!r}, sys.argv[sys.argv.index('-o')+1])\n"
    )
    curl.chmod(0o755)
    flags = ["--no-browser", *(["--source"] if source else [])]
    result = subprocess.run(
        ["/bin/bash", "-s", "--", *flags],
        input=script.read_text(),
        env={
            **os.environ,
            "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
            "BRIDGE_HOME": str(target),
            "BRIDGE_VERSION": "v0.1.0",
        },
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((target / "download-args.json").read_text()) == [
        "v0.1.0",
        *(["--source"] if source else []),
    ]
    assert json.loads(result.stdout.splitlines()[-1]) == ["up", *flags]


def test_failure_is_resumable_without_persisting_auth_links(home, monkeypatch, capsys):
    runtime = fake_runtime(monkeypatch)
    runtime.wait_ready.side_effect = RuntimeError("not ready")
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    with pytest.raises(RuntimeError, match="not ready"):
        onboarding.up(options("--source"))
    assert json.loads((home / ".bridge/onboarding.json").read_text()) == {
        "step": "runtime",
        "state": "interrupted",
    }
    opened.assert_not_called()
    output = capsys.readouterr()
    assert output.out.count("완료") == 1
    assert "개인 Bridge 시작 단계에서 중단" in output.err
    assert str(next((home / ".bridge/logs").iterdir())) in output.err
    runtime.installed.return_value = True
    runtime.wait_ready.side_effect = None
    runtime.call.reset_mock()
    onboarding.up(options("--source"))
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


def test_admin_and_ai_connections_are_independent(home):
    for flags in (
        (),
        ("--connection", "none"),
        ("--admin-url", "https://private.test"),
        ("--admin-url", "http://localhost:18789", "--public-url", "https://public.test"),
        ("--connection", "https", "--public-url", "https://public.test"),
    ):
        onboarding.validate(options(*flags))
    with pytest.raises(ValueError):
        onboarding.validate(options("--connection", "none", "--public-url", "https://a.test"))


def test_default_does_not_touch_network_providers(home, monkeypatch):
    runtime = Mock()
    monkeypatch.setattr(cli, "tailscale_binary", Mock(side_effect=AssertionError("no provider")))
    args = options()
    onboarding.validate(args)
    onboarding.connect_network(args, runtime)
    runtime.call.assert_not_called()


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


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_piped_installer_summarizes_bootstrap_and_preserves_failures(tmp_path, verbose, failed):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "install.sh"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    target = tmp_path / "bridge home"
    target.mkdir()
    (target / "bridge").write_text("import json, sys; print(json.dumps(sys.argv[1:]))")
    # An isolated PATH forces Python preparation without downloading or installing anything.
    for command in ("uname", "mktemp"):
        (binaries / command).symlink_to("/usr/bin/" + command)
    (binaries / "curl").write_text("#!/bin/sh\nexit 99\n")
    uv = binaries / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = install ]; then\n'
        "  echo 'runtime download detail'\n"
        "  echo 'runtime warning' >&2\n"
        f"  exit {7 if failed else 0}\n"
        "fi\n"
        f"printf '%s\\n' '{sys.executable}'\n"
    )
    uv.chmod(0o755)
    (binaries / "curl").chmod(0o755)
    flags = ["--verbose"] if verbose else []
    result = subprocess.run(
        ["/bin/bash", "-s", "--", *flags],
        input=script.read_text(),
        env={
            **os.environ,
            "PATH": str(binaries),
            "BRIDGE_HOME": str(target),
            "TMPDIR": str(tmp_path),
        },
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == (7 if failed else 0), result.stderr
    if verbose:
        assert "runtime download detail" in result.stdout
        assert "runtime warning" in result.stderr
    else:
        assert "runtime download detail" not in result.stdout
        assert "runtime warning" not in result.stderr
        log = next(tmp_path.glob("kakaotalk-bridge-setup.*"))
        assert "runtime download detail" in log.read_text()
        assert "runtime warning" in log.read_text()
        if failed:
            assert str(log) in result.stderr
    if not failed:
        assert "설치 실행 환경 준비 완료" in result.stdout
        assert json.loads(result.stdout.splitlines()[-1]) == ["up", *flags]


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
    choose = Mock(side_effect=[39443, 38787, 38789])
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
    assert choose.call_count == 3
    assert saved["local_admin_port"] == 38789


def test_root_owned_network_settings_are_read_without_exposing_secrets(home, monkeypatch):
    (home / ".env").write_text(
        "OPENAI_TUNNEL_ENABLED=1\nADMIN_LOCAL_PORT=19789\nPRIVATE_VALUE=never-return\n"
    )
    monkeypatch.setattr(cli, "read_env", Mock(side_effect=PermissionError))

    def privileged(command, **kwargs):
        return subprocess.run(command, text=True, capture_output=True, check=True).stdout

    monkeypatch.setattr(onboarding, "privileged", privileged)
    assert onboarding.network_config() == {
        "OPENAI_TUNNEL_ENABLED": "1",
        "ADMIN_LOCAL_PORT": "19789",
    }
