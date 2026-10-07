import argparse
import hashlib
import io
import json
import os
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from ops import cli, onboarding, releases, setup_output

SOURCE = (Path(__file__).resolve().parents[1] / "ops/source.py").read_text()


def manifest(version="v0.1.0"):
    return {
        "schema": 1,
        "version": version,
        "images": {
            kind: f"ghcr.io/{releases.REPOSITORY}-{kind}@sha256:" + "a" * 64
            for kind in ("server", "device", "gateway")
        },
    }


def bundle(files=None):
    files = files or {
        "bridge": "# release launcher",
        "ops/cli.py": "# release cli",
        "ops/source.py": SOURCE,
        "compose.yaml": "services: {}",
        "release.json": json.dumps(manifest()),
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in files.items():
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o755 if name == "bridge" else 0o644
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def fake_download(monkeypatch, content=None, **changes):
    content = content or bundle()
    url = f"https://github.com/{releases.REPOSITORY}/releases/download/v0.1.0/{releases.ASSET}"
    data = {
        "tag_name": "v0.1.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": releases.ASSET,
                "browser_download_url": url,
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    data.update(changes)
    calls = []

    def request(address):
        calls.append(address)
        response = io.BytesIO(json.dumps(data).encode() if "api.github.com" in address else content)
        response.url = address
        return response

    monkeypatch.setattr(releases, "request", request)
    return data, calls


def test_release_download_validates_and_installs_matching_bundle(tmp_path, monkeypatch):
    _, calls = fake_download(monkeypatch)
    target = tmp_path / "a path" / "bridge"
    assert releases.download(target) == "v0.1.0"
    assert json.loads((target / "release.json").read_text()) == manifest()
    assert (target / "bridge").stat().st_mode & 0o111
    assert calls[0].endswith("/releases/latest")
    assert len(calls) == 2


def test_release_checksum_failure_never_installs_or_falls_back(tmp_path, monkeypatch):
    data, calls = fake_download(monkeypatch)
    data["assets"][0]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="체크섬이 일치하지 않아"):
        releases.download(tmp_path / "bridge")
    assert not list(tmp_path.iterdir())
    assert len(calls) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("digest", None),
        ("browser_download_url", "https://example.test/install.tar.gz"),
    ],
)
def test_download_requires_github_digest_and_official_asset_url(
    tmp_path, monkeypatch, field, value
):
    data, calls = fake_download(monkeypatch)
    data["assets"][0][field] = value
    with pytest.raises(ValueError):
        releases.download(tmp_path / "bridge")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "main"},
        {"assets": []},
    ],
)
def test_invalid_release_is_rejected_before_download(tmp_path, monkeypatch, change):
    _, calls = fake_download(monkeypatch, **change)
    with pytest.raises(ValueError):
        releases.download(tmp_path / "bridge")
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["../escape", "/escape", "secrets/key", ".env", "ops/.env.local"])
def test_unsafe_archive_is_rejected_before_extraction(tmp_path, name):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(bundle({name: "private"}))
    with pytest.raises(ValueError, match="허용되지 않는 경로"):
        releases.extract(archive, tmp_path / "incoming")
    assert not (tmp_path / "incoming").exists()


def test_bundle_manifest_must_match_release_tag(tmp_path, monkeypatch):
    fake_download(
        monkeypatch,
        bundle(
            {
                "bridge": "",
                "ops/cli.py": "",
                "compose.yaml": "",
                "release.json": json.dumps(manifest("v0.2.0")),
            }
        ),
    )
    with pytest.raises(ValueError, match="버전이 서로 다릅니다"):
        releases.download(tmp_path / "bridge")
    assert not list(tmp_path.iterdir())


