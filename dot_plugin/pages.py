"""Small server-rendered pages; authentication stays in auth.py."""

from html import escape


def page(title, body):
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · KakaoTalk MCP</title>
  <link rel="icon" type="image/svg+xml" href="/assets/logo.svg">
  <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
  <header><img src="/assets/logo.svg" width="28" height="28" alt="">KakaoTalk MCP</header>
  <main>{body}</main>
</body>
</html>"""
