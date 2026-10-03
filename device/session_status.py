"""Bounded session evidence, never proof of a remote phone's live session."""

import math
import time
import xml.etree.ElementTree as ET

from device.login_guard import KAKAO, inspect_option


def screen_evidence(xml):
    """Return enums only; never return account names, input values or chat text."""
    unknown = {"state": "unknown", "secondary_option": "unknown"}
    if len(xml) > 2 * 1024 * 1024:
        return unknown
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return unknown
    nodes = [n for n in root.iter("node") if n.get("package") == KAKAO]
    if not nodes:
        return {**unknown, "state": "not_visible"}
    if any(n.get("class", "").endswith("EditText") for n in nodes) and any(
        n.get("text") == "로그인" and n.get("clickable") == "true" for n in nodes
    ):
        try:
            inspect_option(xml)
            selected = "selected"
        except RuntimeError:
            selected = "not_verified"
        return {"state": "login_required", "secondary_option": selected}
    # Recognize an explicit tab bar only. Generic chat text is not login evidence.
    for parent in nodes:
        if parent.get("class") != "android.widget.TabWidget":
            continue
        tabs = {
            n.get("text") or n.get("content-desc")
            for n in parent.iter("node")
            if n.get("package") == KAKAO and n.get("clickable") == "true"
        }
        if {"친구", "채팅", "더보기"} <= tabs:
            return {**unknown, "state": "main_screen_observed"}
    return unknown


def timestamp(value, now):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value <= now
    ):
        return value
    return None


def enrollment_evidence(config, proof, signature, now=None):
    now = time.time() if now is None else now
    matches = bool(signature) and (
        config.get("collector_mode") == "iris"
        and config.get("secondary_login_version", 0) == signature["kakao_version"]
        and config.get("device_fingerprint") == signature["fingerprint"]
    )
    checked = timestamp(proof.get("checked_at"), now)
    proof_matches = bool(signature) and (
        proof.get("epoch") == config.get("enrollment_epoch") and proof.get("signature") == signature
    )
    precheck = "missing"
    if proof:
        precheck = "valid" if checked and proof_matches and now - checked <= 1800 else "expired"
    phone_at = timestamp(config.get("phone_session_confirmed_at"), now)
    tablet_at = timestamp(config.get("tablet_session_confirmed_at", phone_at), now)
    report_at = timestamp(config.get("phone_session_reported_at"), now)
    if config.get("phone_session_report") == "lost" and report_at:
        phone = "reported_lost"
    elif matches and phone_at:
        phone = "operator_confirmed" if now - phone_at <= 86400 else "recheck_due"
    else:
        phone = "unknown"
    return {
        "collection_approval": "unknown" if not signature else "approved" if matches else "locked",
        "precheck": {
            "state": precheck,
            "checked_at": checked,
            "expires_at": checked + 1800 if checked else None,
        },
        "tablet": {
            "state": "operator_confirmed" if matches and tablet_at else "unknown",
            "confirmed_at": tablet_at if matches else None,
        },
        "phone": {
            "state": phone,
            "confirmed_at": phone_at,
            "reported_at": report_at,
            "automatic": False,
        },
    }
