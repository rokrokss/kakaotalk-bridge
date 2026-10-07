import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "rokrokss/kakaotalk-bridge"

# A stand-in for a version's CLI: record subprocess boundaries with the generation that
# ran them, so a test can prove an upgrade never executes the installed (old) code.
CLI = '''\
import json
import os
import sys
from pathlib import Path

generation = "GENERATION"
root = Path(__file__).parent
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps([generation, sys.argv[1:]]) + "\\n")
command = sys.argv[1]
if command == "update":
    assert sys.stdin.read() == "", "installer input leaked into the update"
if command == "up" and "--plan" in sys.argv:
    command = "plan"
sys.exit(int(os.environ.get("BRIDGE_TEST_" + command.upper().replace("-", "_") + "_EXIT", "0")))
'''

# Serves fake GitHub responses to the real releases.py inside the installer's Python.
NETWORK = '''\
import io
import json
import os
import urllib.request
from pathlib import Path

folder = Path(os.environ["BRIDGE_TEST_NETWORK"])


def urlopen(request, timeout=None):
    url = getattr(request, "full_url", request)
    with (folder / "requests.jsonl").open("a") as log:
        log.write(json.dumps(url) + "\\n")
    routes = json.loads((folder / "routes.json").read_text())
    if url not in routes:
        raise OSError("unexpected download: " + url)
    response = io.BytesIO((folder / routes[url]).read_bytes())
    response.url = url
    return response


urllib.request.urlopen = urlopen
'''


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as bundle:
        for name, content in files.items():
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def new_version(prefix=""):
    return {
        prefix + "bridge": CLI.replace("GENERATION", "new"),
        prefix + "ops/cli.py": "# new cli",
        prefix + "ops/source.py": (ROOT / "ops/source.py").read_text(),
        prefix + "compose.yaml": "services: {}",
    }


MANIFEST = json.dumps(
    {
        "schema": 1,
        "version": "v0.2.0",
        "images": {
            kind: f"ghcr.io/{REPOSITORY}-{kind}@sha256:" + "b" * 64
            for kind in ("server", "device", "gateway")
        },
    }
)


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "existing bridge"
    root.mkdir()
    shutil.copytree(ROOT / "ops", root / "ops", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "install.sh", root / "install.sh")
    (root / "release.json").write_text('{"version":"v0.1.0"}')
    (root / "bridge").write_text(CLI.replace("GENERATION", "old"))
    state = root / ".bridge"
    state.mkdir()
    (state / "installed").write_text("1")
    (state / "mac.json").write_text('{"vm":"existing-vm"}')
    (state / "onboarding.json").write_text('{"state":"ready"}')
    (root / ".env").write_text("KEEP=original\n")
    (root / "secrets").mkdir()
    (root / "secrets/identity").write_text("existing identity")

    network = tmp_path / "network"
    network.mkdir()
    (network / "sitecustomize.py").write_text(NETWORK)
    bundle = archive({**new_version(), "release.json": MANIFEST})
    (network / "bundle.tar.gz").write_bytes(bundle)
    # GitHub source archives also carry .env.example, which release bundles leave out.
    source = {**new_version("kakaotalk-bridge-v0.2.0/"), "kakaotalk-bridge-v0.2.0/.env.example": ""}
    (network / "source.tar.gz").write_bytes(archive(source))
    asset = f"https://github.com/{REPOSITORY}/releases/download/v0.2.0/bridge-install.tar.gz"
    (network / "release.json").write_text(
        json.dumps(
            {
                "tag_name": "v0.2.0",
                "assets": [
                    {
                        "name": "bridge-install.tar.gz",
                        "browser_download_url": asset,
                        "digest": "sha256:" + hashlib.sha256(bundle).hexdigest(),
                    }
                ],
            }
        )
    )
    api = f"https://api.github.com/repos/{REPOSITORY}/releases/"
    (network / "routes.json").write_text(
        json.dumps(
            {
                api + "latest": "release.json",
                api + "tags/v0.2.0": "release.json",
                asset: "bundle.tar.gz",
                f"https://codeload.github.com/{REPOSITORY}/tar.gz/v0.2.0": "source.tar.gz",
            }
        )
    )

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
    # The piped installer fetches this repository's helper from main.
    curl = binaries / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import shutil, sys\n"
        f"assert sys.argv[-3] == 'https://raw.githubusercontent.com/{REPOSITORY}/main/ops/releases.py'\n"
        f"shutil.copyfile({str(ROOT / 'ops/releases.py')!r}, sys.argv[-1])\n"
    )
    curl.chmod(0o755)
    # Linux installs re-run through sudo, which resets the test environment. Run as
    # root here; test_onboarding covers the elevation itself.
    user = binaries / "id"
    user.write_text("#!/bin/sh\necho 0\n")
    user.chmod(0o755)
    return root


def run_installer(root, *arguments, local=False, **environment):
    env = {**os.environ, **environment}
    env.pop("BRIDGE_HOME", None)
    env.pop("BRIDGE_VERSION", None)
    env.update(environment)
    env["PATH"] = str(root / "test-bin") + os.pathsep + env["PATH"]
    network = root.parent / "network"
    env["BRIDGE_TEST_NETWORK"] = str(network)
    env["PYTHONPATH"] = str(network)
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
        timeout=20,
        check=False,
    )
    log = root / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert (root / ".env").read_text() == "KEEP=original\n"
    assert (root / "secrets/identity").read_text() == "existing identity"
    return result, calls


