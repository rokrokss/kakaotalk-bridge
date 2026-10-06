"""Small server-rendered pages; authentication stays in auth.py."""

from html import escape

from fastapi.responses import HTMLResponse

LINK_COOKIE = "__Host-kakao-link"


def browser_page(body, redirect="", *, status_code=200):
    response = HTMLResponse(body, status_code=status_code)
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; img-src 'self'; "
        f"form-action 'self' {redirect}; frame-ancestors 'none'; base-uri 'none'"
    )
    return response


# Shown on browser routes instead of OAuth error codes.
BROWSER_ERRORS = {
    "invalid_approval": "승인 요청이 만료되었거나 이미 처리되었습니다. AI 앱에서 연결을 다시 시작하세요.",
    "approval_required": "서버 소유자의 승인이 필요합니다. 관리 화면의 ‘AI 연결’에서 요청을 승인한 뒤 다시 시도하세요.",
    "passkey_login_required": "패스키로 로그인해야 합니다. 이 페이지를 새로고침한 뒤 다시 시도하세요.",
    "consent_required": "연결하려면 이 화면에서 허용을 선택해야 합니다.",
    "invalid_origin": "다른 주소에서 보낸 요청이라 거부했습니다. 이 서버 주소에서 연결을 다시 시작하세요.",
    "invalid_link_key": "연결 키가 올바르지 않습니다. 관리 화면에서 새 연결 링크를 받으세요.",
    "slow_down": "요청이 너무 잦습니다. 잠시 후 다시 시도하세요.",
    "registration_limit": "연결 등록 한도를 넘었습니다. 잠시 후 다시 시도하세요.",
    "passkey_disabled": "이 서버는 패스키 승인을 사용하지 않습니다.",
    "tunnel_not_approved_or_expired": "개인 터널이 승인되지 않았거나 만료되었습니다. 관리 화면에서 다시 승인하세요.",
    "metadata_fetch_failed": "AI 앱 정보를 가져오지 못했습니다. 잠시 후 다시 시도하세요.",
}
BROWSER_ERROR = "AI 앱의 연결 요청을 처리하지 못했습니다. AI 앱에서 연결을 다시 추가하세요."


def error_page(reason, *, status_code):
    text = BROWSER_ERRORS.get(reason, BROWSER_ERROR)
    response = browser_page(
        page("연결하지 못했습니다", f"<h1>연결하지 못했습니다</h1><p>{escape(text)}</p>"),
        status_code=status_code,
    )
    # Only approval forms need a same-origin referrer.
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def page(title, body):
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · KakaoTalk Bridge</title>
  <link rel="icon" type="image/svg+xml" href="/assets/logo.svg?v=cc464e4">
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
  <header><img src="/assets/logo.svg?v=cc464e4" width="28" height="28" alt="">KakaoTalk Bridge</header>
  <main>{body}</main>
</body>
</html>"""
