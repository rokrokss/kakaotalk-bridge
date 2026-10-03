import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Collector:
    def __init__(self, config):
        self.config = config

    def get(self, path, **params):
        request = Request(
            self.config.api_url.rstrip("/") + path + "?" + urlencode(params),
            headers={"Authorization": "Bearer " + self.config.read_token},
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError
                return json.loads(data)
        except (OSError, ValueError):
            raise RuntimeError("collector_unavailable") from None

    def checkpoint(self):
        return self.get("/v1/checkpoint")

    def messages(self, after, limit=50, conversation_ref=None):
        filters = {"conversation_ref": conversation_ref} if conversation_ref else {}
        return self.get("/v1/messages", after=after, limit=limit, **filters)
