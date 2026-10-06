"""Single-owner OAuth 2.1: PKCE, exact audience, CSRF-bound approval, rotating tokens."""

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.fernet import InvalidToken
from webauthn.helpers.exceptions import WebAuthnException

from dot_plugin import network
from dot_plugin.config import SCOPES
from dot_plugin.pages import page as render_page


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AuthError(Exception):
    def __init__(self, reason="invalid_request", status=400):
        self.reason, self.status = reason, status


def redirect_origin(uri):
    """Build an injection-safe CSP source for an already approved redirect URI."""
    try:
        if not isinstance(uri, str) or any(ord(c) <= 32 or ord(c) == 127 for c in uri):
            raise ValueError
        u = urlsplit(uri)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
            raise ValueError
        host = u.hostname.encode("idna").decode()
        if ":" in host:
            host = "[" + str(ipaddress.IPv6Address(host)) + "]"
        elif not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError
        port = f":{u.port}" if u.port and u.port != 443 else ""
        return "https://" + host + port
    except (ValueError, UnicodeError):
        raise AuthError("invalid_redirect_uri") from None


def grant_unexpired(grant, *, now=None):
    expires = grant.get("expires", 0)
    if grant.get("transport") == "tunnel" and expires is None:
        return True
    return isinstance(expires, (int, float)) and expires > (time.time() if now is None else now)