def test_existing_installation_is_preserved_without_network(tmp_path, monkeypatch):
    network = Mock(side_effect=AssertionError("must not download"))
    monkeypatch.setattr(releases, "request", network)
    (tmp_path / "identity").write_text("keep")
    with pytest.raises(RuntimeError, match="그대로 두었습니다"):
        releases.download(tmp_path)
    assert (tmp_path / "identity").read_text() == "keep"
    network.assert_not_called()


def test_default_onboarding_uses_bundled_images_and_never_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(onboarding.platform, "system", lambda: "Linux")
    monkeypatch.setattr(onboarding, "prepare_linux", Mock())
    monkeypatch.setattr(onboarding, "connect_network", Mock())
    opened = Mock()
    monkeypatch.setattr(onboarding, "open_setup", opened)
    runtime = Mock()
    runtime.installed.return_value = False
    monkeypatch.setattr(onboarding, "Runtime", lambda: runtime)
    parser = argparse.ArgumentParser()
    onboarding.add_arguments(parser)
    (tmp_path / "release.json").write_text(json.dumps(manifest()))
    onboarding.up(parser.parse_args([]))
    call = runtime.call.call_args_list[0].args
    assert call[:3] == ("install", "--manifest", str(tmp_path / "release.json"))
    assert "--source" not in call


