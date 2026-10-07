"""Verified release downloads and upgrades. This module also runs as a standalone bootstrap.

The installer fetches this file from main and runs it before any installed code. An
upgrade never executes the installation's previous code: the downloaded version's own
source.py swaps the code, and the new CLI then validates the setup options and updates
the services.
"""

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

try:
    from ops.errors import BridgeError
except ImportError:  # Standalone bootstrap before the project is installed.
    BridgeError = RuntimeError

REPOSITORY = "rokrokss/kakaotalk-bridge"
VERSION = r"v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?"
ASSET = "bridge-install.tar.gz"
MAX_DOWNLOAD = 128 * 1024 * 1024
PERSISTENT = {".git", ".bridge", ".env", "secrets", "inputs", "artifacts", "backups"}
# Version of a downloaded source installation; release installations have release.json.
SOURCE_RECORD = ".bridge/source.json"
# Setup modes and help that run the installation as it is (argparse also accepts prefixes).
AS_IS = ("--plan", "--source", "--manifest", "--help")
# The oldest installed version this release upgrades in place. The upgrade reads it from
# the downloaded release, so every release declares its own floor; older installations
# are deleted and installed fresh.
UPGRADE_FROM = "0.3.1"


def validate_manifest(data):
    if data.get("schema") != 1 or not re.fullmatch(VERSION, data.get("version", "")):
        raise BridgeError("지원하지 않는 릴리스 정보입니다.")
    refs = {}
    for kind in ("server", "device", "gateway"):
        ref = data.get("images", {}).get(kind, "")
        if not re.fullmatch(
            re.escape(f"ghcr.io/{REPOSITORY}-{kind}") + r"@sha256:[a-f0-9]{64}", ref
        ):
            raise BridgeError("공식 릴리스 정보만 사용할 수 있습니다.")
        refs[kind] = ref
    return refs


def request(url):
    return urlopen(Request(url, headers={"User-Agent": "KakaoTalk-Bridge-Installer"}), timeout=120)


def download_file(url, destination):
    digest = hashlib.sha256()
    total = 0
    with request(url) as response, destination.open("xb") as output:
        if not response.url.startswith("https://"):
            raise BridgeError("다운로드가 안전하지 않은 주소로 바뀌어 중단했습니다.")
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > MAX_DOWNLOAD:
                raise BridgeError("다운로드가 허용 크기를 넘었습니다.")
            digest.update(block)
            output.write(block)
    return "sha256:" + digest.hexdigest()


def extract(archive, destination):
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if sum(member.size for member in members) > MAX_DOWNLOAD:
            raise BridgeError("릴리스 파일이 허용 크기를 넘습니다.")
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or any(
                    part in PERSISTENT or (part.startswith(".env") and part != ".env.example")
                    for part in path.parts
                )
                or not (member.isfile() or member.isdir())
            ):
                raise BridgeError("릴리스 파일에 허용되지 않는 경로가 있어 중단했습니다.")
        bundle.extractall(destination, filter="data")



def release_info(version):
    endpoint = "latest" if version == "latest" else "tags/" + version
    with request(f"https://api.github.com/repos/{REPOSITORY}/releases/{endpoint}") as response:
        release = json.loads(response.read(2 * 1024 * 1024))
    tag = release["tag_name"]
    if (
        release.get("draft")
        or not re.fullmatch(VERSION, tag)
        or (version != "latest" and version != tag)
        or (version == "latest" and release.get("prerelease"))
    ):
        raise BridgeError("릴리스 버전이 예상과 다릅니다.")
    return release


