import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROTOCOL = "2026-07-28"
SCOPES = "kakao.read kakao.events"
EVENT = "message.created"


@dataclass(frozen=True)
class Config:
    public_url: str
    database: str
    link_key: str
    storage_key: bytes
    api_url: str = "http://api:8000"
    read_token: str = ""
    approval_mode: str = "passkey"

    def __post_init__(self):
        if self.approval_mode not in {"key", "admin", "passkey"}:
            raise ValueError("Invalid approval mode")
        u = urlsplit(self.public_url)
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path
        ):
            raise ValueError(
                "DOT_PUBLIC_URL must be a canonical HTTPS origin without a trailing slash"
            )
        if self.approval_mode == "key" and len(self.link_key) < 32:
            raise ValueError("Dot linking key must contain at least 32 characters")

    @property
    def resource(self):
        return self.public_url + "/mcp"

    @classmethod
    def from_env(cls, *, control=False):
        def secret(name):
            return (
                Path(os.getenv(name + "_FILE", "/run/secrets/" + name.lower())).read_text().strip()
            )

        return cls(
            os.environ["DOT_PUBLIC_URL"].rstrip("/"),
            os.getenv("DOT_DB_PATH", "/data/dot.db"),
            secret("MCP_LINK_KEY") if os.getenv("DOT_APPROVAL_MODE", "passkey") == "key" else "",
            secret("MCP_STORAGE_KEY").encode(),
            os.getenv("API_URL", "http://api:8000"),
            "" if control else secret("READ_TOKEN"),
            os.getenv("DOT_APPROVAL_MODE", "passkey"),
        )
