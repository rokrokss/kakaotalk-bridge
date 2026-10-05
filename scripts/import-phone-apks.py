#!/usr/bin/env python3
"""Copy only installed KakaoTalk APKs from one authorized USB Android phone."""

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def adb(*args):
    result = subprocess.run(
        ["adb", "-d", *args], capture_output=True, text=True, timeout=180, check=False
    )
    if result.returncode:
        raise RuntimeError(
            "USB phone unavailable or not authorized; unlock and allow USB debugging"
        )
    return result.stdout.strip()


def main():
    target = Path(__file__).resolve().parents[1] / "inputs" / "kakao"
    target.mkdir(parents=True, exist_ok=True)
    if list(target.glob("*.apk")):
        raise RuntimeError(
            "inputs/kakao already contains APKs; preserve them before importing a new set"
        )
    paths = adb("shell", "pm", "path", "com.kakao.talk").splitlines()
    if not paths or any(not line.startswith("package:") for line in paths):
        raise RuntimeError("KakaoTalk is not installed or its APKs are inaccessible")
    paths = [line.removeprefix("package:") for line in paths]
    if any(not re.fullmatch(r"/data/app/[A-Za-z0-9_./=+~\-]+\.apk", p) or ".." in p for p in paths):
        raise RuntimeError("Unexpected APK path; no files were copied")
    names = [Path(p).name for p in paths]
    if len(set(names)) != len(names) or "base.apk" not in names:
        raise RuntimeError("Unexpected split APK layout; no files were copied")
    with tempfile.TemporaryDirectory(prefix="kakao-apks-", dir=target.parent) as temporary:
        for remote, name in zip(paths, names, strict=True):
            local = Path(temporary) / name
            adb("pull", remote, str(local))
            if not local.is_file() or local.stat().st_size == 0:
                raise RuntimeError("APK copy incomplete; target directory was not changed")
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
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from ops.setup_output import report_error

        report_error(exc)
        raise SystemExit(1) from None
