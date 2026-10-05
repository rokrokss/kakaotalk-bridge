import argparse
import json
import stat
from unittest.mock import Mock

import pytest

from ops import cli, onboarding, tunnel
from tests.test_onboarding import options

TUNNEL = "tunnel_" + "a" * 32


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/mcp_storage_key").write_text("installed")
    (tmp_path / ".env").write_text(
        "DOT_PUBLIC_URL=https://existing.test\nADMIN_AUTH_MODE=passkey\n"
    )
    return tmp_path


def test_configure_preserves_public_url_and_never_prints_credentials(home, monkeypatch, capsys):
    execute = Mock(return_value="")
    monkeypatch.setattr(cli, "compose", execute)
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    tunnel.configure(TUNNEL, key)
    assert cli.read_env()["DOT_PUBLIC_URL"] == "https://existing.test"
    assert cli.read_env()["OPENAI_TUNNEL_ID"] == TUNNEL
    secret = (home / "secrets/mcp_tunnel_authorization").read_text()
    assert secret.startswith("Bearer ")
    assert stat.S_IMODE((home / "secrets/openai_tunnel_api_key").stat().st_mode) == 0o444
    assert key.read_text() not in (home / ".env").read_text() + capsys.readouterr().out
    assert secret.strip() not in json.dumps(json.loads((home / ".bridge/tunnel.json").read_text()))
    assert execute.call_args_list[0].args == ("pull", "openai-tunnel")
    assert {"dot-plugin", "dot-control", "dot-ingress", "dot-tunnel", "openai-tunnel"} <= set(
        cli.services()
    )
    tunnel.configure(TUNNEL, key)
    assert (home / "secrets/mcp_tunnel_authorization").read_text() == secret


def test_bad_credentials_and_failed_pull_preserve_configuration(home, monkeypatch):
    execute = Mock()
    monkeypatch.setattr(cli, "compose", execute)
    before = (home / ".env").read_text()
    key = home / "key"
    key.write_text("bad\nheader")
    with pytest.raises(ValueError):
        tunnel.configure(TUNNEL, key)
    execute.assert_not_called()
    key.write_text("sk-" + "x" * 40)
    execute.side_effect = RuntimeError("image unavailable")
    with pytest.raises(RuntimeError):
        tunnel.configure(TUNNEL, key)
    assert (home / ".env").read_text() == before
    assert not (home / "secrets/openai_tunnel_api_key").exists()


def test_failed_start_restores_previous_files_and_restarts_services(home, monkeypatch):
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    before = (home / ".env").read_bytes()
    calls = []

    def execute(*args, **kwargs):
        calls.append(args)
        if "--force-recreate" in args:
            raise RuntimeError("failed to start")
        return ""

    monkeypatch.setattr(cli, "compose", execute)
    with pytest.raises(RuntimeError, match="previous configuration restored"):
        tunnel.configure(TUNNEL, key)
    assert (home / ".env").read_bytes() == before
    assert not (home / "secrets/openai_tunnel_api_key").exists()
    assert not (home / "secrets/mcp_tunnel_authorization").exists()
    assert not (home / ".bridge/tunnel.json").exists()
    assert calls[-1] == ("up", "-d", "--no-build", *cli.services())


def test_invalid_existing_private_credential_stops_before_mutation(home, monkeypatch):
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    (home / "secrets/mcp_tunnel_authorization").write_text("invalid")
    execute = Mock()
    monkeypatch.setattr(cli, "compose", execute)
    with pytest.raises(RuntimeError, match="Restore the existing"):
        tunnel.configure(TUNNEL, key)
    execute.assert_not_called()


def test_failed_key_rotation_restores_old_key_and_recreates_its_mount(home, monkeypatch):
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "OPENAI_TUNNEL_ID": TUNNEL})
    old = "sk-" + "o" * 40
    runtime_key = home / "secrets/openai_tunnel_api_key"
    runtime_key.write_text(old)
    private = home / "secrets/mcp_tunnel_authorization"
    private.write_text("Bearer " + "a" * 43)
    key = home / "key"
    key.write_text("sk-" + "n" * 40)
    recreated = []

    def execute(*args, **kwargs):
        if "--force-recreate" in args:
            recreated.append(runtime_key.read_text().strip())
            if len(recreated) == 1:
                raise RuntimeError("failed rotation")
        return ""

    monkeypatch.setattr(cli, "compose", execute)
    with pytest.raises(RuntimeError, match="previous configuration restored"):
        tunnel.configure(TUNNEL, key)
    assert recreated == [key.read_text(), old]
    assert cli.read_env()["OPENAI_TUNNEL_ENABLED"] == "1"
    assert private.read_text() == "Bearer " + "a" * 43


