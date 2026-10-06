"""Connection setup authority, secret handling, orchestration and Unix transport."""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from ops import access, cli, expose, lima, onboarding, setup_agent, tunnel
from server.connection_setup import validate
from tests.test_webui import ORIGIN, TOKEN, signin
from webui.app import create_app
from webui.setup import SetupBusy, SetupClient

KEY = "sk-synthetic-" + "x" * 40
TUNNEL = "tunnel_" + "a" * 32


def request(method="none", **kwargs):
    return {"method": method, "request_id": str(uuid.uuid4()), **kwargs}


def tunnel_request(**kwargs):
    return request("openai-tunnel", tunnel_id=TUNNEL, api_key=KEY, approve=True) | kwargs


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"method": []},
        {"method": {}},
        request("shell", command="id"),
        request("none", command="id"),
        request("none", request_id="-" * 36),
        request("tailscale"),
        request("tailscale", install_tailscale=1),
        request("https", url="https://user:secret@host.test"),
        request("https", url="https://host.test/mcp"),
        request("https", url="https://host.test:65536"),
        request("https", url="https://host.test;touch /tmp/unsafe"),
        tunnel_request(approve=False),
        tunnel_request(approve=1),
        tunnel_request(tunnel_id="tunnel_;id"),
        tunnel_request(api_key_file="/etc/passwd"),
        tunnel_request(api_key=123),
        tunnel_request(api_key=KEY + "\n"),
    ],
)
def test_setup_contract_rejects_commands_paths_and_implicit_consent(data):
    with pytest.raises(ValueError):
        validate(data)


def test_web_setup_requires_admin_session_and_csrf():
    service = Mock()
    service.call.return_value = {"available": True, "job": {"state": "idle"}}
    app = create_app(TOKEN, Mock(), Mock(), auth_mode="local", setup_client=service)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/admin/api/connection-setup").status_code == 401
        assert (
            client.post(
                "/admin/api/connection-setup", json=tunnel_request(), headers={"Origin": ORIGIN}
            ).status_code
            == 401
        )
        service.call.assert_not_called()
        headers = signin(client)
        assert (
            client.post(
                "/admin/api/connection-setup", json=tunnel_request(), headers={"Origin": ORIGIN}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/admin/api/connection-setup",
                json=tunnel_request(),
                headers={**headers, "Origin": "https://evil.test"},
            ).status_code
            == 403
        )
        service.call.assert_not_called()
        assert client.get("/admin/api/connection-setup").json()["available"]
        data = tunnel_request()
        service.call.return_value = {"state": "running"}
        response = client.post("/admin/api/connection-setup", json=data, headers=headers)
        assert response.status_code == 202
        service.call.assert_called_with("POST", data)
        assert KEY not in response.text
        invalid = client.post(
            "/admin/api/connection-setup", json=tunnel_request(command=KEY), headers=headers
        )
        assert invalid.status_code == 422 and KEY not in invalid.text
        malformed = client.post("/admin/api/connection-setup", json={"method": []}, headers=headers)
        assert malformed.status_code == 422
        service.call.side_effect = SetupBusy
        assert (
            client.post("/admin/api/connection-setup", json=data, headers=headers).status_code
            == 409
        )
        service.call.side_effect = OSError(KEY)
        missing = client.get("/admin/api/connection-setup")
        assert missing.json()["available"] is False and KEY not in missing.text
        failure = client.post("/admin/api/connection-setup", json=data, headers=headers)
        assert failure.status_code == 503 and KEY not in failure.text


def test_jobs_are_serial_idempotent_and_persist_no_credentials(root):
    gate = threading.Event()
    runner = Mock(side_effect=lambda data: (gate.wait(3), {"state": "ready", "message": "done"})[1])
    jobs = setup_agent.Jobs(runner)
    data = tunnel_request()
    try:
        first = jobs.submit(data)
        assert first["state"] == "running"
        assert jobs.submit(data)["id"] == first["id"]
        with pytest.raises(BlockingIOError):
            jobs.submit(request("stdio"))
        assert KEY not in json.dumps(jobs.snapshot())
        assert KEY not in jobs.path.read_text()
        assert jobs.path.stat().st_mode & 0o777 == 0o600
    finally:
        gate.set()
        jobs.thread.join(3)
    assert jobs.snapshot()["job"]["state"] == "ready"
    runner.assert_called_once()
    assert setup_agent.Jobs().snapshot()["job"]["state"] == "ready"
    assert KEY not in jobs.path.read_text()


