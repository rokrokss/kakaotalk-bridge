"""Run against an isolated Compose test project. Never posts to KakaoTalk."""

import asyncio
import http.cookiejar
import json
import os
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

base = os.getenv("SMOKE_URL", "https://127.0.0.1:18443")
tls = ssl.create_default_context(cafile="secrets/tls_cert.pem")


def request(path, token=None, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + Path(f"secrets/{token}").read_text().strip()
    req = Request(base + path, json.dumps(data).encode() if data is not None else None, headers)
    with urlopen(req, context=tls, timeout=5) as response:
        return json.load(response)


for attempt in range(30):
    try:
        request("/health/ready")
        break
    except URLError:
        time.sleep(1)
else:
    raise SystemExit("Gateway/API not ready")

event = {
    "event_id": str(uuid4()),
    "enrollment_epoch": str(uuid4()),
    "source_seq": 1,
    "device_id": os.getenv("DEVICE_ID", "personal-tablet"),
    "source": "iris_db",
    "kind": "db_row",
    "package_name": "com.kakao.talk",
    "notification_key": "synthetic-test",
    "observed_at": datetime.now(UTC).isoformat(),
    "payload": {"messages": [{"body": "테스트: no KakaoTalk account involved", "sender": "123"}]},
    "database_ref": {
        "database_id": "synthetic:1",
        "log_id": "1",
        "chat_id": "9007199254740993",
        "sender_id": "123",
        "message_type": "1",
        "origin": "SYNCMSG",
        "is_mine": False,
    },
}
batch = {"schema_version": 1, "events": [event]}
# Synthetic fixture confirmation only; this is not evidence about a real Kakao account.
request(
    "/internal/v1/heartbeat",
    "ingest_token",
    {
        "device_id": event["device_id"],
        "enrollment_epoch": event["enrollment_epoch"],
        "source": "iris_db",
        "database_id": "synthetic:1",
        "listener_connected": True,
        "secondary_login_confirmed": True,
        "last_source_seq": 1,
    },
)
assert (
    request("/internal/v1/observations:batch", "ingest_token", batch)["results"][0]["status"]
    == "committed"
)
assert (
    request("/internal/v1/observations:batch", "ingest_token", batch)["results"][0]["status"]
    == "duplicate"
)
page = request("/v1/messages", "read_token")
assert len(page["items"]) == 1
assert page["items"][0]["body"] == event["payload"]["messages"][0]["body"]
assert page["coverage"]["complete"] is False
progress = request("/internal/v1/iris/cursor?epoch=" + event["enrollment_epoch"], "ingest_token")
assert progress == {"after": 1, "database_id": "synthetic:1"}
assert page["items"][0]["conversation_ref"].endswith(":9007199254740993")
print("PASS: synthetic Iris row, durable cursor and scoped conversation ID")
print(
    "PASS: TLS verification, authenticated ingest, duplicate retry, Korean text, read API, partial coverage"
)


async def mcp_smoke():
    params = StdioServerParameters(
        command="docker",
        args=[
            "compose",
            "-p",
            os.environ["SMOKE_PROJECT"],
            "--profile",
            "mcp",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "mcp",
        ],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        for name, args in [
            ("get_recent_messages", {}),
            ("search_messages", {"q": "테스트"}),
            ("list_conversations", {}),
            ("get_collector_status", {}),
        ]:
            result = await client.call_tool(name, args)
            assert not result.isError, name
            data = result.structuredContent
            if data is None:
                # SDK v1 may encode a generic dict return as JSON TextContent.
                texts = [item.text for item in result.content if item.type == "text"]
                assert len(texts) == 1
                data = json.loads(texts[0])
            if name != "get_collector_status":
                assert len(data["items"]) == 1, name
            else:
                assert data["coverage"]["complete"] is False
    print("PASS: container stdio MCP calls all four read-only tools against the API")


asyncio.run(mcp_smoke())


# Validate the deployed gateway -> admin route without touching ADB or a Kakao account.
cookies = http.cookiejar.CookieJar()
admin = build_opener(HTTPSHandler(context=tls), HTTPCookieProcessor(cookies))


def admin_request(path, data=None, csrf=None):
    headers = {"Origin": base, "Content-Type": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    req = Request(base + path, None if data is None else json.dumps(data).encode(), headers)
    with admin.open(req, timeout=10) as response:
        return response.headers, response.read()


headers, html = admin_request("/admin/")
assert b"device-text" in html and headers["Cache-Control"] == "no-store"
_, body = admin_request(
    "/admin/api/login", {"token": Path("secrets/admin_token").read_text().strip()}
)
csrf = json.loads(body)["csrf"]
assert any(cookie.secure and cookie.has_nonstandard_attr("HttpOnly") for cookie in cookies)
_, body = admin_request("/admin/api/state")
assert json.loads(body)["job"]["state"] == "idle"
try:
    admin_request("/admin/api/key", {"name": "home"})
except URLError as error:
    assert error.code == 403
else:
    raise AssertionError("CSRF protection missing")
admin_request("/admin/api/logout", {}, csrf)
try:
    admin_request("/admin/api/session")
except URLError as error:
    assert error.code == 401
else:
    raise AssertionError("Logout did not revoke session")
print("PASS: HTTPS web console, secure admin session, CSRF rejection and logout (no ADB actions)")
