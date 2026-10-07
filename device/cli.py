"""Fixed-purpose ADB tasks. No external command endpoint and no Docker socket."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

# The keyboard app keeps the application ID it was first released with: Android stores
# the enabled input method by this ID, so renaming it would orphan installed devices.
PKG = "dev.kakaocollector.bridge"
IME = f"{PKG}/dev.kakaotalkbridge.android.WebInputMethod"


def adb(*args, timeout=25, check=True):
    result = subprocess.run(
        ["adb", "-s", os.getenv("ADB_TARGET", "redroid:5555"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError("adb_failed")
    return result.stdout.strip()


def connect():
    subprocess.run(
        ["adb", "connect", os.getenv("ADB_TARGET", "redroid:5555")],
        capture_output=True,
        timeout=15,
        check=False,
    )
    # Secure userdebug adbd may start as shell after an Android restart. Only an
    # already-authorized collector key can request root; no pairing bypass.
    if adb("shell", "id", "-u", check=False) == "2000":
        adb("root", check=False)
        for _ in range(20):
            time.sleep(0.5)
            if adb("shell", "id", "-u", check=False) == "0":
                break
        else:
            raise RuntimeError("root_adb_required")


def is_installed(package):
    return adb("shell", "pm", "path", package, check=False).startswith("package:")


def sample():
    result = {"device_id": os.getenv("DEVICE_ID", "personal-tablet"), "state": "offline"}
    try:
        connect()
        if adb("get-state") != "device":
            return result
        if adb("shell", "getprop", "sys.boot_completed") != "1":
            result["state"] = "booting"
            return result
        kakao, bridge = is_installed("com.kakao.talk"), is_installed(PKG)
        result.update(
            state="android_ready" if kakao and bridge else "needs_setup",
            kakao_installed=kakao,
            bridge_installed=bridge,
            android_version=adb("shell", "getprop", "ro.build.version.release")[:64],
        )
    except (RuntimeError, subprocess.TimeoutExpired):
        pass
    return result


def report(payload):
    token = Path("/run/secrets/device_token").read_text().strip()
    request = Request(
        os.getenv("API_URL", "http://api:8000") + "/internal/v1/device-status",
        json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("device_status_not_committed")


def bootstrap(rotate_epoch=False, *, preserve=False):
    from device import enrollment, iris

    print("Android 시작 대기 중… 최대 180초가 걸릴 수 있습니다.", flush=True)
    deadline = time.monotonic() + 180
    while sample()["state"] in ("offline", "booting"):
        if time.monotonic() >= deadline:
            raise RuntimeError("android_not_ready")
        time.sleep(3)
    # Dedicated redroid root ADB provisions enrollment and the Iris DB reader.
    adb("root", check=False)
    for _ in range(20):
        try:
            connect()
            if adb("shell", "id", "-u") == "0":
                break
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("root_adb_required")
    state = Path("/state/enrollment.json")
    device = os.getenv("DEVICE_ID", "personal-tablet")
    current = enrollment.snapshot().config
    if current and not state.exists() and not rotate_epoch:
        raise RuntimeError("host_state_missing")
    if preserve and current:
        identity = json.loads(state.read_text())
        if (
            identity.get("enrollment_epoch") != current.get("enrollment_epoch")
            or identity.get("device_id") != device
        ):
            raise RuntimeError("enrollment_mismatch")
        return False
    if preserve:
        from device.setup import verify_installed_kakao, verify_kakao

        if not is_installed("com.kakao.talk"):
            supplied = sorted(Path("/inputs/kakao").glob("*.apk"))
            if not supplied:
                raise RuntimeError("kakao_not_installed")
            verify_kakao(supplied)
            adb("install-multiple", *map(str, supplied), timeout=180)
        verify_installed_kakao()
    if not state.exists():
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"device_id": device, "enrollment_epoch": str(uuid.uuid4())}))
        state.chmod(0o600)
    identity = json.loads(state.read_text())
    if identity["device_id"] != device:
        raise RuntimeError("device_identity_changed")
    if rotate_epoch:
        identity["enrollment_epoch"] = str(uuid.uuid4())
        state.write_text(json.dumps(identity))
    apks = sorted(Path("/inputs/kakao").glob("*.apk"))
    if apks and not preserve:
        print("제공된 카카오톡 APK 세트 설치 중… 로그인은 수행하지 않습니다.")
        for apk in apks:
            with apk.open("rb") as source:
                print(f"APK SHA256 {hashlib.file_digest(source, 'sha256').hexdigest()}")
        adb("install-multiple", "-r", *map(str, apks), timeout=180)
    if not is_installed("com.kakao.talk"):
        raise RuntimeError("kakao_not_installed")
    adb("install", "-r", "/opt/bridge.apk", timeout=120)
    iris.stop()
    # A new enrollment starts locked. The collector installs its own Iris build once approved.
    enrollment.write(
        {"device_id": identity["device_id"], "enrollment_epoch": identity["enrollment_epoch"]}
    )
    print(
        "설치가 완료되었습니다. 카카오톡에서 ‘다른 기기와 함께 사용’을 선택해 로그인한 뒤, "
        "관리 화면에서 휴대폰 로그인이 유지되는지 확인하면 수집이 시작됩니다."
    )
    return True


def bridge_uid():
    # PackageManager's UID listing works across Android versions; dumpsys is diagnostic
    # output and Android 14 no longer emits the old userId field.
    listing = adb("shell", "pm", "list", "packages", "--user", "0", "-U", PKG)
    matches = re.findall(rf"^package:{re.escape(PKG)} uid:(\d+)$", listing, re.MULTILINE)
    if len(matches) != 1 or not 10000 <= int(matches[0]) < 100000:
        raise RuntimeError("keyboard_app_unavailable")
    return matches[0]


def ensure_keyboard_app():
    """Keep the keyboard app on the device at the build shipped in this image."""
    if not is_installed(PKG):
        return False
    paths = adb("shell", "pm", "path", PKG).splitlines()
    remote = paths[0].removeprefix("package:") if paths else ""
    if not re.fullmatch(r"/data/app/[A-Za-z0-9_=/+.~-]+\.apk", remote):
        raise RuntimeError("keyboard_app_unverified")
    with open("/opt/bridge.apk", "rb") as source:
        wanted = hashlib.file_digest(source, "sha256").hexdigest()
    if adb("shell", "sha256sum", remote).split()[:1] == [wanted]:
        return False
    keyboard = adb("shell", "settings", "get", "secure", "default_input_method")
    # Same signing key, so Android keeps the app's data and permissions.
    adb("install", "-r", "/opt/bridge.apk", timeout=120)
    if keyboard.startswith(PKG + "/"):
        adb("shell", "ime", "enable", IME)
        adb("shell", "ime", "set", IME)
    return True


def main():
    parser = argparse.ArgumentParser(description="KakaoTalk Bridge 기기 작업")
    parser.add_argument(
        "command", choices=["watch", "iris-watch", "web-ui", "bootstrap", "probe", "approve"]
    )
    parser.add_argument(
        "--phone-session-active",
        action="store_true",
        help="태블릿 로그인 뒤 휴대폰의 카카오톡 로그인이 유지되는 것을 직접 확인함",
    )
    parser.add_argument(
        "--rotate-epoch",
        action="store_true",
        help="Android 상태 복구 후 새 식별자 세대 시작",
    )
    args = parser.parse_args()
    command = args.command
    if command == "web-ui":
        import uvicorn

        uvicorn.run(
            "webui.app:create_app",
            factory=True,
            host="0.0.0.0",
            port=8080,
            access_log=False,
            proxy_headers=False,
        )
    elif command == "iris-watch":
        from device.iris import watch

        watch()
    elif command == "probe":
        print(json.dumps(sample()))
    elif command == "bootstrap":
        bootstrap(args.rotate_epoch)
    elif command == "approve":
        from device import enrollment

        connect()
        enrollment.approve(args.phone_session_active)
        print("수집을 승인했습니다. 휴대폰 로그인 상태는 자동으로 감시하지 않습니다.")
    else:
        keyboard_checked = False
        while True:
            payload = sample()
            if payload.get("bridge_installed") and not keyboard_checked:
                keyboard_checked = True
                try:
                    if ensure_keyboard_app():
                        print(json.dumps({"keyboard_app": "updated"}), flush=True)
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    print(json.dumps({"keyboard_app": "update_failed"}), flush=True)
            try:
                report(payload)
                print(json.dumps({"state": payload["state"], "reported": True}), flush=True)
            except (OSError, URLError, ValueError, RuntimeError):
                print(json.dumps({"state": payload["state"], "reported": False}), flush=True)
            time.sleep(30)


if __name__ == "__main__":
    from device.messages import message

    try:
        main()
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        code = str(exc) if re.fullmatch(r"[a-z_]{3,64}", str(exc)) else None
        raise SystemExit(message(exc) + (f" ({code})" if code else "")) from None