def test_saved_choice_survives_checks_and_failed_setup(root):
    jobs = setup_agent.Jobs(lambda data: {"state": "ready", "message": "done"})
    jobs.submit(request("stdio"))
    jobs.thread.join(3)
    jobs.submit(request("check"))
    jobs.thread.join(3)
    assert setup_agent.Jobs().snapshot()["preferred_method"] == "stdio"
    jobs.runner = lambda data: {"state": "failed", "message": "failed"}
    jobs.submit(tunnel_request())
    jobs.thread.join(3)
    assert jobs.snapshot()["preferred_method"] == "stdio"
    assert KEY not in (root / ".bridge/connection-preferences.json").read_text()


def test_existing_installation_infers_choice_without_job_history(root):
    cli.env_update({"DOT_PUBLIC_URL": "https://ai.test"})
    assert setup_agent.context()["preferred_method"] == "https"
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1"})
    assert setup_agent.context()["preferred_method"] == "openai-tunnel"


def test_progress_belongs_only_to_its_job_and_uses_safe_messages(root):
    data = tunnel_request()
    setup_agent.progress(data, "tunnel")
    assert setup_agent.current_progress(data["request_id"])["step"] == "tunnel"
    assert setup_agent.current_progress("another-job") == {}
    assert KEY not in (root / ".bridge/web-setup-progress.json").read_text()


def test_job_restart_and_errors_never_expose_keys_or_provider_links(root):
    jobs = setup_agent.Jobs(
        lambda _: {
            "state": "action_required",
            "action_url": "https://login.tailscale.com/a/synthetic",
        }
    )
    jobs.submit(request("tailscale", install_tailscale=True))
    jobs.thread.join(3)
    assert "action_url" in jobs.snapshot()["job"]
    assert "login.tailscale" not in jobs.path.read_text()
    assert setup_agent.Jobs().snapshot()["job"]["state"] == "interrupted"
    jobs.runner = Mock(side_effect=RuntimeError(KEY))
    jobs.submit(tunnel_request())
    jobs.thread.join(3)
    assert jobs.snapshot()["job"]["state"] == "failed"
    assert KEY not in jobs.path.read_text()


def test_tunnel_uses_private_temporary_file_then_explicit_approval(root, monkeypatch):
    paths, calls = [], []

    def configure(identity, path):
        calls.append("configure")
        assert identity == TUNNEL and path.read_text().strip() == KEY
        assert path.stat().st_mode & 0o777 == 0o600
        paths.append(path)

    monkeypatch.setattr(tunnel, "configure", configure)
    approval = Mock(side_effect=lambda *args: calls.append("approve"))
    monkeypatch.setattr(tunnel, "control_call", approval)
    monkeypatch.setattr(tunnel, "status", lambda: {"ready": True})
    monkeypatch.setattr(expose, "expose", Mock(side_effect=AssertionError("no Tailscale")))
    monkeypatch.setattr(access, "connect", Mock(side_effect=AssertionError("no OAuth")))
    assert setup_agent.execute(tunnel_request())["tunnel_ready"]
    assert calls == ["configure", "approve"]
    assert not paths[0].exists()
    approval.assert_called_once_with("/tunnel/decision", {"tunnel_id": TUNNEL, "approve": True})
    cli.atomic(root / "secrets/openai_tunnel_api_key", KEY)
    cli.env_update({"OPENAI_TUNNEL_ID": TUNNEL})
    assert setup_agent.execute(tunnel_request(api_key=""))["state"] == "ready"
    with pytest.raises(ValueError, match="새 터널 ID"):
        setup_agent.execute(tunnel_request(api_key="", tunnel_id="tunnel_" + "b" * 32))
    assert KEY not in json.dumps(setup_agent.context())


