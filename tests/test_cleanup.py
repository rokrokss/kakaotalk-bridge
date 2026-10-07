import argparse
import hashlib
import json
from unittest.mock import Mock

import pytest

from ops import cleanup, cli, expose


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "install"
    for folder in ("ops", ".bridge", "secrets", "backups"):
        (root / folder).mkdir(parents=True)
    (root / "bridge").write_text("")
    (root / "backups/old.kcs").write_text("")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cleanup.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(expose, "tailscale_binary", lambda: None)
    return root


def test_linux_removes_only_this_installation(root, tmp_path, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    (root / ".env").write_text("COMPOSE_PROJECT_NAME=kakaotalk-bridge\n")
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    unit = "kakaotalk-setup-" + hashlib.sha256(str(root).encode()).hexdigest()[:12] + ".service"
    (systemd / unit).write_text("")
    (systemd / "kakaotalk-setup-000000000000.service").write_text("")
    monkeypatch.setattr(cleanup, "SYSTEMD", systemd)
    ours, edited = tmp_path / "modules.conf", tmp_path / "modprobe.conf"
    ours.write_text("binder_linux\n")
    edited.write_text("options binder_linux devices=binder\n")
    monkeypatch.setattr(
        cleanup,
        "BINDER_CONFIG",
        {ours: "binder_linux\n", edited: "options binder_linux devices=binder,hwbinder,vndbinder\n"},
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "ps", "-aq"]:
            return "c1\nc2"
        if command[:3] == ["docker", "volume", "ls"]:
            return (
                "kakaotalk-bridge_android-data\n"
                "kakaotalk-bridge_restore-0123456789ab_android-data\n"
                "restore-0123456789ab-scratch\n"
                "kakaotalk-bridge-smoke-1_android-data\n"
                "other_data"
            )
        if command[:3] == ["docker", "network", "ls"]:
            return "n1"
        if command[:3] == ["docker", "image", "ls"]:
            # Without --digests, Docker leaves the digest of digest-only release images empty.
            assert "--digests" in command
            return (
                "ghcr.io/rokrokss/kakaotalk-bridge-server <none> sha256:aaa\n"
                "kakaotalk-bridge/server local-0123 <none>\n"
                "redroid/redroid <none> sha256:bbb\n"
                "ghcr.io/openai/tunnel-client v0.0.15 sha256:ccc\n"
                "python 3.12-slim-bookworm sha256:ddd"
            )
        if command == ["docker", "image", "rm", "redroid/redroid@sha256:bbb"]:
            raise RuntimeError("Command failed: docker (exit 1)")
        return ""

    monkeypatch.setattr(cli, "run", run)
    cleanup.cleanup(argparse.Namespace(local=False, yes=True))
    disable = ["systemctl", "disable", "--now", unit]
    project = ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=kakaotalk-bridge"]
    assert calls.index(disable) < calls.index(project)
    assert [path.name for path in systemd.iterdir()] == ["kakaotalk-setup-000000000000.service"]
    assert ["docker", "rm", "-f", "c1", "c2"] in calls
    assert [
        "docker",
        "volume",
        "rm",
        "kakaotalk-bridge_android-data",
        "kakaotalk-bridge_restore-0123456789ab_android-data",
        "restore-0123456789ab-scratch",
    ] in calls
    assert ["docker", "network", "rm", "n1"] in calls
    assert [command[-1] for command in calls if command[:3] == ["docker", "image", "rm"]] == [
        "ghcr.io/rokrokss/kakaotalk-bridge-server@sha256:aaa",
        "kakaotalk-bridge/server:local-0123",
        "redroid/redroid@sha256:bbb",
        "ghcr.io/openai/tunnel-client:v0.0.15",
    ]
    assert not ours.exists() and edited.exists()
    assert not root.exists()


def test_git_checkout_keeps_source_code(root, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    (root / ".git").mkdir()
    (root / ".env").write_text("COMPOSE_PROJECT_NAME=kakaotalk-bridge\n")
    monkeypatch.setattr(cleanup, "SYSTEMD", root / "missing")
    monkeypatch.setattr(cleanup, "BINDER_CONFIG", {})
    monkeypatch.setattr(cli, "run", lambda command, **kwargs: "")
    cleanup.cleanup(argparse.Namespace(local=False, yes=True))
    assert sorted(path.name for path in root.iterdir()) == [".git", "bridge", "ops"]


@pytest.mark.parametrize("owned", [True, False])
def test_mac_deletes_vm_and_only_the_funnel_it_set(root, monkeypatch, capsys, owned):
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(expose, "tailscale_binary", lambda: "tailscale")
    (root / ".bridge/mac.json").write_text(json.dumps({"vm": "bridge-vm"}))
    config = {"Web": {"host.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:18787"}}}}}
    (root / ".bridge/expose.json").write_text(json.dumps({"hostname": "host.ts.net", "config": config}))
    current = config if owned else {**config, "TCP": {"22": {"TCPForward": "127.0.0.1:22"}}}
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["serve", "status"]:
            return json.dumps(current)
        if command[:2] == ["limactl", "list"]:
            return "default\nbridge-vm"
        return ""

    monkeypatch.setattr(cli, "run", run)
    cleanup.cleanup(argparse.Namespace(local=False, yes=True))
    assert "Lima VM(bridge-vm)" in capsys.readouterr().out
    assert (["tailscale", "serve", "reset"] in calls) is owned
    assert ["limactl", "delete", "--force", "bridge-vm"] in calls
    assert not any(command[0] in {"docker", "systemctl"} for command in calls)
    assert not root.exists()


def test_mac_checkout_without_managed_vm_keeps_source(root, monkeypatch, capsys):
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    (root / ".git").mkdir()
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: pytest.fail("no command expected"))
    cleanup.cleanup(argparse.Namespace(local=False, yes=True))
    assert "Lima VM" not in capsys.readouterr().out.split("KakaoTalk Bridge를 삭제했습니다.")[0]
    assert sorted(path.name for path in root.iterdir()) == [".git", "bridge", "ops"]


def test_stopped_tailscale_does_not_block_removal(root, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(expose, "tailscale_binary", lambda: "tailscale")
    (root / ".bridge/expose.json").write_text(json.dumps({"hostname": "h.ts.net", "config": {}}))

    def run(command, **kwargs):
        raise RuntimeError("Command failed: tailscale (exit 1)")

    monkeypatch.setattr(cli, "run", run)
    cleanup.cleanup(argparse.Namespace(local=False, yes=True))
    assert not root.exists()


def test_nothing_is_removed_without_confirmation(root, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli, "run", lambda *args, **kwargs: pytest.fail("ran before confirmation"))
    args = argparse.Namespace(local=False, yes=False)
    monkeypatch.setattr(cleanup.sys, "stdin", Mock(isatty=lambda: False))
    with pytest.raises(RuntimeError, match="--yes"):
        cleanup.cleanup(args)
    monkeypatch.setattr(cleanup.sys, "stdin", Mock(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: "아니요")
    with pytest.raises(SystemExit):
        cleanup.cleanup(args)
    assert (root / "backups/old.kcs").exists()
