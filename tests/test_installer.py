import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "existing bridge"
    root.mkdir()
    shutil.copytree(ROOT / "ops", root / "ops", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "install.sh", root / "install.sh")
    (root / "release.json").write_text('{"version":"v0.1.0"}')
    state = root / ".bridge"
    state.mkdir()
    (state / "installed").write_text("1")
    (state / "mac.json").write_text('{"vm":"existing-vm"}')
    (state / "onboarding.json").write_text('{"state":"ready"}')
    (root / ".env").write_text("KEEP=original\n")
    (root / "secrets").mkdir()
    (root / "secrets/identity").write_text("existing identity")
    binaries = root / "test-bin"
    binaries.mkdir()
    lima = binaries / "limactl"
    lima.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "assert sys.argv[1:] == ['list', '--format', '{{.Name}}'], sys.argv\n"
        "status = int(os.environ.get('BRIDGE_TEST_LIMA_EXIT', '0'))\n"
        "if status: sys.exit(status)\n"
        "print(os.environ.get('BRIDGE_TEST_VM_NAMES', 'existing-vm'))\n"
    )
    lima.chmod(0o755)
    qemu = binaries / "qemu-system-x86_64"
    qemu.write_text("#!/bin/sh\nexit 1\n")
    qemu.chmod(0o755)
    # Linux installs re-run through sudo, which resets the test environment. Run as
    # root here; test_onboarding covers the elevation itself.
    user = binaries / "id"
    user.write_text("#!/bin/sh\necho 0\n")
    user.chmod(0o755)
    # A stand-in for the installed CLI: record subprocess boundaries and replace
    # the entry point on upgrade, so the final up must execute the new version.
    (root / "bridge").write_text('''\
import json
import os
import sys
from pathlib import Path

generation = "old"
root = Path(__file__).parent
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps([generation, sys.argv[1:]]) + "\\n")
if sys.argv[1] == "upgrade":
    assert sys.stdin.read() == "", "installer input leaked into upgrade"
    status = int(os.environ.get("BRIDGE_TEST_UPGRADE_EXIT", "0"))
    if status:
        sys.exit(status)
    entry = root / "bridge"
    entry.write_text(entry.read_text().replace('generation = "old"', 'generation = "new"'))
elif sys.argv[1] == "install":
    sys.exit(int(os.environ.get("BRIDGE_TEST_INSTALL_EXIT", "0")))
elif "--plan" in sys.argv:
    sys.exit(int(os.environ.get("BRIDGE_TEST_PLAN_EXIT", "0")))
''')
    return root


def run_installer(root, *arguments, local=False, **environment):
    env = {**os.environ, **environment}
    env.pop("BRIDGE_HOME", None)
    env.pop("BRIDGE_VERSION", None)
    env.update(environment)
    env["PATH"] = str(root / "test-bin") + os.pathsep + env["PATH"]
    if local:
        command = ["/bin/bash", str(root / "install.sh"), *arguments]
        content = None
    else:
        command = ["/bin/bash", "-s", "--", *arguments]
        content = (ROOT / "install.sh").read_text()
        env["BRIDGE_HOME"] = str(root)
    result = subprocess.run(
        command,
        input=content,
        env=env,
        text=True,
        capture_output=True,
        start_new_session=True,
        timeout=10,
        check=False,
    )
    log = root / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert (root / ".env").read_text() == "KEEP=original\n"
    assert (root / "secrets/identity").read_text() == "existing identity"
    return result, calls


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("version", [None, "v0.2.0"])
def test_rerun_upgrades_then_launches_new_cli(installation, local, version):
    flags = ["--no-browser", "--vm", "existing-vm", "--admin-port", "19443"]
    environment = {"BRIDGE_VERSION": version} if version else {}
    result, calls = run_installer(installation, *flags, local=local, **environment)
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["old", ["up", "--plan", *flags]],
        ["old", ["upgrade", "--version", version or "latest"]],
        ["new", ["up", *flags]],
    ]
    assert "릴리스 업데이트 확인 중" in result.stdout


