"""Turn one decrypted KakaoTalk attachment into sanitized metadata.

URLs are returned only from this on-demand view. Listings use `hint`, which
looks at the type code and never reads attachment JSON. Media keys (`k`,
checksums) are dropped. Nothing here is stored.
"""

import json
import math

DELETED_BIT = 0x4000
TEXT_LIMIT = 500
URL_LIMIT = 2048
# Kakao multi-photo messages are small; keep a hard cap so one row cannot expand.
MAX_ITEMS = 30
SENSITIVE = {"k", "tk", "cs", "kl", "csl", "cmtl", "ak"}
# Type codes from storycraft/node-kakao KnownChatType. Deleted rows set bit 14.
KINDS = {
    0: ("feed", True),
    1: ("text", False),
    2: ("photo", True),
    3: ("video", True),
    4: ("contact", True),
    5: ("audio", True),
    6: ("emoticon", True),
    7: ("gift", True),
    8: ("emoticon", True),
    9: ("link", True),
    11: ("avatar", True),
    12: ("sticker", True),
    13: ("schedule", True),
    14: ("vote", True),
    15: ("lottery", True),
    16: ("location", True),
    17: ("profile", True),
    18: ("file", True),
    20: ("sticker", True),
    21: ("nudge", True),
    22: ("emoticon", True),
    23: ("search", True),
    24: ("post", True),
    25: ("sticker", True),
    26: ("reply", True),
    27: ("photos", True),
    51: ("call", True),
    52: ("call", True),
    71: ("link", True),
    72: ("alimtalk", True),
    81: ("plus", True),
    82: ("plus", True),
    83: ("plus", True),
    96: ("schedule", True),
    97: ("vote", True),
    98: ("post", True),
}
# feedType 2 and 4 are the only values this bridge already parses as leave/join.
FEED_LABELS = {2: "leave", 4: "join"}


def classify(message_type):
    if message_type is None or message_type == "":
        return None, False
    try:
        code = int(str(message_type))
    except (TypeError, ValueError):
        return "unknown", True
    if code < 0:
        return "unknown", True
    return KINDS.get(code & ~DELETED_BIT, ("unknown", True))


def hint(message_type):
    """Listing/webhook hint. Text can still carry mentions or a link preview."""
    kind, rich = classify(message_type)
    return {"attachment_type": kind, "has_attachment": rich}


def _text(value, limit=TEXT_LIMIT):
    if not isinstance(value, str):
        return None
    if any(ord(ch) < 32 and ch not in "\n\t" or 0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return None
    cleaned = value.strip()
    return cleaned[:limit] or None


def _url(value):
    text = _text(value, URL_LIMIT)
    if not text or len(text) > URL_LIMIT or not text.startswith("https://") or text.startswith("https://@"):
        return None
    if any(ch in text for ch in " \t\r\n\\") or "@" in text.split("/", 3)[2]:
        return None
    return text


def _int(value, upper=2_147_483_647):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    number = int(value)
    if not 0 <= number <= upper:
        return None
    return number


def _seq(value):
    if isinstance(value, list):
        return value[:MAX_ITEMS]
    if value is None:
        return []
    return [value]


def parse_object(raw):
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw) > 65536:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return {"_unparsed": True}
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"_list": value[:MAX_ITEMS]}
    return {"_unparsed": True}


