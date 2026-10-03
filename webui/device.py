"""Allowlisted Android controls. User text travels through a private temporary file."""

import json
import os
import re
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from device import cli, login_guard, session_status

IME = f"{cli.PKG}/.WebInputMethod"
KEYS = {"back": "4", "home": "3", "enter": "66", "delete": "67", "tab": "61", "wake": "224"}


class Android:
    def screenshot(self):
        cli.connect()
        result = subprocess.run(
            ["adb", "-s", os.getenv("ADB_TARGET", "redroid:5555"), "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        data = result.stdout
        if (
            result.returncode
            or len(data) < 24
            or len(data) > 16 * 1024 * 1024
            or data[:8] != b"\x89PNG\r\n\x1a\n"
        ):
            raise RuntimeError("screen_unavailable")
        width, height = struct.unpack(">II", data[16:24])
        if not (1 <= width <= 8192 and 1 <= height <= 8192):
            raise RuntimeError("screen_unavailable")
        return data, width, height

    def tap(self, x, y):
        cli.adb("shell", "input", "tap", str(x), str(y))

    def swipe(self, x, y, end_x, end_y, duration):
        cli.adb("shell", "input", "swipe", str(x), str(y), str(end_x), str(end_y), str(duration))

    def key(self, name):
        cli.adb("shell", "input", "keyevent", KEYS[name])

    def open_kakao(self):
        cli.connect()
        # Resolve only the installed Kakao launcher; never expose arbitrary package/component input.
        component = cli.adb(
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "com.kakao.talk",
        ).splitlines()[-1]
        if not re.fullmatch(r"com\.kakao\.talk/[A-Za-z0-9_.$]+", component):
            raise RuntimeError("kakao_not_installed")
        cli.adb("shell", "am", "start", "-n", component)

    def enable_keyboard(self):
        cli.adb("shell", "ime", "enable", IME)
        cli.adb("shell", "ime", "set", IME)
        if cli.adb("shell", "settings", "get", "secure", "default_input_method") != IME:
            raise RuntimeError("keyboard_unavailable")

    def text(self, text):
        # Keyboard activation is a separate action, before the operator focuses the input field.
        if cli.adb("shell", "settings", "get", "secure", "default_input_method") != IME:
            raise RuntimeError("keyboard_unavailable")
        uid = cli.bridge_uid()
        nonce = uuid.uuid4().hex
        directory = f"/data/user/0/{cli.PKG}/files"
        remote = f"/data/local/tmp/collector-web-{nonce}"
        pending, receipt = f"{directory}/web-input.json", f"{directory}/web-input-result.json"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps({"nonce": nonce, "text": text}), encoding="utf-8")
            path.chmod(0o600)
            try:
                # Create a private file before pushing, eliminating a world-readable upload window.
                cli.adb("shell", "sh", "-c", f"'umask 077; touch {remote}'")
                cli.adb("push", str(path), remote)
                cli.adb("shell", "chmod", "600", remote)
                cli.adb("shell", "rm", "-f", receipt)
                cli.adb("shell", "cp", remote, pending)
                cli.adb("shell", "chown", f"{uid}:{uid}", pending)
                cli.adb("shell", "chmod", "600", pending)
                cli.adb("shell", "restorecon", pending)
                cli.adb(
                    "shell",
                    "am",
                    "broadcast",
                    "--receiver-foreground",
                    "-a",
                    "dev.kakaocollector.bridge.WEB_TEXT",
                    "-p",
                    cli.PKG,
                )
                for _ in range(10):
                    raw = cli.adb("shell", "cat", receipt, check=False)
                    try:
                        result = json.loads(raw)
                    except ValueError:
                        result = {}
                    if result.get("nonce") == nonce:
                        if result.get("committed") is True:
                            return
                        raise RuntimeError("focus_kakao_input")
                    time.sleep(0.1)
                # Do not auto-retry a timed-out input: it may already have been committed.
                raise RuntimeError("input_result_unknown")
            finally:
                cli.adb("shell", "rm", "-f", remote, pending, receipt, check=False)

    def bootstrap(self):
        cli.bootstrap()
        self.enable_keyboard()

    def login_check(self):
        cli.login_check()

    def confirm(self, phone, tablet):
        cli.confirm_secondary(phone, tablet)

    def session_status(self):
        result = {
            "checked_at": time.time(),
            "device": "offline",
            "screen": {"state": "unknown", "secondary_option": "unknown"},
            **session_status.enrollment_evidence({}, {}, None),
        }
        try:
            state = cli.sample()
            result["device"] = state["state"]
            if state["state"] not in ("android_ready", "needs_setup"):
                return result
            if not state.get("kakao_installed"):
                result["screen"]["state"] = "not_installed"
                return result
            try:
                config = json.loads(cli.adb("shell", "cat", cli.REMOTE_CONFIG))
                signature = login_guard.device_signature(cli.adb)
                proof_path = Path("/state/prelogin.json")
                proof = json.loads(proof_path.read_text()) if proof_path.exists() else {}
                result.update(session_status.enrollment_evidence(config, proof, signature))
            except (
                OSError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
                subprocess.TimeoutExpired,
            ):
                pass
            # The UI tree can contain private text. Use a private directory and delete it
            # in finally; only classifications leave this function, never the raw tree.
            directory = "/data/local/tmp/collector-session-" + uuid.uuid4().hex
            path = directory + "/window.xml"
            try:
                cli.adb("shell", "mkdir", "-m", "700", directory)
                cli.adb("shell", "uiautomator", "dump", path, timeout=12)
                result["screen"] = session_status.screen_evidence(cli.adb("shell", "cat", path))
            finally:
                cli.adb("shell", "rm", "-rf", directory, check=False)
        except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired):
            pass
        # Timestamp records completion, not start, of the potentially slow inspection.
        result["checked_at"] = time.time()
        return result

    def record_phone(self, active):
        cli.connect()
        config = json.loads(cli.adb("shell", "cat", cli.REMOTE_CONFIG))
        if active:
            evidence = session_status.enrollment_evidence(
                config, {}, login_guard.device_signature(cli.adb)
            )
            if (
                evidence["collection_approval"] != "approved"
                or not evidence["phone"]["confirmed_at"]
            ):
                raise RuntimeError("secondary_confirmation_required")
            config["phone_session_confirmed_at"] = time.time()
        else:
            config["secondary_login_version"] = 0
        config["phone_session_report"] = "active" if active else "lost"
        config["phone_session_reported_at"] = time.time()
        cli.provision_file(config)
        if not active:
            Path("/state/prelogin.json").unlink(missing_ok=True)
            # The enrollment gate is already revoked. The collector also checks it
            # before each upload; stopping our process accelerates the shutdown.
            from device import iris

            iris.stop()
