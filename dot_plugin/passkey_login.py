"""Public WebAuthn assertions bound to one pending OAuth request; no enrollment routes."""

import html

from fastapi import Request

from dot_plugin.pages import LINK_COOKIE, browser_page, page


def install_routes(app, auth):
    from dot_plugin.auth import AuthError, digest, redirect_origin

    def enabled(request):
        if auth.config.approval_mode != "passkey":
            raise AuthError("passkey_disabled", 404)
        if "https://" + request.headers.get("host", "") != auth.config.public_url:
            raise AuthError("invalid_origin", 403)

    @app.post("/authorize/passkey/{operation}")
    async def assertion(operation: str, request: Request):
        enabled(request)
        auth.rate("passkey", 20)
        if request.headers.get("origin") != auth.config.public_url:
            raise AuthError("invalid_origin", 403)
        if operation not in {"options", "verify"}:
            raise AuthError("invalid_request", 404)
        try:
            body = await request.json()
            ticket = body["ticket"]
            cookie = request.cookies.get(LINK_COOKIE, "")
            record = auth.approval(ticket, cookie)
            if record["status"] != "pending":
                raise AuthError("invalid_approval", 403)
            data = {
                "origin": auth.config.public_url,
                "browser": cookie,
                "purpose": "mcp",
                "context": ticket,
            }
            if operation == "options":
                return auth.passkey_call("authenticate_options", data)
            result = auth.passkey_call(
                "authenticate_verify",
                {**data, "flow": body["flow"], "credential": body["credential"]},
            )
        except (ValueError, TypeError, KeyError):
            raise AuthError("invalid_passkey", 400) from None
        with auth.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            record = auth.approval(ticket, cookie, db=db)
            if record["status"] != "pending" or result["policy"] != auth.policy():
                raise AuthError("invalid_approval", 403)
            record.update(status="authenticated", policy=result["policy"])
            auth.state.put("approval", digest(ticket), record, db=db)
            auth.state.put("consent", digest(cookie), {"ticket": ticket}, db=db)
        return {"url": "/authorize/passkey/consent"}

    @app.get("/authorize/passkey/consent")
    def consent(request: Request):
        enabled(request)
        cookie = request.cookies.get(LINK_COOKIE, "")
        saved = auth.state.get("consent", digest(cookie))
        ticket = saved["ticket"] if saved else ""
        record = auth.approval(ticket, cookie)
        if record["status"] != "authenticated" or record.get("policy") != auth.policy():
            raise AuthError("passkey_login_required", 403)
        esc = html.escape
        redirect = redirect_origin(record["query"]["redirect_uri"])
        return browser_page(
            page(
                "연결 허용",
                f'''<h1>연결을 허용할까요?</h1>
<p><strong>{esc(record["client_name"])}</strong>가 이 KakaoTalk Bridge에 접근하도록 허용할까요?</p>
<p class="hint">클라이언트: {esc(record["query"]["client_id"])}<br>돌아갈 주소: {esc(redirect)}</p>
{auth.permissions(record["scope"])}
<form method="post" action="/authorize"><input type="hidden" name="ticket" value="{esc(ticket)}">
<button type="submit" name="decision" value="allow">연결 허용</button>
<button type="submit" name="decision" value="deny">취소</button></form>
<p class="hint">연결만으로 이벤트 구독이나 자동 작업이 생성되지는 않습니다.</p>''',
            ),
            redirect,
        )
