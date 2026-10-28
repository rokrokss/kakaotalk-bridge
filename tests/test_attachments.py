import io
import json
import socket
from io import BytesIO
from urllib.error import HTTPError

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from device import iris
from dot_plugin.app import create_app as mcp_app
from dot_plugin.app import tool_definitions
from dot_plugin.collector import QueryError
from dot_plugin.config import Config
from server.app import create_app
from server.attachments import describe, hint, image_target
from server.config import Settings
from server.iris_client import IrisError
from server.mcp_adapter import _call_result
from server.mcp_content import file_result, image_result
from server.media import FILE_MAX, IMAGE_OUTPUT_MAX, MediaError, fetch, validate_url
from tests.test_api import DATABASE, DEVICE, INGEST, READ, approve_fixture, auth, event, post
from tests.test_dot_plugin import BASE, call, link

CDN = "https://dn.talk.kakao.com/path/photo.jpg"
THUMB = "https://dn.talk.kakao.com/path/thumb.jpg"


def jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (8, 6), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


class FakeIris:
    def __init__(self, attachment, media=None, error=None, media_error=None):
        self.attachment_value = attachment
        self.media_value = media if media is not None else (jpeg_bytes(), "image/jpeg", 8, 6)
        self.error = error
        self.media_error = media_error
        self.calls = []

    def attachment(self, **kwargs):
        self.calls.append(("attachment", kwargs))
        if self.error:
            raise IrisError(self.error)
        return self.attachment_value(kwargs) if callable(self.attachment_value) else self.attachment_value

    def media(self, url, kind):
        self.calls.append(("media", url, kind))
        if self.media_error:
            raise IrisError(self.media_error)
        if kind == "file":
            return b"%PDF", "application/pdf", None, None
        return self.media_value


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(str(tmp_path / "attach.db"), INGEST, READ, DEVICE))
    with TestClient(app) as client:
        approve_fixture(client)
        yield client


def typed(seq, message_type, body="사진"):
    record = event(seq, body)
    record["database_ref"]["message_type"] = str(message_type)
    return record


def photo_attachment(**extra):
    return json.dumps(
        {
            "url": CDN,
            "thumbnailUrl": THUMB,
            "w": 640,
            "h": 480,
            "mt": "image/jpeg",
            "k": "media-key",
            "cs": "CHECKSUM",
            **extra,
        }
    )


def install(api, fake):
    api.app.state.attachments.iris = fake


def test_listing_hint_has_no_url_and_photo_is_marked(api):
    post(api, typed(1, 2), typed(2, 1, "hello"))
    rows = {item["message_id"]: item for item in api.get("/v2/messages", headers=auth()).json()["items"]}
    assert rows[1]["attachment_type"] == "photo" and rows[1]["has_attachment"] is True
    assert rows[2]["attachment_type"] == "text" and rows[2]["has_attachment"] is False
    assert "http" not in json.dumps(rows)
    assert hint("16386") == {"attachment_type": "photo", "has_attachment": True}
    with api.app.state.store.connect() as db:
        stored = " ".join(row[0] for row in db.execute("SELECT body FROM observations"))
    assert "thumbnailUrl" not in stored and CDN not in stored


def test_attachment_strips_keys_and_image_download_uses_allowlist(api, capsys):
    post(api, typed(1, 2))
    fake = FakeIris(
        {
            "log_id": "1",
            "database_id": DATABASE,
            "message_type": "2",
            "attachment": photo_attachment(),
        }
    )
    install(api, fake)
    view = api.get("/v2/attachments", params={"message_id": 1}, headers=auth())
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["photos"][0]["url"] == CDN
    assert "media-key" not in view.text and "CHECKSUM" not in view.text
    image = api.get(
        "/v2/attachments/image",
        params={"message_id": 1, "variant": "thumbnail"},
        headers=auth(),
    )
    assert image.status_code == 200, image.text
    assert image.content == jpeg_bytes()
    assert image.headers["x-bridge-mime"] == "image/jpeg"
    assert image.headers["x-bridge-variant"] == "thumbnail"
    assert ("media", THUMB, "image") in fake.calls
    captured = capsys.readouterr()
    assert "dn.talk.kakao.com" not in captured.out and "dn.talk.kakao.com" not in captured.err
    original = api.get(
        "/v2/attachments/image", params={"message_id": 1, "variant": "original"}, headers=auth()
    )
    assert original.status_code == 200
    assert ("media", CDN, "image") in fake.calls


