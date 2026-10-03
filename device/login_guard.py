"""Conservative pre-login UI checks. Never clicks, types, or submits credentials."""

import re
import time
import xml.etree.ElementTree as ET

KAKAO = "com.kakao.talk"
OPTION = "다른 기기와 함께 사용"


def inspect_option(xml: str):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise RuntimeError("BLOCKED: unreadable login UI; do not log in") from None
    parents = {child: parent for parent in root.iter() for child in parent}
    nodes = [n for n in root.iter("node") if n.get("package") == KAKAO]
    if not any(n.get("class", "").endswith("EditText") for n in nodes) or not any(
        n.get("text") == "로그인" and n.get("clickable") == "true" for n in nodes
    ):
        raise RuntimeError("BLOCKED: cannot identify the supported Korean login screen")
    labels = [
        n
        for n in root.iter("node")
        if n.get("package") == KAKAO
        and OPTION in " ".join((n.get("text", "") + " " + n.get("content-desc", "")).split())
    ]
    if len(labels) != 1:
        raise RuntimeError("BLOCKED: secondary-device option missing or ambiguous; do not log in")
    label = labels[0]
    # Match the label itself or its immediate row, never an unrelated screen-wide checkbox.
    row = label if label.get("checkable") == "true" else parents.get(label)
    checks = (
        []
        if row is None
        else [
            n
            for n in row.iter("node")
            if n.get("package") == KAKAO and n.get("checkable") == "true"
        ]
    )
    if len(checks) != 1 or checks[0].get("checked") != "true" or checks[0].get("enabled") != "true":
        raise RuntimeError(
            "BLOCKED: cannot prove the secondary-device option is selected; do not log in"
        )


def device_signature(adb):
    if "tablet" not in adb("shell", "getprop", "ro.build.characteristics").split(","):
        raise RuntimeError("BLOCKED: Android build characteristics are not tablet")
    sizes = re.findall(r"(\d+)x(\d+)", adb("shell", "wm", "size"))
    densities = re.findall(r"density:\s*(\d+)", adb("shell", "wm", "density"))
    if not sizes or not densities or int(densities[-1]) <= 0:
        raise RuntimeError("BLOCKED: cannot inspect tablet display settings")
    width, height = map(int, sizes[-1])
    dpi = int(densities[-1])
    if min(width, height) * 160 / dpi < 600:
        raise RuntimeError("BLOCKED: display smallest width is below 600dp")
    version = re.search(r"versionCode=(\d+)", adb("shell", "dumpsys", "package", KAKAO))
    fingerprint = adb("shell", "getprop", "ro.build.fingerprint")
    if not version or not fingerprint:
        raise RuntimeError("BLOCKED: installed KakaoTalk/build identity is unknown")
    return {
        "kakao_version": int(version[1]),
        "fingerprint": fingerprint,
        "width": width,
        "height": height,
        "dpi": dpi,
    }


def prelogin(adb):
    signature = device_signature(adb)
    path = "/data/local/tmp/kakaocollector-login-check.xml"
    try:
        adb("shell", "uiautomator", "dump", path)
        inspect_option(adb("shell", "cat", path))
    finally:
        adb("shell", "rm", "-f", path, check=False)
    return {"checked_at": time.time(), "signature": signature}


def confirm(proof, signature, phone_active, tablet_active):
    age = time.time() - proof.get("checked_at", 0)
    if not 0 <= age <= 1800 or proof.get("signature") != signature:
        raise RuntimeError(
            "BLOCKED: pre-login check expired or device/app changed; re-check before logging in"
        )
    if not phone_active or not tablet_active:
        raise RuntimeError(
            "BLOCKED: operator must verify both phone and tablet sessions remain active"
        )
    return {
        "secondary_login_version": signature["kakao_version"],
        "device_fingerprint": signature["fingerprint"],
        "phone_session_confirmed_at": time.time(),
        "tablet_session_confirmed_at": time.time(),
        "phone_session_report": "active",
        "phone_session_reported_at": time.time(),
    }