@pytest.mark.parametrize("ssh", [False, True])
def test_headless_and_ssh_never_launch_a_host_browser(tmp_path, monkeypatch, ssh):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(onboarding.platform, "system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    if ssh:
        monkeypatch.setenv("SSH_CONNECTION", "client port server port")
        monkeypatch.setenv("DISPLAY", ":10")
    else:
        monkeypatch.delenv("SSH_CONNECTION", raising=False)
    parser = argparse.ArgumentParser()
    onboarding.add_arguments(parser)
    args = parser.parse_args([])
    onboarding.validate(args)
    runtime = Mock()
    runtime.call.return_value = "http://localhost:18789/admin/"
    opened = Mock()
    monkeypatch.setattr(onboarding.webbrowser, "open", opened)
    onboarding.open_setup(args, runtime)
    opened.assert_not_called()


@pytest.mark.parametrize("failed", [False, True])
def test_upgrade_switches_source_and_restores_it_on_update_failure(tmp_path, monkeypatch, failed):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(releases.os, "geteuid", lambda: 0)
    monkeypatch.setattr(releases, "vm_missing", lambda root: False)
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/cli.py").write_text("old code")
    (tmp_path / "bridge").write_text("old launcher")
    (tmp_path / "compose.yaml").write_text("old compose")
    (tmp_path / "release.json").write_text("old release")
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/installed").write_text("1")
    (tmp_path / ".bridge/mac.json").write_text("{}")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/identity").write_text("keep me")
    fake_download(monkeypatch)
    commands = []

    def run(command):
        commands.append(command[2])
        if command[2] == "update":
            assert (tmp_path / "ops/cli.py").read_text() == "# release cli"
            if failed:
                raise RuntimeError("failed health check")
        if command[2] == "start":
            assert (tmp_path / "ops/cli.py").read_text() == "old code"

    monkeypatch.setattr(setup_output, "run", run)
    if failed:
        with pytest.raises(RuntimeError, match="health check"):
            releases.upgrade(argparse.Namespace(version="latest"))
        assert commands == ["update", "start"]
        assert (tmp_path / "release.json").read_text() == "old release"
    else:
        releases.upgrade(argparse.Namespace(version="latest"))
        assert commands == ["update", "setup-agent"]
        assert (tmp_path / ".bridge/previous-source/ops/cli.py").read_text() == "old code"
    assert (tmp_path / "secrets/identity").read_text() == "keep me"
    assert not (tmp_path / ".bridge/source-journal.json").exists()


def test_upgrade_current_release_preserves_code_and_never_redeploys(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(releases.os, "geteuid", lambda: 0)
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/installed").write_text("1")
    (tmp_path / ".bridge/mac.json").write_text("{}")
    (tmp_path / "release.json").write_text(json.dumps(manifest()))
    (tmp_path / "bridge").write_text("existing launcher")
    (tmp_path / ".env").write_text("existing settings")
    fake_download(monkeypatch)
    run = Mock(side_effect=AssertionError("same release must not back up or redeploy"))
    monkeypatch.setattr(setup_output, "run", run)

    releases.upgrade(argparse.Namespace(version="latest"))

    run.assert_not_called()
    assert (tmp_path / "bridge").read_text() == "existing launcher"
    assert (tmp_path / ".env").read_text() == "existing settings"
    assert "이미 v0.1.0 릴리스를 사용하고 있습니다." in capsys.readouterr().out
    assert not (tmp_path / ".bridge/previous-source").exists()


def source_bundle(top="kakaotalk-bridge-v0.1.0"):
    return bundle(
        {
            f"{top}/bridge": "# source launcher",
            f"{top}/ops/cli.py": "# source cli",
            f"{top}/ops/source.py": SOURCE,
            f"{top}/compose.yaml": "services: {}",
            f"{top}/.env.example": "COMPOSE_PROJECT_NAME=kakaotalk-bridge",
        }
    )


def test_source_download_follows_the_latest_release_tag_and_records_it(tmp_path, monkeypatch):
    _, calls = fake_download(monkeypatch, source_bundle())
    target = tmp_path / "source bridge"
    assert releases.download(target, source=True) == "v0.1.0"
    assert calls == [
        f"https://api.github.com/repos/{releases.REPOSITORY}/releases/latest",
        f"https://codeload.github.com/{releases.REPOSITORY}/tar.gz/v0.1.0",
    ]
    assert (target / "ops/cli.py").read_text() == "# source cli"
    assert json.loads((target / releases.SOURCE_RECORD).read_text()) == {"version": "v0.1.0"}
    assert not (target / "release.json").exists()


def test_named_source_ref_skips_the_release_lookup(tmp_path, monkeypatch):
    _, calls = fake_download(monkeypatch, source_bundle("kakaotalk-bridge-main"))
    releases.download(tmp_path / "bridge", "main", source=True)
    assert calls == [f"https://codeload.github.com/{releases.REPOSITORY}/tar.gz/main"]


def test_installations_are_classified_by_their_own_markers(tmp_path):
    assert releases.channel(tmp_path) == "source"
    (tmp_path / "release.json").write_text("{}")
    assert releases.channel(tmp_path) == "release"
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    assert releases.channel(tmp_path) == "git"


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["--plan"], True),
        (["--pla"], True),
        (["--pl"], True),
        (["--so"], True),
        (["--manifest=release.json"], True),
        (["--manifest", "release.json"], True),
        (["-h"], True),
        (["--hel"], True),
        (["--p"], False),
        ([], False),
        (["--no-browser"], False),
        (["--admin-port", "80"], False),
        (["--apk-folder", "/a path/apks"], False),
    ],
)
def test_setup_modes_and_help_run_the_installation_as_is(arguments, expected):
    assert releases.as_is(arguments) is expected


def installed_source(root):
    (root / "bridge").write_text("old launcher")
    (root / "ops").mkdir()
    (root / "ops/cli.py").write_text("old code")
    (root / "compose.yaml").write_text("old compose")
    (root / ".bridge").mkdir()
    (root / ".bridge/installed").write_text("1")
    (root / "secrets").mkdir()
    (root / "secrets/bridge.jks").write_text("personal key")


def recorder(root, fail=None):
    calls = []

    def bridge(*arguments, quiet=False):
        calls.append(arguments)
        # Everything after the swap must run the new code, never the installed one.
        assert (root / "ops/cli.py").read_text() != "old code" or arguments == ("start",)
        if arguments[0] == fail:
            raise RuntimeError(f"{fail} failed")

    return bridge, calls


