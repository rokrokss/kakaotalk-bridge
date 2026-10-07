import json
import os
import subprocess
import sys

import pytest

from ops import cli, launcher


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "my bridge"
    root.mkdir()
    (root / "bridge").write_text("import json, sys; print(json.dumps(sys.argv[1:]))")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    return root


def on_path(monkeypatch):
    monkeypatch.setenv("PATH", str(launcher.path().parent) + os.pathsep + os.environ["PATH"])


def run(*arguments, **environment):
    result = subprocess.run(
        [str(launcher.path()), *arguments],
        cwd="/",
        env={**os.environ, **environment},
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_command_runs_this_installation_from_anywhere(installation, monkeypatch):
    on_path(monkeypatch)
    launcher.install()
    assert launcher.path().stat().st_mode & 0o777 == 0o755
    assert run("doctor", "a value") == ["doctor", "a value"]
    assert launcher.client_command() == [str(launcher.path())]


def test_command_finds_a_newer_python_when_the_setup_python_is_gone(
    installation, tmp_path, monkeypatch
):
    on_path(monkeypatch)
    pythons = tmp_path / "pythons"
    pythons.mkdir()
    (pythons / "python3.14").symlink_to(sys.executable)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "removed/python3"))
    launcher.install()
    assert run("up", PATH=f"{pythons}{os.pathsep}/usr/bin:/bin") == ["up"]


@pytest.mark.parametrize("existing", ["another installation", "another program"])
def test_command_serving_something_else_is_left_alone(installation, monkeypatch, capsys, existing):
    on_path(monkeypatch)
    if existing == "another installation":
        monkeypatch.setattr(cli, "ROOT", installation.parent / "other bridge")
        launcher.install()
        monkeypatch.setattr(cli, "ROOT", installation)
    else:
        launcher.path().parent.mkdir(parents=True)
        launcher.path().write_text("#!/bin/sh\necho unrelated\n")
    before = launcher.path().read_text()
    launcher.install()
    assert launcher.path().read_text() == before
    assert "다른 설치를 가리키고 있어 그대로 두었습니다" in capsys.readouterr().out
    assert launcher.client_command() == [sys.executable, str(installation / "bridge")]
    launcher.remove()
    assert launcher.path().read_text() == before


def test_mac_adds_the_command_folder_to_the_shell_profile_once(installation, private_launcher, capsys):
    launcher.install()
    launcher.install()
    profile = (private_launcher / ".zprofile").read_text()
    assert profile.count(launcher.PROFILE_LINE) == 1
    output = capsys.readouterr().out
    assert output.count("PATH로 추가했습니다") == 1
    assert "새 터미널부터 kakaotalk-bridge 명령을 쓸 수 있습니다" in output


def test_other_shells_get_guidance_without_profile_changes(installation, private_launcher, capsys, monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    launcher.install()
    assert not (private_launcher / ".zprofile").exists()
    assert "PATH에 추가하면" in capsys.readouterr().out


def test_linux_command_serves_every_account_without_profile_changes(
    installation, private_launcher, monkeypatch
):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    launcher.install()
    assert launcher.path() == launcher.SYSTEM_BIN / "kakaotalk-bridge"
    assert launcher.serves_this()
    assert not (private_launcher / ".zprofile").exists()


def test_cleanup_removes_only_this_installations_command(installation, monkeypatch):
    on_path(monkeypatch)
    launcher.install()
    launcher.remove()
    assert not launcher.path().exists()
    launcher.remove()


def test_unwritable_command_folder_never_stops_setup(installation, private_launcher, capsys):
    (private_launcher / ".local").mkdir()
    (private_launcher / ".local/bin").write_text("not a folder")
    launcher.install()
    assert "명령을 만들지 못했습니다" in capsys.readouterr().out
