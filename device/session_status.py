"""Bounded session evidence, never proof of a remote phone's live session."""

import math
import time
import xml.etree.ElementTree as ET

from device import enrollment

KAKAO = "com.kakao.talk"
OPTION = "다른 기기와 함께 사용"


def option_selected(root) -> bool:
    """Whether the Korean login screen has the secondary-device option checked."""
    parents = {child: parent for parent in root.iter() for child in parent}
    labels = [
        n
        for n in root.iter("node")
        if n.get("package") == KAKAO
        and OPTION in " ".join((n.get("text", "") + " " + n.get("content-desc", "")).split())
    ]
    if len(labels) != 1:
        return False
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
    return (
        len(checks) == 1
        and checks[0].get("checked") == "true"
        and checks[0].get("enabled") == "true"
    )


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
        selected = "selected" if option_selected(root) else "not_verified"
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


def evidence(snap, now=None):
    """Approval and login state for the admin screen. Never returns account IDs."""
    now = time.time() if now is None else now
    if snap is None:
        return {
            "collection_approval": "unknown",
            "approval_reason": None,
            "kakao": {"login": "unknown", "version": None},
            "approved_at": None,
            "phone": {
                "state": "unknown",
                "confirmed_at": None,
                "reported_at": None,
                "automatic": False,
            },
        }
    config = snap.config or {}
    state, reason = enrollment.approval(snap)
    user, login = enrollment.account(snap)
    phone_at = timestamp(config.get("phone_session_confirmed_at"), now)
    report_at = timestamp(config.get("phone_session_reported_at"), now)
    if config.get("phone_session_report") == "lost" and report_at:
        phone = "reported_lost"
    elif state == "approved" and phone_at:
        phone = "operator_confirmed" if now - phone_at <= 86400 else "recheck_due"
    else:
        phone = "unknown"
    return {
        "collection_approval": state,
        "approval_reason": reason,
        "kakao": {"login": "logged_in" if user else login, "version": snap.kakao_version},
        "approved_at": timestamp(config.get("approved_at"), now) if state == "approved" else None,
        "phone": {
            "state": phone,
            "confirmed_at": phone_at,
            "reported_at": report_at,
            "automatic": False,
        },
    }
