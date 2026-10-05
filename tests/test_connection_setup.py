import argparse
from pathlib import Path
from unittest.mock import Mock

import pytest

from ops import cli, connections, onboarding


def options(*args):
    parser = argparse.ArgumentParser()
    connections.add_arguments(parser)
    return parser.parse_args(args)


def test_skip_and_stdio_never_call_providers(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        onboarding, "Runtime", Mock(side_effect=AssertionError("no runtime needed"))
    )
    connections.setup(options("--method", "none"))
    connections.setup(options("--method", "stdio"))
    output = capsys.readouterr().out
    assert str(tmp_path / "bridge") in output
    assert '"mcp"' in output
    assert not list(tmp_path.iterdir())


def test_noninteractive_setup_requires_explicit_choice(monkeypatch):
    monkeypatch.setattr(connections.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="--method"):
        connections.setup(options())


def test_https_wizard_automates_consent_without_changing_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    cli.atomic(tmp_path / ".bridge/admin-url", "http://localhost:18789/admin/")
    runtime = Mock()
    runtime.call.return_value = "http://localhost:18789/admin/"
    monkeypatch.setattr(onboarding, "Runtime", lambda: runtime)
    monkeypatch.setattr(cli, "tailscale_binary", Mock(side_effect=AssertionError("no Tailscale")))
    connections.setup(options("--method", "https", "--url", "https://ai.test", "--no-browser"))
    assert runtime.call.call_args_list[1].args == ("connect", "--url", "https://ai.test")
    assert runtime.call.call_args_list[2].args == (
        "passkey-login",
        "--link-only",
        "--public-url",
        "https://ai.test",
    )
    assert (tmp_path / ".bridge/admin-url").read_text() == "http://localhost:18789/admin/"


def test_tunnel_wizard_hides_and_removes_temporary_runtime_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(connections.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(connections.getpass, "getpass", lambda _: "sk-" + "x" * 40)
    identity = "tunnel_" + "a" * 32
    paths = []

    def call(*args, **kwargs):
        if args[0] == "tunnel":
            path = Path(args[-1])
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.read_text().strip() == "sk-" + "x" * 40
            paths.append(path)
        return "http://localhost:18789/admin/"

    runtime = Mock()
    runtime.call.side_effect = call
    monkeypatch.setattr(onboarding, "Runtime", lambda: runtime)
    connections.setup(options("--method", "openai-tunnel", "--tunnel-id", identity, "--no-browser"))
    assert paths and not paths[0].exists()
    assert "sk-" + "x" * 40 not in capsys.readouterr().out
    assert all(call.args[0] not in {"connect", "expose"} for call in runtime.call.call_args_list)
