#!/usr/bin/env python3
"""Create plugin-only credentials without replacing existing secrets or printing them."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

root = Path(__file__).resolve().parents[1] / "secrets"
root.mkdir(mode=0o700, exist_ok=True)
for name, value in (
    ("mcp_approval_token", secrets.token_urlsafe(32)),
    ("mcp_passkey_token", secrets.token_urlsafe(32)),
    ("mcp_link_key", secrets.token_urlsafe(32)),
    ("mcp_storage_key", Fernet.generate_key().decode()),
):
    try:
        descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"기존 secrets/{name} 유지")
    else:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(value + "\n")
        print(f"secrets/{name} 생성 완료 (키 값은 표시하지 않습니다)")
