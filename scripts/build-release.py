"""Build the public installer bundle from tracked code and immutable image refs."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.releases import REPOSITORY, VERSION, validate_manifest


def build(version, digests, destination):
    if not re.fullmatch(VERSION, version):
        raise ValueError("Invalid release version")
    data = {
        "schema": 1,
        "version": version,
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "images": {
            kind: f"ghcr.io/{REPOSITORY}-{kind}@{digest}" for kind, digest in digests.items()
        },
    }
    validate_manifest(data)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = (json.dumps(data, indent=2) + "\n").encode()
    (destination / "release.json").write_bytes(manifest)
    tracked = subprocess.check_output(["git", "archive", "HEAD"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tracked)) as source:
        with tarfile.open(destination / "bridge-install.tar.gz", "w:gz") as bundle:
            for member in source.getmembers():
                if member.name.startswith(".env"):
                    continue
                if not (member.isdir() or member.isfile()):
                    raise ValueError("Release source must not contain links")
                bundle.addfile(member, source.extractfile(member) if member.isfile() else None)
            member = tarfile.TarInfo("release.json")
            member.size, member.mode = len(manifest), 0o644
            bundle.addfile(member, io.BytesIO(manifest))
        for name in ("install.sh", "install.ps1"):
            (destination / name).write_bytes(source.extractfile(name).read())
    checksums = []
    for path in sorted(destination.iterdir()):
        if path.name != "SHA256SUMS":
            checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
    (destination / "SHA256SUMS").write_text("".join(checksums))
    print(f"{version} 설치 파일·이미지 매니페스트·체크섬 생성 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    for kind in ("server", "device", "gateway"):
        parser.add_argument("--" + kind, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/release"))
    args = parser.parse_args()
    build(
        args.version,
        {kind: getattr(args, kind) for kind in ("server", "device", "gateway")},
        args.output,
    )