def test_image_errors_are_codes_without_urls(api):
    post(api, typed(1, 2), typed(2, 9, "link"))
    missing = api.get("/v2/attachments", params={"message_id": 99}, headers=auth())
    assert missing.status_code == 404 and missing.json() == {"error": "message_not_found_or_expired"}
    install(api, FakeIris(None, error="not_found"))
    gone = api.get("/v2/attachments", params={"message_id": 1}, headers=auth())
    assert gone.status_code == 409 and gone.json()["error"] == "attachment_not_in_device_database"
    install(api, FakeIris(None, error="decrypt_failed"))
    failed = api.get("/v2/attachments", params={"message_id": 1}, headers=auth())
    assert failed.json() == {"error": "attachment_decrypt_failed"}
    install(
        api,
        FakeIris(
            {
                "log_id": "1",
                "database_id": DATABASE,
                "message_type": "2",
                "attachment": photo_attachment(url="https://evil.example/a.jpg", thumbnailUrl=THUMB),
            }
        ),
    )
    blocked = api.get(
        "/v2/attachments/image",
        params={"message_id": 1, "variant": "original"},
        headers=auth(),
    )
    assert blocked.status_code == 400 and blocked.json() == {"error": "host_not_allowed"}
    assert "evil.example" not in blocked.text
    install(
        api,
        FakeIris(
            {
                "log_id": "1",
                "database_id": DATABASE,
                "message_type": "2",
                "attachment": photo_attachment(),
            },
            media_error="image_expired",
        ),
    )
    expired = api.get("/v2/attachments/image", params={"message_id": 1}, headers=auth())
    assert expired.status_code == 410 and expired.json() == {"error": "image_expired"}
    assert "http" not in expired.text


def test_video_original_is_refused_and_file_download_is_explicit(api):
    post(api, typed(1, 3, "동영상"), typed(2, 18, "파일"))
    install(
        api,
        FakeIris(
            lambda kwargs: {
                "log_id": str(kwargs["log_id"]),
                "database_id": DATABASE,
                "message_type": "3" if str(kwargs["log_id"]) == "1" else "18",
                "attachment": json.dumps(
                    {"thumbnailUrl": THUMB, "d": 1500, "w": 320, "h": 240, "tk": "thumb-key"}
                    if str(kwargs["log_id"]) == "1"
                    else {
                        "name": "보고서.pdf",
                        "size": 3,
                        "mt": "application/pdf",
                        "url": CDN,
                        "cs": "SECRET",
                    }
                ),
            },
        ),
    )
    refused = api.get(
        "/v2/attachments/image",
        params={"message_id": 1, "variant": "original"},
        headers=auth(),
    )
    assert refused.json() == {"error": "video_not_downloaded"}
    thumb = api.get(
        "/v2/attachments/image", params={"message_id": 1, "variant": "thumbnail"}, headers=auth()
    )
    assert thumb.status_code == 200
    view = api.get("/v2/attachments", params={"message_id": 1}, headers=auth()).json()
    assert view["video"]["duration_ms"] == 1500 and "thumb-key" not in json.dumps(view)
    downloaded = api.get("/v2/attachments/file", params={"message_id": 2}, headers=auth())
    assert downloaded.status_code == 200 and downloaded.content == b"%PDF"
    assert "SECRET" not in downloaded.headers.get("content-disposition", "")
    assert downloaded.headers["x-bridge-mime"] == "application/pdf"
    assert "http" not in downloaded.headers["x-bridge-file-name"]


def test_feed_uses_stored_body_when_collector_is_down(api):
    body = json.dumps(
        {"feedType": 4, "members": [{"userId": 9, "nickName": "Ada"}], "secret": "nope"}
    )
    post(api, typed(3, 0, body))
    install(api, FakeIris(None, error="attachment_unavailable"))
    view = api.get("/v2/attachments", params={"message_id": 1}, headers=auth())
    assert view.status_code == 200, view.text
    assert view.json()["feed"]["label"] == "join"
    assert view.json()["feed"]["members"] == [{"user_id": "9", "nickname": "Ada"}]
    assert "nope" not in view.text


def test_reply_resolves_retained_source_message(api):
    post(api, typed(10, 1, "원문"), typed(11, 26, "답장"))
    install(
        api,
        FakeIris(
            {
                "log_id": "11",
                "database_id": DATABASE,
                "message_type": "26",
                "attachment": json.dumps(
                    {"src_logId": 10, "src_userId": 7, "src_message": "원문", "src_type": 1}
                ),
            }
        ),
    )
    view = api.get("/v2/attachments", params={"message_id": 2}, headers=auth()).json()
    assert view["reply"]["source_log_id"] == "10"
    assert view["reply"]["source_message_id"] == 1
    assert view["reply"]["preview"] == "원문"


