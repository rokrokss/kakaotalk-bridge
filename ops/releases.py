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

REPOSITORY = "rokrokss/kakaotalk-bridge"
VERSION = r"v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?"
ASSET = "bridge-install.tar.gz"
MAX_DOWNLOAD = 128 * 1024 * 1024
PERSISTENT = {".git", ".bridge", ".env", "secrets", "inputs", "artifacts", "backups"}


def validate_manifest(data):
    if data.get("schema") != 1 or not re.fullmatch(VERSION, data.get("version", "")):
        raise ValueError("Unsupported release manifest")
    refs = {}
    for kind in ("server", "device", "gateway"):
        ref = data.get("images", {}).get(kind, "")
        if not re.fullmatch(
            re.escape(f"ghcr.io/{REPOSITORY}-{kind}") + r"@sha256:[a-f0-9]{64}", ref
        ):
            raise ValueError("Use the digest-pinned official release manifest")
        refs[kind] = ref
    return refs


def request(url):
    return urlopen(Request(url, headers={"User-Agent": "KakaoTalk-Bridge-Installer"}), timeout=120)


def download_file(url, destination):
    digest = hashlib.sha256()
    total = 0
    with request(url) as response, destination.open("xb") as output:
        if not response.url.startswith("https://"):
            raise ValueError("Download redirected to an insecure URL")
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > MAX_DOWNLOAD:
                raise ValueError("Release download exceeds size limit")
            digest.update(block)
            output.write(block)
    return "sha256:" + digest.hexdigest()


def extract(archive, destination):
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if sum(member.size for member in members) > MAX_DOWNLOAD:
            raise ValueError("Release archive exceeds size limit")
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
                raise ValueError("Unsafe release archive")
        bundle.extractall(destination, filter="data")


def download(target, version="latest", *, source=False):
    target = Path(target).expanduser().absolute()
    if target.exists():
        raise RuntimeError("Installation directory already exists; existing files were preserved")
    if source:
        version = "main" if version == "latest" else version
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
            raise ValueError("Invalid source version")
        url = f"https://codeload.github.com/{REPOSITORY}/tar.gz/{version}"
        expected = None
    else:
        if version != "latest" and not re.fullmatch(VERSION, version):
            raise ValueError("Choose a release tag, or use --source for a branch or commit")
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
            raise ValueError("Unexpected release version")
        version = tag
        asset = next((a for a in release["assets"] if a["name"] == ASSET), None)
        if not asset or not re.fullmatch(r"sha256:[a-f0-9]{64}", asset.get("digest") or ""):
            raise ValueError("Release has no verified installation bundle")
        url = f"https://github.com/{REPOSITORY}/releases/download/{version}/{ASSET}"
        if asset.get("browser_download_url") != url:
            raise ValueError("Unexpected release download URL")
        expected = asset["digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bridge-download-", dir=target.parent) as folder:
        scratch = Path(folder)
        archive = scratch / ASSET
        actual = download_file(url, archive)
        if expected and actual != expected:
            raise ValueError("Release checksum mismatch; nothing was installed")
        incoming = scratch / "incoming"
        extract(archive, incoming)
        if source:
            roots = list(incoming.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError("Unexpected source archive")
            incoming = roots[0]
        else:
            data = json.loads((incoming / "release.json").read_text())
            validate_manifest(data)
            if data["version"] != version:
                raise ValueError("Installation bundle and image versions differ")
        if not all(
            (incoming / name).is_file() for name in ("bridge", "ops/cli.py", "compose.yaml")
        ):
            raise ValueError("Incomplete installation bundle")
        incoming.rename(target)
    print(f"{'소스' if source else '릴리스'} {version} 다운로드 및 검증 완료", flush=True)
    return version


def upgrade(args):
    # Import only here: download() must work before the project is installed.
    from ops import cli, source
    from ops.onboarding import installation_lock
    from ops.setup_output import run

    if sys.platform == "linux" and os.geteuid() != 0:
        run(
            ["sudo", sys.executable, str(cli.ROOT / "bridge"), "upgrade", "--version", args.version]
        )
        return
    if (cli.ROOT / ".git").exists():
        raise RuntimeError(
            "Use a release installation for upgrade; Git checkouts use update --source"
        )
    marker = ".bridge/mac.json" if sys.platform == "darwin" else ".bridge/installed"
    if not (cli.ROOT / marker).exists():
        raise RuntimeError("Run bridge up before upgrading this installation")
    with installation_lock(), tempfile.TemporaryDirectory(prefix="bridge-upgrade-") as folder:
        source.rollback(cli.ROOT)
        incoming = Path(folder) / "incoming"
        print("새 릴리스 다운로드 및 검증 중…", flush=True)
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
        # Source switching and child commands are transactional. The existing image
        # updater owns backups/health checks and rejects unsupported Iris migrations.
        print(f"{version} 업데이트 준비 중… 기존 데이터를 백업합니다.", flush=True)
        source.apply(cli.ROOT, archive)
        command = [sys.executable, str(cli.ROOT / "bridge")]
        try:
            run([*command, "update", "--manifest", str(cli.ROOT / "release.json")])
        except BaseException:
            source.rollback(cli.ROOT)
            print("업데이트를 적용하지 못했습니다. 이전 버전으로 복구 중…", flush=True)
            run([*command, "start"])
            raise
        source.commit(cli.ROOT)
        run([*command, "setup-agent", "install"])
        print(f"{version} 업데이트 완료. 기존 설정과 로그인 정보가 유지됩니다.", flush=True)


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
