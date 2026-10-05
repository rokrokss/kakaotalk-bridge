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