def test_describe_shapes_for_rich_types():
    photo = describe("2", photo_attachment())
    assert photo["photos"][0]["width"] == 640
    assert "k" not in photo["photos"][0]
    multi = describe(
        "27",
        json.dumps(
            {
                "imageUrls": [CDN, CDN + "2"],
                "thumbnailUrls": [THUMB],
                "wl": [10, 11],
                "hl": [12, 13],
                "sl": 4,
                "kl": ["secret"],
                "csl": ["abc"],
            }
        ),
    )
    assert len(multi["photos"]) == 2 and "secret" not in json.dumps(multi)
    link = describe(
        "9",
        json.dumps(
            {
                "scrapData": {
                    "url": "https://example.com/a",
                    "title": "Title",
                    "description": "Body",
                    "mainImageUrl": "https://example.com/i.jpg",
                }
            }
        ),
    )
    assert link["link"]["title"] == "Title" and link["images"][0]["role"] == "link"
    emoticon = describe("12", json.dumps({"path": "item/1", "name": "heart", "alt": "하트"}))
    assert emoticon["emoticon"]["path"] == "item/1" and emoticon["emoticon"]["image_url"] is None
    assert emoticon["images"] == []
    https_emoticon = describe("6", json.dumps({"path": "https://item.kakaocdn.net/dw/x.png"}))
    assert https_emoticon["emoticon"]["image_url"].startswith("https://item.kakaocdn.net/")
    place = describe("16", json.dumps({"lat": 375000000000, "lng": 1270000000000, "a": "서울", "t": "카페"}))
    assert place["location"]["latitude"] == 37.5 and place["location"]["longitude"] == 127.0
    contact = describe("4", json.dumps({"name": "Kim", "url": "https://dn.talk.kakao.com/secret.vcf"}))
    assert contact["contact"] == {"name": "Kim", "has_card": True}
    assert "secret.vcf" not in json.dumps(contact)
    audio = describe("5", json.dumps({"d": 3200, "url": CDN, "s": 10}))
    assert audio["audio"]["duration_ms"] == 3200 and CDN not in json.dumps(audio)
    reply = describe(
        "26",
        json.dumps({"src_logId": 10, "src_userId": 7, "src_message": "hi", "src_type": 1}),
        names={"7": "Ada"},
        message_ids={"10": 3},
    )
    assert reply["reply"]["source_message_id"] == 3 and reply["reply"]["source_user_name"] == "Ada"
    mention = describe("1", json.dumps({"mentions": [{"user_id": 7, "at": [0], "len": 3}]}), names={"7": "Ada"})
    assert mention["mentions"][0]["name"] == "Ada" and mention["has_attachment"] is True
    unknown = describe("999", json.dumps({"foo": "bar", "k": "secret"}))
    assert unknown["attachment_type"] == "unknown" and unknown["unknown_fields"]["foo"] == "bar"
    assert "secret" not in json.dumps(unknown)
    reaction = describe("1", json.dumps({"reaction": {"type": "heart"}}))
    assert reaction["reactions"]["type"] == "heart"
    with pytest.raises(ValueError, match="^not_an_image$"):
        image_target(describe("1", None), "original", 0)
    with pytest.raises(ValueError, match="^video_not_downloaded$"):
        image_target(describe("3", json.dumps({"thumbnailUrl": THUMB})), "original", 0)


def test_media_allowlist_redirect_private_ip_and_downscale(monkeypatch):
    with pytest.raises(MediaError, match="^host_not_allowed$"):
        validate_url("https://evil.example/a.jpg")
    with pytest.raises(MediaError, match="^host_not_allowed$"):
        validate_url("http://dn.talk.kakao.com/a.jpg")
    with pytest.raises(MediaError, match="^host_not_allowed$"):
        validate_url("https://user:pw@dn.talk.kakao.com/a.jpg")

    def redirect(url, limit):
        assert limit >= len(b"ok")
        if url.endswith("/start"):
            return 302, {"location": "https://127.0.0.1/secret"}, b""
        raise AssertionError(url)

    with pytest.raises(MediaError, match="^host_not_allowed$"):
        fetch(CDN.replace("path/photo.jpg", "start"), "image", transport=redirect)

    def expired(url, limit):
        return 410, {}, b"gone"

    with pytest.raises(MediaError, match="^image_expired$"):
        fetch(CDN, "image", transport=expired)
    with pytest.raises(MediaError, match="^file_unavailable$"):
        fetch(CDN, "file", transport=expired)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(MediaError, match="^image_unavailable$"):
        fetch(CDN, "image")

    buffer = BytesIO()
    Image.new("RGB", (1800, 1200), "red").save(buffer, format="PNG")
    blob = buffer.getvalue()

    def png(url, limit):
        return 200, {"content-type": "image/png"}, blob

    data, mime, width, height = fetch(CDN, "image", transport=png)
    assert mime == "image/jpeg" and max(width, height) <= 1600 and len(data) <= IMAGE_OUTPUT_MAX

    def huge(url, limit):
        return 200, {"content-type": "application/pdf"}, b"x" * (FILE_MAX + 1)

    with pytest.raises(MediaError, match="^file_too_large$"):
        fetch(CDN, "file", transport=huge)

    def html(url, limit):
        return 200, {"content-type": "text/html"}, b"<html></html>"

    _data, file_mime, _w, _h = fetch(CDN, "file", transport=html)
    assert file_mime == "application/octet-stream"


