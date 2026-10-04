#!/usr/bin/env python3
"""Exercise the deployed OAuth/MCP endpoint without printing keys or message text.

Creates a temporary OAuth grant and revokes it before exiting. Does not subscribe,
acknowledge messages, or send KakaoTalk messages. Requires the project's httpx.
"""

import argparse
import base64
import hashlib
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


def smoke(base, key_path):
    if urlsplit(base).scheme != "https" or urlsplit(base).path:
        raise ValueError("Expected an HTTPS origin without a trailing slash")
    redirect = "https://chatgpt.com/connector_platform_oauth_redirect"
    verifier, oauth_state = secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    token = registration = None
    with httpx.Client(base_url=base, timeout=20, follow_redirects=False, trust_env=False) as client:
        response = client.get("/mcp")
        assert response.status_code == 401
        assert base + "/.well-known/oauth-protected-resource" in response.headers[
            "www-authenticate"
        ]
        assert client.get("/.well-known/openid-configuration").status_code == 404
        metadata = client.get("/.well-known/oauth-authorization-server")
        assert metadata.status_code == 200 and metadata.json()["issuer"] == base
        print("PASS public TLS, unauthenticated MCP 401, OAuth discovery, OIDC 404")
        response = client.post(
            "/register",
            json={
                "redirect_uris": [redirect],
                "client_name": "KakaoTalk deployment smoke test",
                "token_endpoint_auth_method": "none",
            },
        )
        assert response.status_code == 201
        registration = response.json()
        query = {
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": redirect,
            "resource": base + "/mcp",
            "scope": "kakao.read kakao.events",
            "state": oauth_state,
            "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("="),
        }
        page = client.get("/authorize?" + urlencode(query))
        assert page.status_code == 200
        assert page.headers["referrer-policy"] == "same-origin"
        ticket = re.search(r'name="ticket" value="([^"]+)"', page.text)[1]
        approval = client.post(
            "/authorize",
            data={"ticket": ticket, "link_key": Path(key_path).read_text().strip()},
            headers={"Origin": base},
        )
        assert approval.status_code == 303
        assert approval.headers["referrer-policy"] == "no-referrer"
        location = urlsplit(approval.headers["location"])
        assert location.scheme + "://" + location.netloc + location.path == redirect
        callback = parse_qs(location.query)
        assert callback["state"] == [oauth_state] and callback["iss"] == [base]
        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": callback["code"][0],
                "redirect_uri": redirect,
                "client_id": registration["client_id"],
                "resource": base + "/mcp",
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200
        token = response.json()
        print("PASS OAuth owner approval, PKCE S256 and token exchange")
        try:
            client.headers["Authorization"] = "Bearer " + token["access_token"]

            def rpc(method, **params):
                response = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                assert response.status_code == 200
                data = response.json()
                assert "error" not in data
                assert data["result"]["resultType"] == "complete"
                return data["result"]

            discovery = rpc("server/discover")
            assert "2026-07-28" in discovery["supportedVersions"]
            assert "events" in discovery["capabilities"]
            tools = rpc("tools/list")["tools"]
            assert len(tools) == 8
            events = rpc("events/list")["events"]
            assert [e["name"] for e in events] == ["message.created"]
            profile = rpc("tools/call", name="get_profile", arguments={})
            assert profile["structuredContent"]["id"]
            status = rpc("tools/call", name="get_collector_status", arguments={})
            assert not status["isError"]
            print("PASS MCP 2.0 discovery, 8 tools, message.created event, profile and status")
            recent = rpc("tools/call", name="get_recent_messages", arguments={"limit": 1})[
                "structuredContent"
            ]
            rows = recent["items"]
            assert len(rows) <= 1
            source = rows[0].get("source") if rows else "empty"
            print(
                f"PASS real collector read: rows={len(rows)}, "
                f"has_more={recent['has_more']}, source={source}; text not printed"
            )
        finally:
            client.headers.pop("Authorization", None)
            revoked = client.post(
                "/revoke",
                data={"client_id": registration["client_id"], "token": token["refresh_token"]},
            )
            assert revoked.status_code == 200
            denied = client.get("/mcp", headers={"Authorization": "Bearer " + token["access_token"]})
            assert denied.status_code == 401
            print("PASS smoke-test grant revoked; no active subscription created")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", help="Public HTTPS origin, no trailing slash")
    parser.add_argument("--key-file", default="secrets/mcp_link_key")
    options = parser.parse_args()
    smoke(options.origin, options.key_file)
