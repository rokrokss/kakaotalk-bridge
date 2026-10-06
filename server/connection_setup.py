"""Shared, dependency-free input contract for the finite host setup service."""

import re
from urllib.parse import urlsplit

METHODS = {"none", "stdio", "https", "tailscale", "openai-tunnel", "check"}


def validate(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("method"), str)
        or data["method"] not in METHODS
    ):
        raise ValueError("지원하는 연결 방식을 선택하세요.")
    allowed = {"method", "request_id"} | {
        "https": {"url"},
        "tailscale": {"install_tailscale"},
        "openai-tunnel": {"tunnel_id", "api_key", "approve"},
    }.get(data["method"], set())
    if set(data) - allowed or not re.fullmatch(
        r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(data.get("request_id", ""))
    ):
        raise ValueError("설정 요청이 올바르지 않습니다. 페이지를 새로고침한 뒤 다시 시도하세요.")
    if data["method"] == "https":
        value = data.get("url")
        if not isinstance(value, str) or len(value) > 253:
            raise ValueError("공개 HTTPS 주소를 입력하세요.")
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
            or (url.port is not None and not 1 <= url.port <= 65535)
            or not re.fullmatch(r"https://[a-z0-9.-]+(?::[0-9]{1,5})?", value)
        ):
            raise ValueError("경로나 끝의 / 없이 https://로 시작하는 주소만 입력하세요.")
    if data["method"] == "tailscale" and data.get("install_tailscale") is not True:
        raise ValueError("계속하려면 Tailscale 설치와 Funnel 공개 접속을 허용하세요.")
    if data["method"] == "openai-tunnel":
        if not re.fullmatch(r"tunnel_[a-z0-9]{32}", str(data.get("tunnel_id", ""))):
            raise ValueError("OpenAI에서 발급한 터널 ID를 입력하세요.")
        if data.get("approve") is not True:
            raise ValueError("이 개인 터널이 수집한 메시지에 접근하도록 허용해야 합니다.")
        key = data.get("api_key", "")
        if not isinstance(key, str) or (key and not re.fullmatch(r"[A-Za-z0-9_-]{20,512}", key)):
            raise ValueError("올바른 실행용 API 키를 입력하세요.")
    return dict(data)
