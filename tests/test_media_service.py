import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from device.media_service import Handler, ThreadingHTTPServer


def _server(attachment, fetch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.token = "t" * 32
    httpd.attachment = attachment
    httpd.fetch = fetch
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def _request(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(), headers=headers
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.read(), dict(response.headers)
    except HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_media_service_rejects_missing_token_and_does_not_log_urls(capsys):
    seen = {}

    def attachment(payload):
        seen["log"] = payload["log_id"]
        return {"log_id": payload["log_id"], "message_type": "1", "attachment": None, "database_id": "1:1"}

    def fetch(payload):
        seen["url"] = payload["url"]
        return b"\xff\xd8\xff", "image/jpeg", 2, 3

    httpd, _thread = _server(attachment, fetch)
    port = httpd.server_address[1]
    secret = "https://dn.talk.kakao.com/private/photo.jpg"
    try:
        status, body, _headers = _request(port, "/internal/attachment", {"log_id": "1"})
        assert status == 401 and json.loads(body) == {"error": "unauthorized"}
        status, body, _headers = _request(
            port, "/internal/attachment", {"log_id": "9"}, token="u" * 32
        )
        assert status == 401
        status, body, _headers = _request(
            port, "/internal/attachment", {"log_id": "9"}, token="t" * 32
        )
        assert status == 200 and seen["log"] == "9"
        status, body, headers = _request(
            port, "/internal/media", {"url": secret, "kind": "image"}, token="t" * 32
        )
        assert status == 200 and body == b"\xff\xd8\xff"
        assert headers["X-Bridge-Mime"] == "image/jpeg"
        assert secret not in json.dumps(headers)
    finally:
        httpd.shutdown()
    Handler.log_message(object(), "fetched %s", secret)
    captured = capsys.readouterr()
    assert secret not in captured.out and secret not in captured.err and "dn.talk" not in captured.err
