import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class QueryError(ValueError):
    pass


class Collector:
    def __init__(self, config):
        self.config = config

    def get(self, path, **params):
        request = Request(
            self.config.api_url.rstrip("/")
            + path
            + "?"
            + urlencode(
                {
                    k: str(v).lower() if isinstance(v, bool) else v
                    for k, v in params.items()
                    if v is not None
                }
            ),
            headers={"Authorization": "Bearer " + self.config.read_token},
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError
                return json.loads(data)
        except HTTPError as exc:
            if exc.code == 400:
                raise QueryError("invalid_query_or_expired_cursor") from None
            raise RuntimeError("collector_unavailable") from None
        except (OSError, ValueError):
            raise RuntimeError("collector_unavailable") from None

    def checkpoint(self):
        return self.get("/v1/checkpoint")

    def messages(self, after, limit=50):
        return self.get("/v1/messages", after=after, limit=limit)