def fetch(scratch, version="latest", *, source=False):
    """Download and verify a version into scratch; returns (code folder, version)."""
    scratch = Path(scratch)
    if source:
        # Source installations follow releases unless a branch or commit is named.
        if version == "latest":
            version = release_info("latest")["tag_name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
            raise BridgeError("소스 버전 이름이 올바르지 않습니다.")
        url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{version}"
        expected = None
    else:
        if version != "latest" and not re.fullmatch(VERSION, version):
            raise BridgeError("릴리스 태그(예: v0.2.0)를 지정하세요. 브랜치나 커밋은 --source와 함께 사용합니다.")
        release = release_info(version)
        version = release["tag_name"]
        asset = next((a for a in release["assets"] if a["name"] == ASSET), None)
        if not asset or not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            raise BridgeError("이 릴리스에는 검증된 설치 파일이 없습니다.")
        url = f"https://github.com/{REPOSITORY}/releases/download/{version}/{ASSET}"
        if asset.get("browser_download_url") != url:
            raise BridgeError("릴리스 다운로드 주소가 예상과 다릅니다.")
        expected = asset["digest"]
    archive = scratch / ASSET
    actual = download_file(url, archive)
    if expected and actual != expected:
        raise BridgeError("내려받은 파일의 체크섬이 일치하지 않아 설치하지 않았습니다.")
    incoming = scratch / "incoming"
    extract(archive, incoming)
    if source:
        roots = list(incoming.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise BridgeError("소스 파일 구성이 예상과 다릅니다.")
        incoming = roots[0]
    else:
        data = json.loads((incoming / "release.json").read_text())
        validate_manifest(data)
        if data["version"] != version:
            raise BridgeError("설치 파일과 이미지 버전이 서로 다릅니다.")
    if not all((incoming / name).is_file() for name in ("bridge", "ops/cli.py", "compose.yaml")):
        raise BridgeError("설치 파일이 완전하지 않습니다.")
    return incoming, version


def download(target, version="latest", *, source=False):
    target = Path(target).expanduser().absolute()
    if target.exists():
        raise BridgeError("설치 폴더가 이미 있습니다. 기존 파일은 그대로 두었습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bridge-download-", dir=target.parent) as folder:
        incoming, version = fetch(folder, version, source=source)
        if source:
            record_source(incoming, version)
        incoming.rename(target)
    print(f"{'소스' if source else '릴리스'} {version} 다운로드 및 검증 완료", flush=True)
    return version


def record_source(root, version):
    path = Path(root) / SOURCE_RECORD
    path.parent.mkdir(mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(descriptor, "w") as output:
        json.dump({"version": version}, output)
    os.replace(temporary, path)


def channel(root):
    """How this installation gets new code: git, a verified release, or downloaded source."""
    root = Path(root)
    if (root / ".git").exists():
        return "git"
    if (root / "release.json").is_file():
        return "release"
    return "source"


def finished(root):
    """Whether setup completed; interrupted setups resume with the code that started them."""
    root = Path(root)
    marker = ".bridge/mac.json" if sys.platform == "darwin" else ".bridge/installed"
    if not (root / marker).is_file():
        return False
    progress = root / ".bridge/onboarding.json"
    if not progress.is_file():
        # mac.json is written before the VM finishes its first installation.
        return sys.platform != "darwin"
    try:
        record = json.loads(progress.read_text())
    except (ValueError, OSError):
        return False
    return isinstance(record, dict) and record.get("state") == "ready"


def as_is(arguments):
    """Setup modes and help use the installation unchanged; unclear prefixes count too."""
    for argument in arguments:
        name = argument.split("=", 1)[0]
        if name == "-h" or (
            name.startswith("--") and len(name) >= 4 and any(o.startswith(name) for o in AS_IS)
        ):
            return True
    return False


def current(root, kind, incoming, version):
    if kind == "release":
        installed = root / "release.json"
        return installed.read_bytes() == (incoming / "release.json").read_bytes()
    try:
        recorded = json.loads((root / SOURCE_RECORD).read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return False
    # Branches and commits move, so only a release tag can already be current.
    return recorded == version and re.fullmatch(VERSION, version) is not None


def version_tuple(text):
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(part) for part in match.groups()) if match else ()


def declared(path, name):
    """A top-level `name = "..."` string from a file, or None when it is absent."""
    try:
        match = re.search(rf'^{name} = "([^"]+)"', path.read_text(), re.MULTILINE)
    except OSError:
        return None
    return match[1] if match else None


def vm_missing(root):
    """Whether the Mac's managed VM is gone. A Lima failure stops instead of guessing."""
    if sys.platform != "darwin":
        return False
    vm = json.loads((root / ".bridge/mac.json").read_text())["vm"]
    # GUI shells and fresh Homebrew installs may not include these paths yet.
    os.environ["PATH"] = os.pathsep.join(
        [os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"]
    )
    try:
        names = subprocess.run(
            ["limactl", "list", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        raise BridgeError(
            "Lima VM 상태를 확인하지 못해 업데이트하지 않았습니다. limactl이 동작하는지 확인한 뒤 다시 실행하세요."
        ) from None
    return vm not in names


@contextlib.contextmanager
def lock(root):
    # The same kernel lock as onboarding.installation_lock, so setup and upgrades exclude
    # each other. Child commands do not take it.
    import fcntl

    path = Path(root) / ".bridge/up.lock"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError("이 설치에서 다른 설정 작업이 이미 진행 중입니다. 끝난 뒤 다시 실행하세요.") from None
        yield


def swapper(incoming):
    """The downloaded version's own source.py, so swapping never runs the previous code."""
    path = incoming / "ops/source.py"
    if not path.is_file():
        raise BridgeError("이 버전은 설치 명령으로 업데이트할 수 없습니다. 더 최신 버전을 지정하세요.")
    spec = importlib.util.spec_from_file_location("bridge_incoming_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade_installation(root, version="latest", *, bridge, plan=None, say=print):
    """Bring an installation to `version` with the downloaded code. True if it changed.

    `bridge(*arguments, quiet=False)` runs the installation's CLI, which is the new one
    once the code is swapped. `plan` holds setup options to validate before updating.
    """
    root = Path(root)
    kind = channel(root)
    if kind == "git":
        raise BridgeError("Git 작업 폴더는 git pull 후 kakaotalk-bridge update --source로 업데이트하세요.")
    with lock(root), tempfile.TemporaryDirectory(prefix="bridge-upgrade-") as folder:
        say("새 버전 내려받고 검증하는 중…")
        incoming, version = fetch(folder, version, source=kind == "source")
        if current(root, kind, incoming, version):
            print(
                f"이미 {version} {'소스' if kind == 'source' else '릴리스'}를 사용하고 있습니다.",
                flush=True,
            )
            return False
        floor = declared(incoming / "ops/releases.py", "UPGRADE_FROM")
        installed = declared(root / "pyproject.toml", "version")
        if floor and version_tuple(installed) < version_tuple(floor):
            raise BridgeError(
                f"{installed or '버전을 알 수 없는'} 설치는 {version} 버전으로 업데이트할 수 없습니다. "
                f"{root}에서 ./bridge cleanup으로 삭제한 뒤(명령이 없으면 Lima VM과 설치 폴더를 직접 삭제) "
                "설치 명령을 다시 실행하세요. 카카오톡 로그인과 수집한 데이터도 삭제됩니다."
            )
        missing = vm_missing(root)
        source = swapper(incoming)
        archive = Path(folder) / "code.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for entry in sorted(incoming.iterdir()):
                # Like release bundles: source archives carry .env.example, and the swap
                # never touches settings files.
                if not entry.name.startswith(".env"):
                    bundle.add(entry, arcname=entry.name)
        say(f"{version} 설치 파일 적용 중…")
        source.apply(root, archive)
        if plan is not None:
            try:
                bridge("up", "--plan", *plan, quiet=True)
            except BaseException:
                source.rollback(root)
                raise
        # Without the VM nothing runs old images; setup recreates it with the new code.
        if not missing:
            selection = ["--source"] if kind == "source" else ["--manifest", str(root / "release.json")]
            # The image updater owns backups and health checks, and restores the old images.
            try:
                bridge("update", *selection)
            except BaseException:
                source.rollback(root)
                say("업데이트를 적용하지 못해 이전 버전으로 복구하는 중…")
                bridge("start")
                raise
        source.commit(root)
        if kind == "source":
            record_source(root, version)
        if os.geteuid() == 0 and hasattr(source, "share_code"):
            # Root-run updates keep code readable for the SSH account that runs bridge mcp.
            with contextlib.suppress(OSError):
                source.share_code(root)
        if not missing:
            bridge("setup-agent", "install")
        say(f"{version} 버전으로 업데이트했습니다. 기존 설정과 로그인 정보는 그대로입니다.")
        return True


def upgrade(args):
    """kakaotalk-bridge upgrade: the same upgrade the installer runs, for this installation."""
    from ops import cli
    from ops.setup_output import bridge_command, progress, run

    if sys.platform == "linux" and os.geteuid() != 0:
        run(["sudo", *bridge_command("upgrade", "--version", args.version)])
        return
    marker = ".bridge/mac.json" if sys.platform == "darwin" else ".bridge/installed"
    if not (cli.ROOT / marker).exists():
        raise BridgeError("업데이트하기 전에 kakaotalk-bridge up으로 설치를 완료하세요.")
    upgrade_installation(
        cli.ROOT,
        args.version,
        bridge=lambda *arguments, quiet=False: run(bridge_command(*arguments)),
        say=progress,
    )


def launch(home, version, arguments):
    """Installer entry: upgrade a finished installation, then open setup with its CLI."""
    home = Path(home).resolve()
    command = [sys.executable, str(home / "bridge")]

    def bridge(*parts, quiet=False):
        subprocess.run(
            [*command, *parts], check=True, stdout=subprocess.DEVNULL if quiet else None
        )

    if channel(home) == "git":
        print(
            "Git 작업 폴더는 자동으로 업데이트하지 않습니다. "
            "git pull 후 kakaotalk-bridge update --source를 실행하세요.",
            flush=True,
        )
    elif finished(home) and not as_is(arguments):
        try:
            upgrade_installation(
                home, version, bridge=bridge, plan=arguments, say=lambda text: print(text, flush=True)
            )
        except subprocess.CalledProcessError as error:
            # The failing command already showed its guidance.
            sys.exit(error.returncode)
        except KeyboardInterrupt:
            sys.exit("중단되었습니다. 같은 명령을 실행해 이어서 진행하세요.")
        except (RuntimeError, ValueError) as error:
            # Guidance raised here, written for the person running the installer.
            sys.exit(str(error))
        except Exception as error:  # noqa: BLE001 — network and file errors, no traceback
            sys.exit(f"업데이트하지 못했습니다. 네트워크 연결을 확인한 뒤 같은 명령을 다시 실행하세요. ({error})")
    sys.stdout.flush()
    os.execv(sys.executable, [*command, "up", *arguments])


def main():
    os.umask(0o077)
    if sys.argv[1:2] == ["launch"]:
        home, version, *arguments = sys.argv[2:]
        launch(home, version, arguments[1:] if arguments[:1] == ["--"] else arguments)
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["download"])
    parser.add_argument("target")
    parser.add_argument("version", nargs="?", default="latest")
    parser.add_argument("--source", action="store_true")
    args = parser.parse_args()
    download(args.target, args.version, source=args.source)


if __name__ == "__main__":
    main()