def test_source_installation_rebuilds_the_latest_release_source_once(tmp_path, monkeypatch, capsys):
    installed_source(tmp_path)
    monkeypatch.setattr(releases, "vm_missing", lambda root: False)
    fake_download(monkeypatch, source_bundle())
    bridge, calls = recorder(tmp_path)

    assert releases.upgrade_installation(tmp_path, bridge=bridge, plan=["--no-browser"])
    assert calls == [
        ("up", "--plan", "--no-browser"),
        ("update", "--source"),
        ("setup-agent", "install"),
    ]
    assert (tmp_path / "ops/cli.py").read_text() == "# source cli"
    assert (tmp_path / "secrets/bridge.jks").read_text() == "personal key"
    assert json.loads((tmp_path / releases.SOURCE_RECORD).read_text()) == {"version": "v0.1.0"}

    calls.clear()
    assert not releases.upgrade_installation(tmp_path, bridge=bridge)
    assert calls == []
    assert "이미 v0.1.0 소스를 사용하고 있습니다." in capsys.readouterr().out


def test_named_branches_are_never_already_current(tmp_path):
    releases.record_source(tmp_path, "main")
    assert not releases.current(tmp_path, "source", tmp_path, "main")
    releases.record_source(tmp_path, "v0.1.0")
    assert releases.current(tmp_path, "source", tmp_path, "v0.1.0")


def test_invalid_setup_options_restore_the_code_before_any_service_changes(tmp_path, monkeypatch):
    installed_source(tmp_path)
    monkeypatch.setattr(releases, "vm_missing", lambda root: False)
    fake_download(monkeypatch, source_bundle())
    bridge, calls = recorder(tmp_path, fail="up")
    with pytest.raises(RuntimeError, match="up failed"):
        releases.upgrade_installation(tmp_path, bridge=bridge, plan=["--admin-port", "80"])
    assert calls == [("up", "--plan", "--admin-port", "80")]
    assert (tmp_path / "ops/cli.py").read_text() == "old code"
    assert not (tmp_path / releases.SOURCE_RECORD).exists()


def test_missing_vm_takes_new_code_and_leaves_recreation_to_setup(tmp_path, monkeypatch):
    installed_source(tmp_path)
    monkeypatch.setattr(releases, "vm_missing", lambda root: True)
    fake_download(monkeypatch, source_bundle())
    bridge, calls = recorder(tmp_path)
    assert releases.upgrade_installation(tmp_path, bridge=bridge, plan=[])
    assert calls == [("up", "--plan")]
    assert (tmp_path / "ops/cli.py").read_text() == "# source cli"
    assert not (tmp_path / ".bridge/source-journal.json").exists()


def test_git_checkouts_are_never_upgraded(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(RuntimeError, match="git pull"):
        releases.upgrade_installation(tmp_path, bridge=Mock())


@pytest.mark.parametrize("names,missing", [("bridge-vm\nother\n", False), ("other\n", True)])
def test_vm_check_reads_the_configured_lima_instance(tmp_path, monkeypatch, names, missing):
    monkeypatch.setenv("PATH", os.environ["PATH"])  # vm_missing extends PATH
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/mac.json").write_text('{"vm": "bridge-vm"}')
    monkeypatch.setattr(releases.sys, "platform", "darwin")
    monkeypatch.setattr(releases.subprocess, "run", Mock(return_value=Mock(stdout=names)))
    assert releases.vm_missing(tmp_path) is missing


def test_lima_failure_stops_instead_of_guessing_the_vm_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.environ["PATH"])  # vm_missing extends PATH
    (tmp_path / ".bridge").mkdir()
    (tmp_path / ".bridge/mac.json").write_text('{"vm": "bridge-vm"}')
    monkeypatch.setattr(releases.sys, "platform", "darwin")
    monkeypatch.setattr(releases.subprocess, "run", Mock(side_effect=FileNotFoundError("limactl")))
    with pytest.raises(RuntimeError, match="Lima VM 상태를 확인하지 못해"):
        releases.vm_missing(tmp_path)
