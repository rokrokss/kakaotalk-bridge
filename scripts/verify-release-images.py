"""Verify anonymous GHCR access and both published runtime architectures."""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.releases import validate_manifest


def verify(ref):
    name, digest = ref.removeprefix("ghcr.io/").split("@")
    # Deliberately omit the Actions token: public installs have no credentials.
    with urlopen(
        f"https://ghcr.io/token?service=ghcr.io&scope=repository:{name}:pull", timeout=30
    ) as response:
        token = json.load(response)["token"]
    request = Request(
        f"https://ghcr.io/v2/{name}/manifests/{digest}",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json",
        },
    )
    with urlopen(request, timeout=30) as response:
        manifest = json.load(response)
    platforms = {
        (item.get("platform", {}).get("os"), item.get("platform", {}).get("architecture"))
        for item in manifest.get("manifests", [])
    }
    if not {("linux", "amd64"), ("linux", "arm64")} <= platforms:
        raise ValueError("Release image is missing a supported Linux architecture")
    print(f"공개 다운로드 및 amd64·arm64 확인 완료: {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait_seconds
    for ref in validate_manifest(json.loads(args.manifest.read_text())).values():
        while True:
            try:
                verify(ref)
                break
            except HTTPError as exc:
                if exc.code not in (401, 403, 404) or time.monotonic() >= deadline:
                    raise
                print(
                    "GHCR 패키지 공개 설정을 기다리는 중… GitHub Packages에서 Public으로 설정하세요.",
                    flush=True,
                )
                time.sleep(30)