class OAuth:
    transport = "oauth"

    def __init__(self, config, state, passkeys=None):
        self.config, self.state = config, state
        from server.auth_migration import retire_social_login

        retire_social_login(state)
        from server.passkey_client import PasskeyClient

        self.passkeys = passkeys or PasskeyClient("public")
        self.rate_lock = threading.Lock()
        self.rates = defaultdict(deque)
        with state.transaction() as db:
            self.profile = state.get("settings", "profile", db=db)
            if not self.profile:
                self.profile = "prf_" + secrets.token_hex(16)
                state.put("settings", "profile", self.profile, db=db)

    def passkey_call(self, operation, data=None):
        try:
            return self.passkeys.call("public", operation, data)
        except (ValueError, TypeError, KeyError, WebAuthnException):
            raise AuthError("passkey_verification_failed", 400) from None
        except (OSError, RuntimeError):
            raise AuthError("passkey_unavailable", 503) from None

    def policy(self):
        if self.config.approval_mode == "admin":
            info = self.passkey_call("info")
            # Local admin consent must be revoked on passkey recovery/removal too.
            # Keep the legacy policy only for an unconfigured password/key owner.
            return "admin:" + info["policy"] if info["configured"] else "legacy:admin"
        return (
            self.passkey_call("info")["policy"]
            if self.config.approval_mode == "passkey"
            else "legacy:" + self.config.approval_mode
        )

    def rate(self, operation, count, period=60):
        with self.rate_lock:
            queue = self.rates[operation]
            now = time.time()
            while queue and queue[0] < now - period:
                queue.popleft()
            if len(queue) >= count:
                raise AuthError("slow_down", 429)
            queue.append(now)

    def challenge(self):
        return f'Bearer resource_metadata="{self.config.public_url}/.well-known/oauth-protected-resource/mcp", scope="{SCOPES}"'

    def metadata(self):
        base = self.config.public_url
        return {
            "issuer": base,
            "authorization_endpoint": base + "/authorize",
            "token_endpoint": base + "/token",
            "registration_endpoint": base + "/register",
            "revocation_endpoint": base + "/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "authorization_response_iss_parameter_supported": True,
            "client_id_metadata_document_supported": True,
            "scopes_supported": SCOPES.split(),
        }

    def register(self, meta):
        redirects = meta.get("redirect_uris")
        method = meta.get("token_endpoint_auth_method", "none")
        if method not in ("none", "client_secret_post", "client_secret_basic"):
            raise AuthError("invalid_client_metadata")
        if not isinstance(redirects, list) or not 1 <= len(redirects) <= 8:
            raise AuthError("invalid_redirect_uri")
        for raw in redirects:
            if not isinstance(raw, str) or len(raw) > 2048:
                raise AuthError("invalid_redirect_uri")
            redirect_origin(raw)
        client = {
            "redirect_uris": redirects,
            "token_endpoint_auth_method": method,
            "client_name": str(meta.get("client_name", "MCP client"))[:100],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": SCOPES,
            "client_id_issued_at": int(time.time()),
        }
        public = dict(client)
        if method != "none":
            secret = secrets.token_urlsafe(32)
            client["secret_hash"] = digest(secret)
            public.update(client_secret=secret, client_secret_expires_at=0)
        # Anonymous registration must not consume a shared persistent quota.
        # Seal metadata into an opaque client ID; only owner-approved clients persist.
        encoded = json.dumps(client, separators=(",", ":")).encode()
        if len(encoded) > 4096:
            raise AuthError("invalid_client_metadata")
        public["client_id"] = "reg_" + self.state.crypto.encrypt(b"dcr-v1:" + encoded).decode()
        return public

    def registration(self, client_id):
        try:
            if len(client_id) > 6000 or not client_id.startswith("reg_"):
                raise ValueError
            raw = self.state.crypto.decrypt(client_id[4:].encode(), ttl=600)
            if not raw.startswith(b"dcr-v1:"):
                raise ValueError
            return {**json.loads(raw[7:]), "client_id": client_id}
        except (ValueError, TypeError, InvalidToken):
            raise AuthError("invalid_client", 401) from None

    def client(self, client_id):
        if not isinstance(client_id, str) or len(client_id) > 6000:
            raise AuthError("invalid_client", 401)
        client = self.state.get("client", client_id)
        if client and client.get("metadata_expires", time.time() + 1) > time.time():
            return client
        if client_id.startswith("reg_"):
            return self.registration(client_id)
        # Only OpenAI's documented CIMD endpoint is accepted; failed fetches never
        # grant wildcard redirect access. DCR remains available as a fallback.
        if client_id == "https://chatgpt.com/oauth/client.json":
            status, data = network.public_request(client_id)
            try:
                doc = json.loads(data)
                redirects = doc["redirect_uris"]
                methods = doc.get(
                    "token_endpoint_auth_methods_supported",
                    [doc.get("token_endpoint_auth_method", "none")],
                )
                if (
                    status != 200
                    or doc["client_id"] != client_id
                    or not isinstance(redirects, list)
                    or not redirects
                    or "none" not in methods
                ):
                    raise ValueError
                for uri in redirects:
                    url = urlsplit(uri)
                    if (
                        url.scheme != "https"
                        or url.hostname != "chatgpt.com"
                        or url.username
                        or url.password
                        or url.fragment
                    ):
                        raise ValueError
            except (ValueError, KeyError, TypeError):
                raise AuthError("invalid_client", 401) from None
            client = {
                "client_id": client_id,
                "redirect_uris": redirects,
                "token_endpoint_auth_method": "none",
                "client_name": "ChatGPT",
                "metadata_expires": time.time() + 3600,
            }
            self.state.put("client", client_id, client)
            return client
        raise AuthError("invalid_client", 401)

    @staticmethod
    def permissions(scope):
        permissions = []
        if "kakao.read" in scope.split():
            permissions.append("<li>저장된 메시지 조회·검색 및 수집 상태 확인</li>")
        if "kakao.events" in scope.split():
            permissions.append("<li>요청한 새 메시지 이벤트 구독 및 처리 진행 상황 기록</li>")
        if "kakao.send" in scope.split():
            permissions.append("<li>내 카카오톡 계정으로 기존 대화방에 텍스트 메시지 전송</li>")
        return (
            "<ul>" + "".join(permissions) + "</ul>"
            "<p>조회한 메시지는 연결된 클라이언트와 공유됩니다. "
            "기기 조작 권한은 포함되지 않습니다.</p>"
        )

    def approval(self, ticket, cookie, *, db=None):
        record = self.state.get("approval", digest(ticket), db=db)
        if (
            not record
            or record["expires"] <= time.time()
            or record.get("mode", self.config.approval_mode) != self.config.approval_mode
            or not hmac.compare_digest(record["cookie"], digest(cookie or ""))
        ):
            raise AuthError("invalid_approval", 403)
        return record

    def authorize(self, query):
        self.rate("authorize_get", 30)
        if self.config.approval_mode == "passkey":
            info = self.passkey_call("info")
            if not info["registered"] or info["public_origin"] != self.config.public_url:
                raise AuthError("passkey_not_configured", 503)
        client = self.client(query.get("client_id"))
        if (
            query.get("redirect_uri") not in client["redirect_uris"]
            or query.get("response_type") != "code"
        ):
            raise AuthError()
        if query.get("resource") != self.config.resource:
            raise AuthError("invalid_target")
        scope = query.get("scope", SCOPES)
        if not scope or not set(scope.split()) <= set(SCOPES.split()):
            raise AuthError("invalid_scope")
        if query.get("code_challenge_method") != "S256" or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", query.get("code_challenge", "")
        ):
            raise AuthError("invalid_request")
        if len(query.get("state", "")) > 4096:
            raise AuthError()
        ticket, cookie = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, row in self.state.all("approval", db=db):
                if row["expires"] <= time.time():
                    self.state.delete("approval", key, db=db)
                    self.state.delete("consent", row["cookie"], db=db)
            if len(self.state.all("approval", db=db)) >= 100:
                raise AuthError("slow_down", 429)
            self.state.put(
                "approval",
                digest(ticket),
                {
                    "query": {
                        k: query.get(k, "")
                        for k in (
                            "client_id",
                            "redirect_uri",
                            "code_challenge",
                            "state",
                            "resource",
                        )
                    },
                    "scope": scope,
                    "client_name": client["client_name"],
                    "display_code": secrets.token_hex(4).upper(),
                    "status": "pending",
                    "mode": self.config.approval_mode,
                    "policy": self.policy() if self.config.approval_mode == "admin" else None,
                    "cookie": digest(cookie),
                    "expires": time.time() + 600,
                },
                db=db,
            )
        esc = html.escape
        if self.config.approval_mode == "passkey":
            return (
                render_page(
                    "KakaoTalk Bridge 연결",
                    f'''<h1>KakaoTalk Bridge 연결</h1>
<p>본인 인증 후 <strong>{esc(client["client_name"])}</strong>의 접근 권한을 확인하세요.</p>
<form id="passkey-mcp"><input type="hidden" name="ticket" value="{esc(ticket)}">
<button type="submit">패스키로 계속</button></form>
<p id="passkey-status" role="status"></p>
<p class="hint">기기, 휴대폰 또는 보안 키로 인증하세요. 패스키를 사용할 수 없는 브라우저라면 시스템 브라우저에서 다시 연결하세요.</p>
<script src="/assets/passkey.js" defer></script><script src="/assets/passkey-login.js" defer></script>''',
                ),
                cookie,
                redirect_origin(query["redirect_uri"]),
            )
        page = render_page(
            "연결 승인",
            f'''<h1>연결 승인</h1>
<p><strong>{esc(client["client_name"])}</strong>에 다음 권한을 허용합니다:</p>
{self.permissions(scope)}
<form method="post" action="/authorize">
<input type="hidden" name="ticket" value="{esc(ticket)}">
<label for="link-key">서버 연결 키</label>
<input id="link-key" type="password" name="link_key" autocomplete="off" required aria-describedby="key-help">
<p id="key-help" class="hint"><code>secrets/mcp_link_key</code>에 저장된 키를 입력하세요. 카카오 비밀번호를 입력하는 곳이 아닙니다.</p>
<button type="submit">연결 허용</button>
</form>
<p class="hint">연결만으로 이벤트 구독이나 자동 작업이 생성되지는 않습니다.</p>''',
        )
        if self.config.approval_mode == "admin":
            record = self.state.get("approval", digest(ticket))
            page = render_page(
                "ChatGPT 연결",
                f'''<h1>관리 화면에서 확인</h1>
<p>비공개 관리 화면을 열고 <strong>AI 연결</strong>을 선택하세요.</p>
<p>승인 전에 아래 코드와 클라이언트가 일치하는지 확인하세요:</p>
<code class="endpoint">{record["display_code"]}</code>
<p><strong>{esc(client["client_name"])}</strong> · {esc(query["client_id"])}</p>
<p>돌아갈 주소: {esc(redirect_origin(query["redirect_uri"]))}</p>
{self.permissions(scope)}
<form id="approval" method="post" action="/authorize">
<input type="hidden" name="ticket" value="{esc(ticket)}">
<button type="submit">승인 후 계속</button>
</form><p id="status" role="status">승인 대기 중입니다. 10분 후 만료됩니다.</p>
<p class="hint">연결만으로 이벤트 구독이나 자동 작업이 생성되지는 않습니다.</p>
<script src="/assets/approval.js" defer></script>''',
            )
        return page, cookie, redirect_origin(query["redirect_uri"])

    def approve(self, form, cookie, origin):
        self.rate("authorize_post", 10)
        if origin != self.config.public_url:
            raise AuthError("invalid_origin", 403)
        ticket = form.get("ticket", "")
        self.approval(ticket, cookie)
        if self.config.approval_mode == "key" and not hmac.compare_digest(
            form.get("link_key", "").encode(), self.config.link_key.encode()
        ):
            raise AuthError("invalid_link_key", 401)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.approval(ticket, cookie, db=db)
            if self.config.approval_mode == "admin" and (
                record.get("status") != "approved" or record.get("policy") != self.policy()
            ):
                raise AuthError("approval_required", 403)
            if self.config.approval_mode == "passkey":
                if record.get("status") != "authenticated" or record.get("policy") != self.policy():
                    raise AuthError("passkey_login_required", 403)
                if form.get("decision") not in {"allow", "deny"}:
                    raise AuthError("consent_required", 403)
            self.state.delete("approval", digest(ticket), db=db)
            self.state.delete("consent", digest(cookie or ""), db=db)
            grant = {
                **record["query"],
                "scope": record["scope"],
                "expires": time.time() + 120,
                "policy": record.get("policy"),
            }
            if self.config.approval_mode == "passkey" and form.get("decision") == "deny":
                result = {"error": "access_denied"}
            else:
                client_id = grant["client_id"]
                if client_id.startswith("reg_") and not self.state.get("client", client_id, db=db):
                    client = self.registration(client_id)
                    if len(self.state.all("client", db=db)) >= 100:
                        raise AuthError("registration_limit", 429)
                    self.state.put("client", client_id, client, db=db)
                code = secrets.token_urlsafe(32)
                self.state.put("code", digest(code), grant, db=db)
                result = {"code": code}
        query = urlencode({**result, "state": grant["state"], "iss": self.config.public_url})
        return grant["redirect_uri"] + ("&" if "?" in grant["redirect_uri"] else "?") + query

    def approval_status(self, form, cookie, origin):
        self.rate("approval_status", 180)
        if origin != self.config.public_url:
            raise AuthError("invalid_origin", 403)
        record = self.state.get("approval", digest(form.get("ticket", "")))
        if (
            not record
            or record["expires"] <= time.time()
            or not hmac.compare_digest(record["cookie"], digest(cookie or ""))
        ):
            raise AuthError("invalid_approval", 403)
        return {"status": record.get("status", "pending")}

    def authenticate_client(self, form, authorization):
        client_id, secret, method = form.get("client_id"), form.get("client_secret"), "none"
        if secret is not None:
            method = "client_secret_post"
        if authorization:
            try:
                if not authorization.startswith("Basic "):
                    raise ValueError
                raw = base64.b64decode(authorization[6:], validate=True).decode()
                from urllib.parse import unquote_plus

                encoded_id, encoded_secret = raw.split(":", 1)
                basic_id, basic_secret = unquote_plus(encoded_id), unquote_plus(encoded_secret)
                if client_id and client_id != basic_id:
                    raise ValueError
                if secret is not None:
                    raise ValueError
                client_id, secret, method = basic_id, basic_secret, "client_secret_basic"
            except (ValueError, UnicodeError):
                raise AuthError("invalid_client", 401) from None
        if form.get("client_assertion"):
            raise AuthError("unsupported_client_authentication", 401)
        client = self.client(client_id)
        if method != client["token_endpoint_auth_method"]:
            raise AuthError("invalid_client", 401)
        if method != "none" and not hmac.compare_digest(
            digest(secret or ""), client.get("secret_hash", "")
        ):
            raise AuthError("invalid_client", 401)
        return client

    def issue(self, grant_id, grant):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.state.transaction() as db:
            self.state.put(
                "access",
                digest(access),
                {"grant_id": grant_id, "expires": time.time() + 1800},
                db=db,
            )
            self.state.put(
                "refresh",
                digest(refresh),
                {"grant_id": grant_id, "expires": grant["expires"], "used": False},
                db=db,
            )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": grant["scope"],
        }

    def token(self, form, header):
        self.rate("token", 120)
        client = self.authenticate_client(form, header)
        if form.get("resource") != self.config.resource:
            raise AuthError("invalid_target")
        if form.get("grant_type") == "authorization_code":
            record = self.state.take("code", digest(form.get("code", "")))
            verifier = form.get("code_verifier", "")
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            if (
                not record
                or record["expires"] <= time.time()
                or record["client_id"] != client["client_id"]
                or form.get("redirect_uri") != record["redirect_uri"]
                or record["resource"] != form["resource"]
                or (record.get("policy") and record["policy"] != self.policy())
            ):
                raise AuthError("invalid_grant")
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) or not hmac.compare_digest(
                challenge, record["code_challenge"]
            ):
                raise AuthError("invalid_grant")
            grant_id = secrets.token_hex(24)
            grant = {
                "client_id": client["client_id"],
                "resource": record["resource"],
                "scope": record["scope"],
                "owner": digest(self.profile + ":" + client["client_id"]),
                "policy": record.get("policy"),
                "revoked": False,
                "expires": time.time() + 30 * 86400,
            }
            self.state.put("grant", grant_id, grant)
        elif form.get("grant_type") == "refresh_token":
            key = digest(form.get("refresh_token", ""))
            with self.state.transaction() as db:
                db.execute("BEGIN IMMEDIATE")
                record = self.state.get("refresh", key, db=db)
                grant = self.state.get("grant", record["grant_id"], db=db) if record else None
                if (
                    not record
                    or not grant
                    or grant.get("transport", "oauth") != "oauth"
                    or grant["client_id"] != client["client_id"]
                    or record["expires"] <= time.time()
                    or grant["revoked"]
                    or not grant_unexpired(grant)
                    or grant["resource"] != form["resource"]
                    or (grant.get("policy") and grant["policy"] != self.policy())
                ):
                    raise AuthError("invalid_grant")
                grant_id = record["grant_id"]
                if record["used"]:
                    grant["revoked"] = True
                    self.state.put("grant", grant_id, grant, db=db)
                else:
                    record["used"] = True
                    self.state.put("refresh", key, record, db=db)
            if grant["revoked"]:
                raise AuthError("invalid_grant")
            if form.get("scope") and form["scope"] != grant["scope"]:
                raise AuthError("invalid_scope")
        else:
            raise AuthError("unsupported_grant_type")
        return self.issue(grant_id, grant)

    def principal(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("invalid_token", 401)
        record = self.state.get("access", digest(authorization[7:]))
        grant = self.active_grant(record["grant_id"]) if record else None
        if (
            not record
            or record["expires"] <= time.time()
            or not grant
            or grant.get("transport", "oauth") != "oauth"
        ):
            raise AuthError("invalid_token", 401)
        return {**grant, "grant_id": record["grant_id"]}

    def active_grant(self, grant_id):
        grant = self.state.get("grant", grant_id)
        return (
            grant
            if grant
            and not grant["revoked"]
            and grant_unexpired(grant)
            and (
                grant.get("transport", "oauth") == "oauth"
                and grant["resource"] == self.config.resource
                or grant.get("transport") == "tunnel"
                and bool(self.config.tunnel_id)
                and grant["resource"] == self.config.tunnel_resource
            )
            and (
                not grant.get("policy")
                or grant["policy"]
                == (
                    self.passkey_call("info")["policy"]
                    if grant.get("transport") == "tunnel"
                    else self.policy()
                )
            )
            else None
        )

    def revoke(self, form, header):
        self.rate("revoke", 30)
        client = self.authenticate_client(form, header)
        key = digest(form.get("token", ""))
        record = self.state.get("refresh", key) or self.state.get("access", key)
        if record:
            grant = self.state.get("grant", record["grant_id"])
            if grant and grant["client_id"] == client["client_id"]:
                grant["revoked"] = True
                self.state.put("grant", record["grant_id"], grant)

    def cleanup(self):
        now = time.time()
        with self.state.transaction() as db:
            for kind in ("approval", "code", "access", "refresh", "grant"):
                for key, record in self.state.all(kind, db=db):
                    expired = (
                        not grant_unexpired(record, now=now)
                        if kind == "grant"
                        else record.get("expires", now + 1) < now
                    )
                    if expired:
                        self.state.delete(kind, key, db=db)
            active_clients = {g["client_id"] for _, g in self.state.all("grant", db=db)}
            for key, client in self.state.all("client", db=db):
                if (
                    key not in active_clients
                    and client.get("client_id_issued_at", now) < now - 3600
                ):
                    self.state.delete("client", key, db=db)


def parse_form(raw):
    try:
        data = parse_qs(raw.decode(), keep_blank_values=True, max_num_fields=24)
        if any(len(v) != 1 for v in data.values()):
            raise ValueError
        return {k: v[0] for k, v in data.items()}
    except (UnicodeError, ValueError):
        raise AuthError() from None