def test_attachment_request_reports_code_only(monkeypatch):
    def boom(req, timeout=0):
        raise HTTPError(req.full_url, 409, "no", {}, io.BytesIO(b'{"error":"decrypt_failed"}'))

    monkeypatch.setattr(iris, "urlopen", boom)
    with pytest.raises(RuntimeError, match="^decrypt_failed$") as caught:
        iris.attachment_request(10, "token")
    assert "http" not in str(caught.value)


def test_send_tools_do_not_grow_quote_or_media_parameters():
    names = {tool["name"] for tool in tool_definitions()}
    assert "send_image" not in names and "send_media" not in names
    send = next(tool for tool in tool_definitions() if tool["name"] == "send_message")
    assert set(send["inputSchema"]["properties"]) == {"conversation_ref", "text", "request_id"}
    image = next(tool for tool in tool_definitions() if tool["name"] == "get_message_image")
    assert image["annotations"]["openWorldHint"] is True
    assert image["annotations"]["readOnlyHint"] is True
    assert "kakao.read" in image["securitySchemes"][0]["scopes"]
    attachment = next(tool for tool in tool_definitions() if tool["name"] == "get_message_attachment")
    assert attachment["annotations"]["openWorldHint"] is False


def test_mcp_image_and_file_blocks_omit_urls(tmp_path):
    blob = jpeg_bytes()

    class Stub:
        def __init__(self, error=None):
            self.error = error

        def attachment(self, message_id):
            return {
                "message_id": message_id,
                "attachment_type": "photo",
                "has_attachment": True,
                "message_type": "2",
            }

        def image(self, message_id, variant, index):
            if self.error:
                raise QueryError(self.error)
            return blob, {
                "x-bridge-mime": "image/jpeg",
                "x-bridge-width": "8",
                "x-bridge-height": "6",
                "x-bridge-count": "1",
                "x-bridge-role": "photo",
                "x-bridge-attachment-type": "photo",
            }

        def file(self, message_id):
            return b"%PDF", {"x-bridge-mime": "application/pdf", "x-bridge-file-name": "a.pdf"}

    rendered = image_result({"message_id": 1, "variant": "thumbnail"}, blob, "image/jpeg")
    called = _call_result(rendered)
    assert called.content[1].type == "image" and called.content[1].mimeType == "image/jpeg"
    assert called.structuredContent is None
    assert "http" not in called.content[0].text
    filed = _call_result(file_result({"name": "a.pdf", "size": 4}, b"%PDF", "application/pdf", 4))
    assert str(filed.content[1].resource.uri) == "https://kakaotalk-bridge.invalid/messages/4/file"
    assert filed.content[1].resource.blob

    config = Config(BASE, str(tmp_path / "dot.db"), "L" * 43, Fernet.generate_key(), approval_mode="key")
    with TestClient(mcp_app(config, Stub(), worker=False), base_url=BASE) as client:
        _, form = link(client)
        client.headers["Authorization"] = "Bearer " + client.post("/token", data=form).json()["access_token"]
        result = call(client, "get_message_image", message_id=1)["result"]
        assert result["content"][1]["type"] == "image"
        assert "structuredContent" not in result
        assert "http" not in result["content"][0]["text"]
        meta = call(client, "get_message_attachment", message_id=1)["result"]
        assert meta["structuredContent"]["attachment_type"] == "photo"
        downloaded = call(client, "get_message_file", message_id=1)["result"]
        assert downloaded["content"][1]["type"] == "resource"
    with TestClient(mcp_app(config, Stub("image_expired"), worker=False), base_url=BASE) as client:
        _, form = link(client)
        client.headers["Authorization"] = "Bearer " + client.post("/token", data=form).json()["access_token"]
        error = call(client, "get_message_image", message_id=1)["error"]
        assert error["message"] == "image_expired"