def downloads(root):
    log = root.parent / "network/requests.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("version", [None, "v0.2.0"])
def test_rerun_upgrades_with_only_the_new_code(installation, local, version):
    flags = ["--no-browser", "--vm", "existing-vm", "--admin-port", "19443"]
    environment = {"BRIDGE_VERSION": version} if version else {}
    result, calls = run_installer(installation, *flags, local=local, **environment)
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["new", ["up", "--plan", *flags]],
        ["new", ["update", "--manifest", str(installation.resolve() / "release.json")]],
        ["new", ["setup-agent", "install"]],
        ["new", ["up", *flags]],
    ]
    assert json.loads((installation / "release.json").read_text())["version"] == "v0.2.0"
    assert "v0.2.0 버전으로 업데이트했습니다" in result.stdout
    assert downloads(installation)[0].endswith("latest" if version is None else "tags/v0.2.0")


def test_current_release_opens_setup_without_redeploying(installation):
    (installation / "release.json").write_text(MANIFEST)
    result, calls = run_installer(installation, "--no-browser")
    assert result.returncode == 0, result.stderr
    assert calls == [["old", ["up", "--no-browser"]]]
    assert "이미 v0.2.0 릴리스를 사용하고 있습니다." in result.stdout


def test_pre_release_source_snapshot_upgrades_and_keeps_building_its_own_images(installation):
    # The shape of curl installs before the first release: main's source, no release.json.
    (installation / "release.json").unlink()
    result, calls = run_installer(installation, "--no-browser")
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["new", ["up", "--plan", "--no-browser"]],
        ["new", ["update", "--source"]],
        ["new", ["setup-agent", "install"]],
        ["new", ["up", "--no-browser"]],
    ]
    assert downloads(installation)[-1].endswith("/tar.gz/v0.2.0")
    assert not (installation / "release.json").exists()
    record = json.loads((installation / ".bridge/source.json").read_text())
    assert record == {"version": "v0.2.0"}

    result, calls = run_installer(installation, "--no-browser")
    assert result.returncode == 0, result.stderr
    assert calls[-1] == ["new", ["up", "--no-browser"]]
    assert ["new", ["update", "--source"]] not in calls[4:]
    assert "이미 v0.2.0 소스를 사용하고 있습니다." in result.stdout


@pytest.mark.parametrize(
    "flags",
    [["--plan"], ["--pla"], ["--source"], ["--manifest", "custom.json"], ["--help"]],
)
def test_setup_modes_and_help_run_the_installation_as_is(installation, flags):
    result, calls = run_installer(installation, *flags)
    assert result.returncode == 0, result.stderr
    assert calls == [["old", ["up", *flags]]]
    assert downloads(installation) == []


@pytest.mark.parametrize(
    "state",
    ["downloaded", "running", "interrupted", "git", "damaged-progress", "null-progress"],
)
def test_incomplete_and_git_installations_resume_without_upgrade(installation, state):
    if state == "downloaded":
        (installation / ".bridge/installed").unlink()
        (installation / ".bridge/mac.json").unlink()
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
    assert calls == [["old", ["up", "--no-browser"]]]
    assert downloads(installation) == []
    if state == "git":
        assert "git pull" in result.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac VM recovery")
def test_missing_mac_vm_takes_new_code_and_lets_its_setup_recreate_the_vm(installation):
    result, calls = run_installer(installation, "--no-browser", BRIDGE_TEST_VM_NAMES="other-vm")
    assert result.returncode == 0, result.stderr
    assert calls == [
        ["new", ["up", "--plan", "--no-browser"]],
        ["new", ["up", "--no-browser"]],
    ]


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac VM recovery")
def test_lima_failure_stops_before_changing_any_code(installation):
    result, calls = run_installer(installation, "--no-browser", BRIDGE_TEST_LIMA_EXIT="23")
    assert result.returncode == 1
    assert calls == []
    assert "Lima VM 상태를 확인하지 못해" in result.stderr
    assert '"old"' in (installation / "bridge").read_text()


def test_update_failure_restores_the_previous_code_and_services(installation):
    result, calls = run_installer(installation, "--no-browser", BRIDGE_TEST_UPDATE_EXIT="23")
    assert result.returncode == 23
    assert calls == [
        ["new", ["up", "--plan", "--no-browser"]],
        ["new", ["update", "--manifest", str(installation.resolve() / "release.json")]],
        ["old", ["start"]],
    ]
    assert (installation / "release.json").read_text() == '{"version":"v0.1.0"}'


@pytest.mark.parametrize("arguments", [["--admin-port", "80"], ["--unknown-option"]])
def test_invalid_setup_options_restore_the_code_before_updating(installation, arguments):
    result, calls = run_installer(installation, *arguments, BRIDGE_TEST_PLAN_EXIT="2")
    assert result.returncode == 2
    assert calls == [["new", ["up", "--plan", *arguments]]]
    assert '"old"' in (installation / "bridge").read_text()
    assert (installation / "release.json").read_text() == '{"version":"v0.1.0"}'


def test_unverified_download_never_touches_the_installation(installation):
    (installation.parent / "network/bundle.tar.gz").write_bytes(b"tampered")
    result, calls = run_installer(installation, "--no-browser")
    assert result.returncode == 1
    assert calls == []
    assert "체크섬이 일치하지 않아" in result.stderr
    assert '"old"' in (installation / "bridge").read_text()
