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


class OAuth:
    def __init__(self, config, state):
        self.config, self.state = config, state
        self.rate_lock = threading.Lock()
        self.rates = defaultdict(deque)
        with state.transaction() as db:
            self.profile = state.get("settings", "profile", db=db)
            if not self.profile:
                self.profile = "prf_" + secrets.token_hex(16)
                state.put("settings", "profile", self.profile, db=db)

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
        self.rate("register", 20)
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
        if len(self.state.all("client")) >= 100:
            raise AuthError("registration_limit", 429)
        client = {
            "client_id": "client_" + secrets.token_urlsafe(24),
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
        self.state.put("client", client["client_id"], client)
        return public

    def client(self, client_id):
        if not isinstance(client_id, str):
            raise AuthError("invalid_client", 401)
        client = self.state.get("client", client_id)
        if client and client.get("metadata_expires", time.time() + 1) > time.time():
            return client
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

    def authorize(self, query):
        self.rate("authorize_get", 30)
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
        self.state.put(
            "approval",
            digest(ticket),
            {
                "query": {
                    k: query.get(k, "")
                    for k in ("client_id", "redirect_uri", "code_challenge", "state", "resource")
                },
                "scope": scope,
                "cookie": digest(cookie),
                "expires": time.time() + 600,
            },
        )
        esc = html.escape
        permissions = []
        if "kakao.read" in scope.split():
            permissions.append("<li>Read and search stored messages and check collection status</li>")
        if "kakao.events" in scope.split():
            permissions.append("<li>Subscribe to requested new-message events and record processing progress</li>")
        page = render_page(
            "Approve connection",
            f'''<h1>Approve connection</h1>
<p>Allow <strong>{esc(client["client_name"])}</strong> the following permissions:</p>
<ul>{"".join(permissions)}</ul>
<p>Retrieved messages are shared with the connected client. These permissions do not allow sending KakaoTalk messages or controlling the device.</p>
<form method="post" action="/authorize">
<input type="hidden" name="ticket" value="{esc(ticket)}">
<label for="link-key">Server connection key</label>
<input id="link-key" type="password" name="link_key" autocomplete="off" required aria-describedby="key-help">
<p id="key-help" class="hint">Use the key stored in <code>secrets/mcp_link_key</code>, not your Kakao password.</p>
<button type="submit">Allow connection</button>
</form>
<p class="hint">Connecting does not create event subscriptions or automated tasks.</p>''',
        )
        return page, cookie, redirect_origin(query["redirect_uri"])

    def approve(self, form, cookie, origin):
        self.rate("authorize_post", 10)
        if origin != self.config.public_url:
            raise AuthError("invalid_origin", 403)
        ticket = form.get("ticket", "")
        record = self.state.get("approval", digest(ticket))
        if (
            not record
            or record["expires"] <= time.time()
            or not hmac.compare_digest(record["cookie"], digest(cookie or ""))
        ):
            raise AuthError("invalid_approval", 403)
        if not hmac.compare_digest(
            form.get("link_key", "").encode(), self.config.link_key.encode()
        ):
            raise AuthError("invalid_link_key", 401)
        record = self.state.take("approval", digest(ticket))
        if not record:
            raise AuthError("invalid_approval", 403)
        code = secrets.token_urlsafe(32)
        grant = {**record["query"], "scope": record["scope"], "expires": time.time() + 120}
        self.state.put("code", digest(code), grant)
        query = urlencode({"code": code, "state": grant["state"], "iss": self.config.public_url})
        return grant["redirect_uri"] + ("&" if "?" in grant["redirect_uri"] else "?") + query

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
                    or grant["client_id"] != client["client_id"]
                    or record["expires"] <= time.time()
                    or grant["revoked"]
                    or grant["expires"] <= time.time()
                    or grant["resource"] != form["resource"]
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
        if not record or record["expires"] <= time.time() or not grant:
            raise AuthError("invalid_token", 401)
        return {**grant, "grant_id": record["grant_id"]}

    def active_grant(self, grant_id):
        grant = self.state.get("grant", grant_id)
        return (
            grant
            if grant
            and not grant["revoked"]
            and grant["expires"] > time.time()
            and grant["resource"] == self.config.resource
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
                    if record.get("expires", now + 1) < now:
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
