"""Fresh-device preparation; never logs in, clears app data, or resets enrollment."""

import hashlib
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from device import cli

AURORA_URL = "https://f-droid.org/repo/com.aurora.store_76.apk"
AURORA_SHA256 = "fd9c75d90d0f4a7c132b9b4a5a2cf1992a45e03b8d8ff988b7dcfbc0db2c4d11"
KAKAO_SIGNER = "2b06cc3d47782d7c497c07f17cb5f859cd6bbcb66829f3e67b96b7a44820d2ce"


def enrolled():
    from device.enrollment import ENROLLMENT, LEGACY_ENROLLMENT

    found = f"'(test -f {ENROLLMENT} || test -f {LEGACY_ENROLLMENT}) && echo present'"
    return cli.adb("shell", "sh", "-c", found, check=False) == "present"


def status():
    result = cli.sample()
    if result["state"] not in ("offline", "booting"):
        result.update(
            aurora_installed=cli.is_installed("com.aurora.store"),
            enrolled=enrolled(),
            apk_available=any(Path("/inputs/kakao").glob("*.apk")),
            locale=cli.adb("shell", "getprop", "persist.sys.locale")[:32],
        )
    return result


def verify_kakao(paths):
    for path in paths:
        result = subprocess.run(
            ["java", "-jar", "/opt/apksigner.jar", "verify", "--print-certs", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        signers = re.findall(
            r"^Signer #\d+ certificate SHA-256 digest: ([a-f0-9]+)$", result.stdout, re.MULTILINE
        )
        if result.returncode or signers != [KAKAO_SIGNER]:
            raise RuntimeError("kakao_signature_unverified")


def verify_installed_kakao():
    paths = cli.adb("shell", "pm", "path", "com.kakao.talk").splitlines()
    if not paths or len(paths) > 32:
        raise RuntimeError("kakao_not_installed")
    with tempfile.TemporaryDirectory() as folder:
        local = []
        for index, line in enumerate(paths):
            remote = line.removeprefix("package:")
            if not re.fullmatch(r"/data/app/[A-Za-z0-9_=/+.~-]+\.apk", remote):
                raise RuntimeError("kakao_signature_unverified")
            path = Path(folder) / f"{index}.apk"
            cli.adb("pull", remote, str(path), timeout=120)
            local.append(path)
        verify_kakao(local)


def open_store():
    cli.connect()
    lines = cli.adb(
        "shell",
        "cmd",
        "package",
        "resolve-activity",
        "--brief",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        "com.aurora.store",
    ).splitlines()
    component = lines[-1] if lines else ""
    if not re.fullmatch(r"com\.aurora\.store/[A-Za-z0-9_.$]+", component):
        raise RuntimeError("aurora_not_installed")
    cli.adb("shell", "am", "start", "-n", component)


def prepare():
    state = status()
    if state["state"] in ("offline", "booting"):
        raise RuntimeError("android_not_ready")
    if (
        state.get("enrolled")
        or state.get("kakao_installed")
        or state.get("bridge_installed")
        or Path("/state/enrollment.json").exists()
    ):
        return False
    if cli.adb("shell", "id", "-u") != "0":
        raise RuntimeError("root_adb_required")
    if state.get("locale") != "ko-KR":
        cli.adb("shell", "setprop", "persist.sys.locale", "ko-KR")
        # Only a fresh device reaches here. Restart the framework to apply the locale
        # before Play delivers language splits. Never reboot an enrolled device.
        # Framework stop/start does not clear the previous boot-completed property.
        # Without resetting it, PackageManager can appear before ADB's install
        # transport is ready and the first install fails with abb_exec: closed.
        cli.adb("shell", "setprop", "sys.boot_completed", "0")
        cli.adb("shell", "stop")
        cli.adb("shell", "start")
        for _ in range(60):
            time.sleep(2)
            if cli.sample()["state"] == "needs_setup" and "package:android" in cli.adb(
                "shell", "pm", "list", "packages", "android", check=False
            ):
                break
        else:
            raise RuntimeError("android_not_ready")
    if not state.get("aurora_installed"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "aurora.apk"
            with urlopen(AURORA_URL, timeout=60) as response, path.open("wb") as output:
                count = 0
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > 30 * 1024 * 1024:
                        raise RuntimeError("aurora_artifact_unverified")
                    output.write(chunk)
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != AURORA_SHA256:
                    raise RuntimeError("aurora_artifact_unverified")
            cli.adb("install", str(path), timeout=120)
        if not cli.is_installed("com.aurora.store"):
            raise RuntimeError("aurora_not_installed")
    open_store()
    return True
