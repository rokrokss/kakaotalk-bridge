"""Fixed-purpose ADB tasks. No external command endpoint and no Docker socket."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from device import login_guard, session_status

PKG = "dev.kakaocollector.bridge"
REMOTE_CONFIG = f"/data/user/0/{PKG}/files/enrollment.json"


def adb(*args, timeout=25, check=True):
    result = subprocess.run(
        ["adb", "-s", os.getenv("ADB_TARGET", "redroid:5555"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError("ADB operation failed; inspect device connectivity")
    return result.stdout.strip()


def connect():
    subprocess.run(
        ["adb", "connect", os.getenv("ADB_TARGET", "redroid:5555")],
        capture_output=True,
        timeout=15,
        check=False,
    )


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
            raise RuntimeError("Device status not committed")


def bootstrap(rotate_epoch=False, *, preserve=False):
    print("Waiting for Android boot (up to 180 seconds).", flush=True)
    deadline = time.monotonic() + 180
    while sample()["state"] in ("offline", "booting"):
        if time.monotonic() >= deadline:
            raise RuntimeError("Android did not boot; check binder/kernel compatibility")
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
        raise RuntimeError("Bootstrap requires root ADB in the dedicated redroid instance")
    state = Path("/state/enrollment.json")
    has_config = (
        adb("shell", "sh", "-c", f"'test -f {REMOTE_CONFIG} && echo present'", check=False)
        == "present"
    )
    if has_config and not state.exists() and not rotate_epoch:
        raise RuntimeError(
            "Device has enrollment but host state is missing; restore device-state first"
        )
    if preserve and has_config:
        remote = json.loads(adb("shell", "cat", REMOTE_CONFIG))
        identity = json.loads(state.read_text())
        if identity.get("enrollment_epoch") != remote.get("enrollment_epoch") or identity.get(
            "device_id"
        ) != os.getenv("DEVICE_ID", "personal-tablet"):
            raise RuntimeError("Enrollment mismatch; restore matching state")
        return False
    if preserve:
        from device.setup import verify_installed_kakao, verify_kakao

        if not is_installed("com.kakao.talk"):
            supplied = sorted(Path("/inputs/kakao").glob("*.apk"))
            if not supplied:
                raise RuntimeError(
                    "Install KakaoTalk in Aurora or import the official APK set first"
                )
            verify_kakao(supplied)
            adb("install-multiple", *map(str, supplied), timeout=180)
        verify_installed_kakao()
    if not state.exists():
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(
            json.dumps(
                {
                    "device_id": os.getenv("DEVICE_ID", "personal-tablet"),
                    "enrollment_epoch": str(uuid.uuid4()),
                }
            )
        )
        state.chmod(0o600)
    identity = json.loads(state.read_text())
    if identity["device_id"] != os.getenv("DEVICE_ID", "personal-tablet"):
        raise RuntimeError("DEVICE_ID changed; restore matching configuration")
    if rotate_epoch:
        identity["enrollment_epoch"] = str(uuid.uuid4())
        state.write_text(json.dumps(identity))
    if not has_config and is_installed(PKG):
        # A preinstalled but never enrolled Bridge is permitted. Its empty outbox has no epoch.
        print("Existing Bridge will be enrolled; existing app data is retained.")
    apks = sorted(Path("/inputs/kakao").glob("*.apk"))
    if apks and not preserve:
        print("Installing supplied KakaoTalk APK set (no login actions).")
        for apk in apks:
            with apk.open("rb") as source:
                print(f"APK SHA256 {hashlib.file_digest(source, 'sha256').hexdigest()}")
        adb("install-multiple", "-r", *map(str, apks), timeout=180)
    if not is_installed("com.kakao.talk"):
        raise RuntimeError("Place the official KakaoTalk APK/split set in inputs/kakao and rerun")
    adb("install", "-r", "/opt/bridge.apk", timeout=120)
    from device import iris

    iris.stop()
    adb("push", "/opt/iris.apk", iris.REMOTE_APK)
    adb("shell", "chmod", "444", iris.REMOTE_APK)
    ca = Path("/run/secrets/tls_cert").read_text()
    config = {
        **identity,
        "url": os.environ["BRIDGE_URL"],
        "token": Path("/run/secrets/ingest_token").read_text().strip(),
        "ca_pem": ca,
        "secondary_login_version": 0,
        "collector_mode": "iris",
    }
    provision(config)
    Path("/state/prelogin.json").unlink(missing_ok=True)
    print(
        "Setup complete. Collection is LOCKED. Before login run login-check on the selected secondary-device option."
    )
    print(
        "Never continue a primary-device transfer login. No KakaoTalk login action was performed."
    )
    return True


def bridge_uid():
    # PackageManager's UID listing works across Android versions; dumpsys is diagnostic
    # output and Android 14 no longer emits the old userId field.
    listing = adb("shell", "pm", "list", "packages", "--user", "0", "-U", PKG)
    matches = re.findall(rf"^package:{re.escape(PKG)} uid:(\d+)$", listing, re.MULTILINE)
    if len(matches) != 1 or not 10000 <= int(matches[0]) < 100000:
        raise RuntimeError("Cannot resolve Bridge app UID")
    return matches[0]


def provision_file(config):
    uid = bridge_uid()
    # Payload travels as a file, never as an ADB argument or logged shell command.
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "enrollment.json"
        file.write_text(json.dumps(config))
        file.chmod(0o600)
        remote = "/data/local/tmp/collector-enrollment.json"
        try:
            adb("push", str(file), remote)
            adb("shell", "chmod", "600", remote)
            directory = f"/data/user/0/{PKG}/files"
            adb("shell", "mkdir", "-p", directory)
            adb("shell", "chown", f"{uid}:{uid}", directory)
            adb("shell", "chmod", "700", directory)
            adb("shell", "cp", remote, REMOTE_CONFIG + ".tmp")
            adb("shell", "chown", f"{uid}:{uid}", REMOTE_CONFIG + ".tmp")
            adb("shell", "chmod", "600", REMOTE_CONFIG + ".tmp")
            adb("shell", "mv", REMOTE_CONFIG + ".tmp", REMOTE_CONFIG)
            adb("shell", "restorecon", "-R", directory)
        finally:
            adb("shell", "rm", "-f", remote, check=False)


def provision(config):
    provision_file(config)
    adb("shell", "am", "start", "-n", f"{PKG}/.SetupActivity")


def login_check():
    connect()
    config = json.loads(adb("shell", "cat", REMOTE_CONFIG))
    signature = login_guard.device_signature(adb)
    if (
        session_status.enrollment_evidence(config, {}, signature)["collection_approval"]
        == "approved"
    ):
        print("Collection is already approved. Use session-check to inspect its status.")
        return False
    # A failed inspection must leave the existing approval and proof untouched.
    proof = login_guard.prelogin(adb)
    proof["epoch"] = config["enrollment_epoch"]
    config["secondary_login_version"] = 0
    # Do not launch the Bridge Activity: the foreground KakaoTalk login UI must stay visible.
    provision_file(config)
    proof_path = Path("/state/prelogin.json")
    proof_path.write_text(json.dumps(proof))
    proof_path.chmod(0o600)
    print(
        "PASS: tablet configuration and selected secondary-login checkbox observed. No login was submitted."
    )
    print("After manual login, verify both devices stay logged in before confirm-secondary.")
    return True


def confirm_secondary(phone_active=False, tablet_active=False):
    connect()
    proof_path = Path("/state/prelogin.json")
    if not proof_path.exists():
        raise RuntimeError("BLOCKED: run login-check before attempting KakaoTalk login")
    config = json.loads(adb("shell", "cat", REMOTE_CONFIG))
    proof = json.loads(proof_path.read_text())
    if proof.get("epoch") != config["enrollment_epoch"]:
        raise RuntimeError("BLOCKED: enrollment changed since pre-login check")
    config.update(
        login_guard.confirm(proof, login_guard.device_signature(adb), phone_active, tablet_active)
    )
    if config.get("collector_mode") == "iris":
        # Iris observes this file directly. Opening Bridge here hides KakaoTalk and
        # makes a successful confirmation look like another setup step.
        provision_file(config)
    else:
        provision(config)
    proof_path.unlink()
    print(
        "Collection enabled based on operator confirmation of both sessions; ongoing phone status is not monitored."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "watch",
            "iris-watch",
            "web-ui",
            "bootstrap",
            "prepare",
            "configure",
            "probe",
            "login-check",
            "confirm-secondary",
        ],
    )
    parser.add_argument("--phone-session-active", action="store_true")
    parser.add_argument("--tablet-session-active", action="store_true")
    parser.add_argument(
        "--rotate-epoch",
        action="store_true",
        help="After restoring Android state, start a new identity epoch without clearing the outbox",
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
    elif command == "prepare":
        from device.setup import prepare

        print(json.dumps({"prepared": prepare()}))
    elif command == "configure":
        bootstrap(preserve=True)
    elif command == "bootstrap":
        bootstrap(args.rotate_epoch)
    elif command == "login-check":
        login_check()
    elif command == "confirm-secondary":
        confirm_secondary(args.phone_session_active, args.tablet_session_active)
    else:
        while True:
            payload = sample()
            try:
                report(payload)
                print(json.dumps({"state": payload["state"], "reported": True}), flush=True)
            except (OSError, URLError, ValueError, RuntimeError):
                print(json.dumps({"state": payload["state"], "reported": False}), flush=True)
            time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(str(exc)) from None
