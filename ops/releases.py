"""Verified release downloads. This module also runs as a standalone bootstrap."""

import argparse
import hashlib
import json
import os
import re
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


def download(target, version="latest", *, source=False):
    target = Path(target).expanduser().absolute()
    if target.exists():
        raise BridgeError("설치 폴더가 이미 있습니다. 기존 파일은 그대로 두었습니다.")
    if source:
        version = "main" if version == "latest" else version
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
            raise BridgeError("소스 버전 이름이 올바르지 않습니다.")
        url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{version}"
        expected = None
    else:
        if version != "latest" and not re.fullmatch(VERSION, version):
            raise BridgeError("릴리스 태그(예: v0.2.0)를 지정하세요. 브랜치나 커밋은 --source와 함께 사용합니다.")
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
        version = tag
        asset = next((a for a in release["assets"] if a["name"] == ASSET), None)
        if not asset or not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            raise BridgeError("이 릴리스에는 검증된 설치 파일이 없습니다.")
        url = f"https://github.com/{REPOSITORY}/releases/download/{version}/{ASSET}"
        if asset.get("browser_download_url") != url:
            raise BridgeError("릴리스 다운로드 주소가 예상과 다릅니다.")
        expected = asset["digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bridge-download-", dir=target.parent) as folder:
        scratch = Path(folder)
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
        if not all(
            (incoming / name).is_file() for name in ("bridge", "ops/cli.py", "compose.yaml")
        ):
            raise BridgeError("설치 파일이 완전하지 않습니다.")
        incoming.rename(target)
    print(f"{'소스' if source else '릴리스'} {version} 다운로드 및 검증 완료", flush=True)
    return version


def upgrade(args):
    # Import only here: download() must work before the project is installed.
    from ops import cli, source
    from ops.onboarding import installation_lock
    from ops.setup_output import bridge_command, progress, run

    if sys.platform == "linux" and os.geteuid() != 0:
        run(["sudo", *bridge_command("upgrade", "--version", args.version)])
        return
    if (cli.ROOT / ".git").exists():
        raise BridgeError("Git 소스 설치는 ./bridge update --source로 업데이트하세요.")
    marker = ".bridge/mac.json" if sys.platform == "darwin" else ".bridge/installed"
    if not (cli.ROOT / marker).exists():
        raise BridgeError("업데이트하기 전에 ./bridge up으로 설치를 완료하세요.")
    with installation_lock(), tempfile.TemporaryDirectory(prefix="bridge-upgrade-") as folder:
        source.rollback(cli.ROOT)
        incoming = Path(folder) / "incoming"
        progress("새 릴리스 내려받고 검증하는 중…")
        version = download(incoming, args.version)
        installed = cli.ROOT / "release.json"
        if (
            installed.exists()
            and installed.read_bytes() == (incoming / "release.json").read_bytes()
        ):
            print(f"이미 {version} 릴리스를 사용하고 있습니다.")
            return
        archive = Path(folder) / ASSET
        with tarfile.open(archive, "w:gz") as bundle:
            for entry in sorted(incoming.iterdir()):
                bundle.add(entry, arcname=entry.name)
        # Source switching and child commands are transactional. The image updater
        # owns backups and health checks.
        progress(f"{version} 설치 파일 적용 중…")
        source.apply(cli.ROOT, archive)
        try:
            run(bridge_command("update", "--manifest", str(cli.ROOT / "release.json")))
        except BaseException:
            source.rollback(cli.ROOT)
            progress("업데이트를 적용하지 못해 이전 버전으로 복구하는 중…")
            run(bridge_command("start"))
            raise
        source.commit(cli.ROOT)
        cli.share_code()
        run(bridge_command("setup-agent", "install"))
        progress(f"{version}으로 업데이트했습니다. 기존 설정과 로그인 정보는 그대로입니다.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("version", nargs="?", default="latest")
    parser.add_argument("--source", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    download(args.target, args.version, source=args.source)


if __name__ == "__main__":
    main()
