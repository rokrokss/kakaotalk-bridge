import os
from dataclasses import dataclass
from pathlib import Path


def secret(name: str) -> str:
    value = Path(os.environ.get(f"{name}_FILE", f"/run/secrets/{name.lower()}")).read_text().strip()
    if len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 characters")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: str
    ingest_token: str
    read_token: str
    device_token: str
    device_id: str = "personal-tablet"
    retention_days: int = 30
    heartbeat_timeout: int = 180

    @classmethod
    def from_env(cls):
        tokens = [secret(n) for n in ("INGEST_TOKEN", "READ_TOKEN", "DEVICE_TOKEN")]
        if len(set(tokens)) != 3:
            raise ValueError("Use distinct credentials for ingest, read and device scopes")
        return cls(
            os.getenv("DB_PATH", "/data/collector.db"),
            *tokens,
            device_id=os.getenv("DEVICE_ID", "personal-tablet"),
            retention_days=max(1, int(os.getenv("RETENTION_DAYS", "30"))),
        )
