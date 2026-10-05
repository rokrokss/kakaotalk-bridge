import argparse
import hashlib
import io
import json
import tarfile
from unittest.mock import Mock

import pytest

from ops import cli, onboarding, releases, setup_output


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
    with pytest.raises(ValueError, match="checksum mismatch"):
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
    with pytest.raises(ValueError, match="Unsafe"):
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
    with pytest.raises(ValueError, match="versions differ"):
        releases.download(tmp_path / "bridge")
    assert not list(tmp_path.iterdir())


def test_existing_installation_is_preserved_without_network(tmp_path, monkeypatch):
    network = Mock(side_effect=AssertionError("must not download"))
    monkeypatch.setattr(releases, "request", network)
    (tmp_path / "identity").write_text("keep")
    with pytest.raises(RuntimeError, match="preserved"):
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
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops/cli.py").write_text("old code")
    (tmp_path / "bridge").write_text("old launcher")
    (tmp_path / "compose.yaml").write_text("old compose")
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
        assert not (tmp_path / "release.json").exists()
    else:
        releases.upgrade(argparse.Namespace(version="latest"))
        assert commands == ["update", "setup-agent"]
        assert (tmp_path / ".bridge/previous-source/ops/cli.py").read_text() == "old code"
    assert (tmp_path / "secrets/identity").read_text() == "keep me"
    assert not (tmp_path / ".bridge/source-journal.json").exists()