def reference_ids(raw, body=None):
    users, logs = set(), set()

    def walk(value, depth=0):
        if depth > 6:
            return
        if isinstance(value, list):
            for item in value[:50]:
                walk(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        for key, item in list(value.items())[:80]:
            if key in {"user_id", "userId", "src_userId"} and _int(item, 9223372036854775807):
                users.add(str(int(item)))
            if key == "src_logId" and _int(item, 9223372036854775807):
                logs.add(str(int(item)))
            walk(item, depth + 1)

    for blob in (parse_object(raw), parse_object(body)):
        if blob:
            walk(blob)
    return users, logs


def _photo(obj, index):
    if not isinstance(obj, dict):
        return None
    width = _int(obj.get("w", obj.get("width")))
    height = _int(obj.get("h", obj.get("height")))
    return {
        "index": index,
        "mime": _text(obj.get("mt") or obj.get("mime"), 80),
        "width": width,
        "height": height,
        "size": _int(obj.get("s", obj.get("size"))),
        "caption": _text(obj.get("cmt") or obj.get("caption")),
        "url": _url(obj.get("url")),
        "thumbnail_url": _url(obj.get("thumbnailUrl") or obj.get("thumbnail_url")),
        "thumbnail_width": _int(obj.get("thumbnailWidth")),
        "thumbnail_height": _int(obj.get("thumbnailHeight")),
        "expires_at": _int(obj.get("expire"), 4_102_444_800),
    }


def _photos(obj):
    if not isinstance(obj, dict):
        return []
    urls = _seq(obj.get("imageUrls") or obj.get("urls"))
    thumbs = _seq(obj.get("thumbnailUrls"))
    if not urls and not thumbs and obj.get("url"):
        return [photo for photo in (_photo(obj, 0),) if photo]
    width, height = _seq(obj.get("wl")), _seq(obj.get("hl"))
    sizes, mimes = _seq(obj.get("sl")), _seq(obj.get("mtl"))
    tw, th = _seq(obj.get("thumbnailWidths")), _seq(obj.get("thumbnailHeights"))
    count = min(MAX_ITEMS, max(len(urls), len(thumbs), len(width), len(height), 0))
    photos = []
    for index in range(count):
        photos.append(
            {
                "index": index,
                "mime": _text(mimes[index], 80) if index < len(mimes) else None,
                "width": _int(width[index]) if index < len(width) else None,
                "height": _int(height[index]) if index < len(height) else None,
                "size": _int(sizes[index]) if index < len(sizes) else None,
                "caption": None,
                "url": _url(urls[index]) if index < len(urls) else None,
                "thumbnail_url": _url(thumbs[index]) if index < len(thumbs) else None,
                "thumbnail_width": _int(tw[index]) if index < len(tw) else None,
                "thumbnail_height": _int(th[index]) if index < len(th) else None,
                "expires_at": _int(obj.get("expire"), 4_102_444_800),
            }
        )
    return photos


def _image_entry(role, photo):
    if not photo or (not photo.get("url") and not photo.get("thumbnail_url")):
        return None
    return {
        "role": role,
        "index": photo["index"],
        "mime": photo.get("mime"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "url": photo.get("url"),
        "thumbnail_url": photo.get("thumbnail_url"),
    }


def _mentions(obj, names):
    found = []
    items = obj.get("mentions") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return found, False
    for item in items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        user = _int(item.get("user_id"), 9223372036854775807)
        if not user:
            continue
        at = [_int(n, 100000) for n in _seq(item.get("at"))]
        found.append(
            {
                "user_id": str(user),
                "name": names.get(str(user)),
                "at": [n for n in at if n is not None][:20],
                "len": _int(item.get("len"), 512),
            }
        )
    all_mention = bool(obj.get("all_mention"))
    return found, all_mention


def _coords(lat, lng):
    def scale(value, limit):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if abs(number) <= limit:
            return round(number, 7)
        for divisor in (10_000_000_000, 1_000_000):
            scaled = number / divisor
            if abs(scaled) <= limit:
                return round(scaled, 7)
        return None

    return scale(lat, 90), scale(lng, 180)


def _members(feed):
    raw = []
    if isinstance(feed.get("member"), dict):
        raw.append(feed["member"])
    if isinstance(feed.get("members"), list):
        raw.extend(feed["members"][:MAX_ITEMS])
    if isinstance(feed.get("inviter"), dict):
        raw.append(feed["inviter"])
    people, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        user = _int(item.get("userId"), 9223372036854775807)
        name = _text(item.get("nickName"), 512)
        if not user or not name or user in seen:
            continue
        seen.add(user)
        people.append({"user_id": str(user), "nickname": name})
    return people


def _feed(body):
    feed = parse_object(body)
    if not isinstance(feed, dict) or feed.get("_unparsed"):
        return None
    kind = feed.get("feedType")
    if isinstance(kind, bool) or not isinstance(kind, int):
        return None
    return {
        "feed_type": kind,
        "label": FEED_LABELS.get(kind),
        "members": _members(feed),
    }


def _link(obj):
    scrap = obj.get("scrapData") if isinstance(obj.get("scrapData"), dict) else obj
    if not isinstance(scrap, dict):
        return None
    url = _url(scrap.get("url") or scrap.get("canonicalUrl"))
    title = _text(scrap.get("title"))
    description = _text(scrap.get("description") or scrap.get("content"))
    image = _url(scrap.get("mainImageUrl") or scrap.get("imageUrl"))
    if not image and isinstance(scrap.get("imageUrls"), list) and scrap["imageUrls"]:
        image = _url(scrap["imageUrls"][0])
    if not any((url, title, description, image)):
        return None
    return {"url": url, "title": title, "description": description, "image_url": image}


def _sanitize(value, depth=0):
    if depth > 4:
        return None
    if isinstance(value, str):
        return _url(value) if value.startswith("https://") else _text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or abs(value) > 1e15):
            return None
        return value
    if isinstance(value, list):
        items = [_sanitize(item, depth + 1) for item in value[:MAX_ITEMS]]
        return [item for item in items if item is not None]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:40]:
            if key in SENSITIVE or not isinstance(key, str) or not _text(key, 80):
                continue
            cleaned = _sanitize(item, depth + 1)
            if cleaned is not None:
                result[_text(key, 80)] = cleaned
        return result or None
    return None