@pytest.mark.parametrize(
    "flags",
    [["--plan"], ["--pla"], ["--source"], ["--manifest", "custom.json"]],
)
def test_explicit_setup_modes_do_not_upgrade(installation, flags):
    result, calls = run_installer(installation, *flags)
    assert result.returncode == 0, result.stderr
    assert calls == [["old", ["up", *flags]]]


@pytest.mark.parametrize(
    "state",
    ["downloaded", "running", "interrupted", "source", "git", "damaged-progress", "null-progress"],
)
def test_incomplete_and_source_installations_resume_without_upgrade(installation, state):
    if state == "downloaded":
        (installation / ".bridge/installed").unlink()
        (installation / ".bridge/mac.json").unlink()
    elif state == "source":
        (installation / "release.json").unlink()
    elif state == "git":
        (installation / ".git").write_text("gitdir: /some/worktree")
    else:
        progress = {
            "damaged-progress": "invalid json",
            "null-progress": "null",
        }.get(state, json.dumps({"state": state}))
        (installation / ".bridge/onboarding.json").write_text(progress)
    result, calls = run_installer(installation, "--no-browser")
    assert result.returncode == 0, result.stderr
    expected = [["old", ["up", "--no-browser"]]]
    if sys.platform == "darwin" and state not in {"downloaded", "source", "git"}:
        expected.insert(0, ["old", ["up", "--plan", "--no-browser"]])
    assert calls == expected


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac bootstrap recovery")
@pytest.mark.parametrize("progress", ["ready", "interrupted", None])
def test_missing_mac_vm_uses_template_install_before_published_up(installation, progress):
    state = installation / ".bridge/onboarding.json"
    if progress is None:
        state.unlink()
    else:
        state.write_text(json.dumps({"state": progress}))
    result, calls = run_installer(
        installation, "--no-browser", BRIDGE_TEST_VM_NAMES="unrelated-vm"
    )
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["old", ["up", "--plan", "--no-browser"]],
        ["old", ["install", "--manifest", str(installation / "release.json")]],
        ["old", ["up", "--no-browser"]],
    ]
    assert "기존 VM이 없어 Bridge 템플릿으로 다시 준비합니다." in result.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac bootstrap recovery")
@pytest.mark.parametrize("failure", ["BRIDGE_TEST_INSTALL_EXIT", "BRIDGE_TEST_LIMA_EXIT"])
def test_failed_mac_vm_recovery_does_not_run_published_up(installation, failure):
    result, calls = run_installer(
        installation, "--no-browser", BRIDGE_TEST_VM_NAMES="", **{failure: "23"}
    )
    assert result.returncode == 23
    assert calls[0] == ["old", ["up", "--plan", "--no-browser"]]
    assert all(command[0] == "install" for _, command in calls[1:])


def test_upgrade_failure_stops_before_opening_setup(installation):
    result, calls = run_installer(installation, "--no-browser", BRIDGE_TEST_UPGRADE_EXIT="23")
    assert result.returncode == 23
    assert calls == [
        ["old", ["up", "--plan", "--no-browser"]],
        ["old", ["upgrade", "--version", "latest"]],
    ]


def test_invalid_setup_options_stop_before_upgrade(installation):
    result, calls = run_installer(installation, "--admin-port", "80", BRIDGE_TEST_PLAN_EXIT="2")
    assert result.returncode == 2
    assert calls == [["old", ["up", "--plan", "--admin-port", "80"]]]


@pytest.mark.parametrize("flag,status", [("--help", 0), ("--unknown-option", 2)])
def test_help_and_unknown_arguments_never_run_upgrade(installation, flag, status):
    result, calls = run_installer(installation, flag)
    assert result.returncode == status
    assert calls == []