def test_switch_revoke_and_disable_preserve_oauth(home, monkeypatch):
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "OPENAI_TUNNEL_ID": TUNNEL})
    revoke = Mock()
    monkeypatch.setattr(tunnel, "revoke", revoke)
    monkeypatch.setattr(cli, "compose", Mock())
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    second = "tunnel_" + "b" * 32
    tunnel.configure(second, key)
    revoke.assert_called_once_with(TUNNEL)
    tunnel.run(argparse.Namespace(tunnel_command="disable"))
    assert revoke.call_args.args == (second,)
    assert cli.read_env()["DOT_PUBLIC_URL"] == "https://existing.test"
    assert cli.read_env()["OPENAI_TUNNEL_ENABLED"] == "0"
    assert "openai-tunnel" not in cli.services()
    assert "dot-plugin" in cli.services()
    assert not (home / ".bridge/tunnel.json").exists()


def test_tunnel_onboarding_skips_public_network_and_opens_only_admin(home, monkeypatch):
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    args = options(
        "--connection",
        "openai-tunnel",
        "--admin-url",
        "https://admin.test",
        "--tunnel-id",
        TUNNEL,
        "--api-key-file",
        str(key),
        "--no-browser",
    )
    monkeypatch.setattr(cli, "tailscale_binary", Mock(side_effect=AssertionError("no Tailscale")))
    onboarding.validate(args)
    runtime = Mock()
    runtime.call.return_value = "https://admin.test/admin/"
    onboarding.connect_network(args, runtime)
    assert runtime.call.call_args.args[:2] == ("tunnel", "configure")
    onboarding.open_setup(args, runtime)
    assert runtime.call.call_args.args == (
        "passkey-login",
        "--link-only",
        "--url",
        "https://admin.test",
    )


def test_tunnel_resume_reuses_config_without_credentials_or_funnel(home, monkeypatch):
    (home / ".bridge").mkdir()
    (home / ".bridge/tunnel.json").write_text(json.dumps({"tunnel_id": TUNNEL}))
    (home / ".bridge/admin-url").write_text("https://admin.test/admin/")
    args = options()
    onboarding.validate(args)
    assert args.connection == "openai-tunnel"
    assert args.admin_url == "https://admin.test"
    runtime = Mock()
    onboarding.connect_network(args, runtime)
    runtime.call.assert_not_called()


def test_restored_tunnel_uses_env_when_local_marker_is_absent(home):
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "OPENAI_TUNNEL_ID": TUNNEL})
    args = options()
    onboarding.validate(args)
    assert args.connection == "openai-tunnel"
    runtime = Mock()
    onboarding.connect_network(args, runtime)
    runtime.call.assert_not_called()


def test_status_redacts_probe_errors(home, monkeypatch):
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "OPENAI_TUNNEL_ID": TUNNEL})
    monkeypatch.setattr(cli, "compose", Mock(side_effect=RuntimeError("private details")))
    assert tunnel.status() == {"configured": True, "tunnel_id": TUNNEL, "ready": False}


def test_tunnel_admin_decision_requires_session_csrf_and_origin():
    from fastapi.testclient import TestClient

    from tests.test_webui import ORIGIN, TOKEN, signin
    from webui.app import create_app

    connections = Mock()
    connections.call.return_value = {"ok": True}
    app = create_app(TOKEN, Mock(), dict, connections=connections, auth_mode="local")
    with TestClient(app, base_url=ORIGIN) as client:
        path, body = "/admin/api/tunnel/decision", {"tunnel_id": TUNNEL, "approve": True}
        assert client.post(path, json=body, headers={"Origin": ORIGIN}).status_code == 401
        headers = signin(client)
        assert client.post(path, json=body, headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.post(
                path, json=body, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        connections.call.assert_not_called()
        assert client.post(path, json=body, headers=headers).status_code == 200
        connections.call.assert_called_once_with("POST", "/tunnel/decision", body)


def test_tunnel_only_needs_no_public_ingress_but_keeps_old_https_admin(home):
    cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "DOT_PUBLIC_URL": "https://a.invalid"})
    assert "dot-ingress" not in cli.services()
    cli.atomic(home / ".bridge/admin-url", "https://private-admin.test/admin/")
    assert "dot-ingress" in cli.services()
    cli.atomic(home / ".bridge/admin-url", "http://localhost:18789/admin/")
    assert "dot-ingress" not in cli.services()


def test_fresh_tunnel_setup_does_not_require_an_admin_proxy(home):
    key = home / "key"
    key.write_text("sk-" + "x" * 40)
    args = options(
        "--connection", "openai-tunnel", "--tunnel-id", TUNNEL, "--api-key-file", str(key)
    )
    onboarding.validate(args)
    assert args.admin_url is None