def describe(message_type, attachment, body=None, *, names=None, message_ids=None):
    """Structured view of one message. `names` and `message_ids` are optional lookups."""
    names, message_ids = names or {}, message_ids or {}
    kind, rich = classify(message_type)
    obj = parse_object(attachment) or {}
    if obj.get("_unparsed"):
        obj = {}
        unparsed = True
    else:
        unparsed = False
    photos = _photos(obj) if kind in {"photo", "photos"} else []
    video = audio = file_info = link = emoticon = location = None
    contact = profile = schedule = reply = None
    if kind == "video" and isinstance(obj, dict):
        video = {
            "mime": _text(obj.get("mt") or obj.get("mime"), 80),
            "width": _int(obj.get("w", obj.get("width"))),
            "height": _int(obj.get("h", obj.get("height"))),
            "size": _int(obj.get("s", obj.get("size"))),
            "duration_ms": _int(obj.get("d", obj.get("duration"))),
            "url": _url(obj.get("url")),
            "thumbnail_url": _url(obj.get("thumbnailUrl")),
            "expires_at": _int(obj.get("expire"), 4_102_444_800),
        }
    if kind == "audio" and isinstance(obj, dict):
        audio = {
            "duration_ms": _int(obj.get("d", obj.get("duration"))),
            "size": _int(obj.get("s", obj.get("size"))),
            "expires_at": _int(obj.get("expire"), 4_102_444_800),
        }
    if kind == "file" and isinstance(obj, dict):
        file_info = {
            "name": _text(obj.get("name") or obj.get("fileName"), 180),
            "mime": _text(obj.get("mt") or obj.get("mime"), 80),
            "size": _int(obj.get("size", obj.get("s"))),
            "url": _url(obj.get("url")),
            "expires_at": _int(obj.get("expire"), 4_102_444_800),
        }
    if kind in {"link", "text", "reply", "unknown"}:
        link = _link(obj)
    if kind in {"emoticon", "sticker"} and isinstance(obj, dict):
        path = _text(obj.get("path"), 300)
        emoticon = {
            "name": _text(obj.get("name") or obj.get("alt"), 200),
            "alt": _text(obj.get("alt")),
            "path": path,
            "mime": _text(obj.get("type"), 80),
            "width": _int(obj.get("width")),
            "height": _int(obj.get("height")),
            "image_url": _url(path) or _url(obj.get("url")),
            "sound_url": _url(obj.get("sound")),
        }
    if kind == "location" and isinstance(obj, dict):
        lat, lng = _coords(obj.get("lat"), obj.get("lng"))
        location = {
            "name": _text(obj.get("t") or obj.get("title") or obj.get("name")),
            "address": _text(obj.get("a") or obj.get("address")),
            "latitude": lat,
            "longitude": lng,
        }
    if kind == "contact" and isinstance(obj, dict):
        contact = {"name": _text(obj.get("name")), "has_card": bool(_url(obj.get("url")))}
    if kind == "profile" and isinstance(obj, dict):
        user = _int(obj.get("userId"), 9223372036854775807)
        profile = {
            "user_id": str(user) if user else None,
            "nickname": _text(obj.get("nickName"), 512),
            "status_message": _text(obj.get("statusMessage")),
            "image_url": _url(obj.get("fullProfileImageUrl") or obj.get("profileImageUrl")),
        }
    if kind == "schedule" and isinstance(obj, dict):
        schedule = {
            "title": _text(obj.get("title") or obj.get("subject")),
            "location": _text(obj.get("location") or obj.get("loc") or obj.get("a")),
            "time_ms": _int(obj.get("time") or obj.get("eventAt") or obj.get("startAt"), 4_102_444_800_000),
        }
    if kind == "reply" and isinstance(obj, dict):
        source = _int(obj.get("src_logId"), 9223372036854775807)
        author = _int(obj.get("src_userId"), 9223372036854775807)
        reply = {
            "source_log_id": str(source) if source else None,
            "source_message_id": message_ids.get(str(source)) if source else None,
            "source_user_id": str(author) if author else None,
            "source_user_name": names.get(str(author)) if author else None,
            "source_type": str(_int(obj.get("src_type"), 100000)) if _int(obj.get("src_type"), 100000) is not None else None,
            "preview": _text(obj.get("src_message")),
            "attach_type": _int(obj.get("attach_type"), 1000),
        }
    mentions, all_mention = _mentions(obj, names)
    feed = _feed(body) if kind == "feed" else None
    images = []
    for photo in photos:
        entry = _image_entry("photo", photo)
        if entry:
            images.append(entry)
    if video and (video.get("thumbnail_url") or (video.get("url") and (video.get("mime") or "").startswith("image/"))):
        images.append(
            {
                "role": "video",
                "index": 0,
                "mime": "image/jpeg" if video.get("thumbnail_url") else video.get("mime"),
                "width": video.get("width"),
                "height": video.get("height"),
                "url": None,
                "thumbnail_url": video.get("thumbnail_url"),
            }
        )
    for role, record, key in (
        ("link", link, "image_url"),
        ("emoticon", emoticon, "image_url"),
        ("profile", profile, "image_url"),
    ):
        if record and record.get(key):
            images.append(
                {
                    "role": role,
                    "index": 0,
                    "mime": record.get("mime") if role == "emoticon" else None,
                    "width": record.get("width") if role == "emoticon" else None,
                    "height": record.get("height") if role == "emoticon" else None,
                    "url": record[key],
                    "thumbnail_url": None,
                }
            )
    reactions = _sanitize(obj.get("reactions") or obj.get("reaction")) if isinstance(obj, dict) else None
    consumed = {
        "url", "thumbnailUrl", "thumbnail_url", "thumbnailWidth", "thumbnailHeight",
        "imageUrls", "urls", "thumbnailUrls", "thumbnailWidths", "thumbnailHeights",
        "w", "h", "s", "size", "width", "height", "mt", "mime", "cmt", "caption", "expire",
        "d", "duration", "name", "fileName", "scrapData", "title", "description", "content",
        "canonicalUrl", "mainImageUrl", "imageUrl", "path", "alt", "type",
        "sound", "lat", "lng", "a", "address", "t", "userId", "nickName", "statusMessage",
        "fullProfileImageUrl", "profileImageUrl", "subject", "location", "loc", "time",
        "eventAt", "startAt", "src_logId", "src_userId", "src_message", "src_type",
        "attach_type", "attach_only", "mentions", "src_mentions", "all_mention",
        "wl", "hl", "sl", "mtl", "reactions", "reaction", "feedType", "member", "members",
        "inviter",
    }
    unknown = None
    if kind == "unknown" or unparsed:
        unknown = _sanitize({k: v for k, v in obj.items() if k not in SENSITIVE}) if obj else None
        if unparsed:
            unknown = {"unparsed": True}
    elif isinstance(obj, dict):
        extra = {k: v for k, v in obj.items() if k not in consumed and k not in SENSITIVE}
        unknown = _sanitize(extra) if extra else None
    present = any(
        (
            photos, video, audio, file_info, link, emoticon, location, contact, profile,
            schedule, reply, mentions, feed, images, reactions, unknown,
        )
    )
    return {
        "message_type": None if message_type is None else str(message_type)[:32],
        "attachment_type": kind,
        "has_attachment": bool(rich or present),
        "deleted": _deleted(message_type),
        "photos": photos,
        "video": video,
        "audio": audio,
        "file": file_info,
        "link": link,
        "emoticon": emoticon,
        "location": location,
        "contact": contact,
        "profile": profile,
        "schedule": schedule,
        "reply": reply,
        "mentions": mentions,
        "all_mention": all_mention,
        "feed": feed,
        "reactions": reactions if isinstance(reactions, (dict, list)) else None,
        "images": images,
        "unknown_fields": unknown,
    }


def _deleted(message_type):
    try:
        return bool(int(str(message_type)) & DELETED_BIT)
    except (TypeError, ValueError):
        return False


def image_target(view, variant, index):
    """Pick the CDN URL for one viewable image. Raises ValueError with a stable code."""
    images = view.get("images") or []
    if not images:
        raise ValueError("not_an_image")
    if not 0 <= index < len(images):
        raise ValueError("index_out_of_range")
    image = images[index]
    if image.get("role") == "video" and variant == "original":
        raise ValueError("video_not_downloaded")
    url = image.get("thumbnail_url") if variant == "thumbnail" else image.get("url")
    if not url:
        raise ValueError("thumbnail_unavailable" if variant == "thumbnail" else "image_unavailable")
    return image, url