def test_failed_tunnel_never_approves_and_removes_temporary_key(root, monkeypatch):
    paths = []

    def fail(identity, path):
        paths.append(path)
        raise RuntimeError(KEY)

    monkeypatch.setattr(tunnel, "configure", fail)
    approval = Mock()
    monkeypatch.setattr(tunnel, "control_call", approval)
    with pytest.raises(RuntimeError):
        setup_agent.execute(tunnel_request())
    assert not paths[0].exists()
    approval.assert_not_called()


def test_oauth_configuration_preserves_admin_origin(root, monkeypatch):
    cli.env_update({"ADMIN_AUTH_MODE": "passkey", "OPENAI_TUNNEL_ENABLED": "1"})
    cli.atomic(root / ".bridge/admin-url", "http://localhost:18789/admin/")
    connect, passkey = Mock(), Mock()
    monkeypatch.setattr(access, "connect", connect)
    monkeypatch.setattr(access, "passkey_setup", passkey)
    setup_agent.execute(request("https", url="https://ai.test"))
    connect.assert_called_once_with("https://ai.test")
    args = passkey.call_args.args[0]
    assert args.url is None and args.public_url == "https://ai.test" and not args.enroll
    assert cli.read_env()["OPENAI_TUNNEL_ENABLED"] == "1"
    assert (root / ".bridge/admin-url").read_text() == "http://localhost:18789/admin/"


def test_stdio_and_skip_do_not_start_network_services(root, monkeypatch):
    monkeypatch.setattr(cli, "run", Mock(side_effect=AssertionError("no commands")))
    for method in ("none", "stdio"):
        assert setup_agent.execute(request(method))["state"] == "ready"
    assert not list(root.iterdir())


@pytest.mark.parametrize("timed_out", [False, True])
def test_tailscale_approval_link_is_returned_without_other_output(monkeypatch, timed_out, capsys):
    link = "https://login.tailscale.com/a/synthetic"
    result = Mock(returncode=1, stdout=link, stderr=KEY)
    run = Mock(return_value=result)
    if timed_out:
        run.side_effect = subprocess.TimeoutExpired(
            "tailscale", 1, output=link.encode(), stderr=KEY.encode()
        )
    monkeypatch.setattr(setup_agent.subprocess, "run", run)
    with pytest.raises(setup_agent.ActionRequired) as error:
        setup_agent.quiet_run(["tailscale", "up"])
    assert error.value.url == link
    assert KEY not in capsys.readouterr().out
    with pytest.raises(RuntimeError):
        setup_agent.quiet_run(["docker", "compose", "up"])


def test_tailscale_setup_runs_on_server_and_respects_existing_route_guard(root, monkeypatch):
    monkeypatch.setattr(expose, "tailscale_binary", lambda: "/usr/bin/tailscale")
    monkeypatch.setattr(onboarding, "network_status", lambda _: {"BackendState": "Running"})
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    publish = Mock(side_effect=RuntimeError("another app"))
    monkeypatch.setattr(expose, "expose", publish)
    oauth = Mock()
    monkeypatch.setattr(setup_agent, "configure_oauth", oauth)
    with pytest.raises(RuntimeError, match="another app"):
        setup_agent.execute(request("tailscale", install_tailscale=True))
    assert publish.call_args.args[0].local is True
    oauth.assert_not_called()
    run.assert_called_once_with(["systemctl", "start", "tailscaled"])


def test_job_main_suppresses_provider_output_and_private_errors(monkeypatch, capsys):
    original_run = cli.run
    monkeypatch.setattr(cli, "run", original_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(tunnel_request())))

    def fail(_):
        print(KEY)
        raise RuntimeError(KEY)

    monkeypatch.setattr(setup_agent, "execute", fail)
    setup_agent.job_main()
    output = capsys.readouterr().out
    assert KEY not in output
    assert json.loads(output)["state"] == "failed"


def test_mac_agent_install_saves_desktop_stdio_without_changing_other_host_network(
    root, monkeypatch
):
    cli.atomic(root / ".bridge/mac.json", json.dumps({"vm": "test-vm", "directory": "/srv/bridge"}))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/limactl")
    run = Mock()
    monkeypatch.setattr(cli, "run", run)
    lima.mac(argparse.Namespace(command="setup-agent", agent_command="install"))
    first, second = run.call_args_list
    data = json.loads(first.kwargs["input"])
    assert data["args"] == [str(root / "bridge"), "mcp"]
    assert first.args[0][-1] == "/srv/bridge/.bridge/stdio-client.json"
    assert second.args[0][-2:] == ["setup-agent", "install"]
    assert all("tailscale" not in part for call in run.call_args_list for part in call.args[0])


