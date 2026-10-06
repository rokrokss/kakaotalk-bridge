#!/usr/bin/env python3
"""Copy only installed KakaoTalk APKs from one authorized USB Android phone."""

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.errors import BridgeError


def adb(*args):
    result = subprocess.run(
        ["adb", "-d", *args], capture_output=True, text=True, timeout=180, check=False
    )
    if result.returncode:
        raise BridgeError("USB로 연결된 휴대폰을 찾을 수 없거나 허용되지 않았습니다. 휴대폰 잠금을 풀고 USB 디버깅을 허용하세요.")
    return result.stdout.strip()


def main():
    target = Path(__file__).resolve().parents[1] / "inputs" / "kakao"
    target.mkdir(parents=True, exist_ok=True)
    if list(target.glob("*.apk")):
        raise BridgeError("inputs/kakao에 이미 APK가 있습니다. 새 세트를 가져오기 전에 기존 파일을 다른 곳에 보관하세요.")
    paths = adb("shell", "pm", "path", "com.kakao.talk").splitlines()
    if not paths or any(not line.startswith("package:") for line in paths):
        raise BridgeError("휴대폰에 카카오톡이 설치되어 있지 않거나 APK에 접근할 수 없습니다.")
    paths = [line.removeprefix("package:") for line in paths]
    if any(not re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~\-]+\.apk", p) or ".." in p for p in paths):
        raise BridgeError("APK 경로가 예상과 달라 아무 파일도 복사하지 않았습니다.")
    names = [Path(p).name for p in paths]
    if len(set(names)) != len(names) or "base.apk" not in names:
        raise BridgeError("분할 APK 구성이 예상과 달라 아무 파일도 복사하지 않았습니다.")
    with tempfile.TemporaryDirectory(prefix="kakao-apks-", dir=target.parent) as temporary:
        for remote, name in zip(paths, names, strict=True):
            local = Path(temporary) / name
            adb("pull", remote, str(local))
            if not local.is_file() or local.stat().st_size == 0:
                raise BridgeError("APK 복사가 끝나지 않아 대상 폴더를 바꾸지 않았습니다.")
            local.chmod(0o600)
        for name in names:
            local = Path(temporary) / name
            with local.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            shutil.move(local, target / name)
            print(f"{name}: sha256={digest}")
    print(f"카카오톡 APK {len(names)}개를 복사했습니다. 앱 데이터와 로그인 설정은 유지됩니다.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        from ops.setup_output import report_error

        report_error(exc)
        raise SystemExit(1) from None