def test_systemd_agent_is_private_restarted_and_escapes_installation_paths(root, monkeypatch):
    root = root / 'Bridge $HOME %n "quoted"'
    root.mkdir()
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(setup_agent.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup_agent.shutil, "which", lambda _: "/usr/bin/systemctl")
    original_is_dir = Path.is_dir
    monkeypatch.setattr(
        Path, "is_dir", lambda p: str(p) == "/run/systemd/system" or original_is_dir(p)
    )
    write, run = Mock(), Mock()
    monkeypatch.setattr(cli, "atomic", write)
    monkeypatch.setattr(cli, "run", run)
    setup_agent.install()
    path, content = write.call_args.args
    assert str(path).startswith("/etc/systemd/system/kakaotalk-setup-")
    assert "--local setup-agent serve" in content
    assert "WorkingDirectory=" not in content
    assert '$$HOME %%n \\"quoted\\"' in content
    assert "UMask=0077" in content and "KillMode=control-group" in content
    assert "StandardOutput=null" in content and "StandardError=null" in content
    assert run.call_args_list[-1].args[0] == ["systemctl", "restart", path.name]
    assert (root / ".bridge/setup-agent").stat().st_mode & 0o777 == 0o700


def test_worker_key_goes_to_stdin_and_timeout_kills_descendants(root, monkeypatch):
    child = Mock(pid=123456, returncode=0)
    child.communicate.return_value = ('{"state":"ready"}', None)
    process = Mock()
    process.__enter__ = Mock(return_value=child)
    process.__exit__ = Mock(return_value=False)
    popen = Mock(return_value=process)
    monkeypatch.setattr(setup_agent.subprocess, "Popen", popen)
    assert setup_agent.Jobs.run_child(tunnel_request())["state"] == "ready"
    assert KEY not in json.dumps(popen.call_args.args)
    assert popen.call_args.kwargs["start_new_session"] is True
    assert KEY in child.communicate.call_args.args[0]
    child.communicate.side_effect = [subprocess.TimeoutExpired("worker", 900), ("", None)]
    kill = Mock()
    monkeypatch.setattr(setup_agent.os, "killpg", kill)
    with pytest.raises(subprocess.TimeoutExpired):
        setup_agent.Jobs.run_child(tunnel_request())
    kill.assert_called_once_with(child.pid, setup_agent.signal.SIGKILL)


def test_actual_unix_agent_transport_and_worker(tmp_path, monkeypatch):
    # Short path: macOS Unix socket names are limited to 104 bytes.
    with tempfile.TemporaryDirectory(prefix="ks-", dir="/tmp") as folder:
        root = Path(folder)
        bridge = root / "bridge"
        bridge.write_text(
            "import sys\nfrom pathlib import Path\nfrom ops import cli, setup_agent\n"
            "cli.ROOT=Path(__file__).parent\n"
            "setup_agent.serve() if sys.argv[-1]=='serve' else setup_agent.job_main()\n"
        )
        socket = root / ".bridge/setup-agent/agent.sock"
        monkeypatch.setenv("SETUP_AGENT_SOCKET", str(socket))
        service = subprocess.Popen(
            [sys.executable, str(bridge), "serve"],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if socket.exists():
                    break
                time.sleep(0.02)
            assert socket.stat().st_mode & 0o777 == 0o600
            assert socket.parent.stat().st_mode & 0o777 == 0o700
            client = SetupClient()
            assert client.call()["available"]
            job = client.call("POST", request("stdio"))
            assert job["state"] == "running"
            for _ in range(100):
                snapshot = client.call()
                if snapshot["job"]["state"] != "running":
                    break
                time.sleep(0.02)
            assert snapshot["job"]["state"] == "ready"
            with pytest.raises(OSError):
                client.call("POST", {"method": "shell", "command": "id"})
        finally:
            service.terminate()
            service.wait(timeout=5)
