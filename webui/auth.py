"""Single-owner login. Pairing codes are issued only from the server CLI."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from dot_plugin.storage import State
from server.config import secret


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OwnerAuth:
    def __init__(self, path, token):
        key = base64.urlsafe_b64encode(hashlib.sha256(("admin-auth-v1:" + token).encode()).digest())
        self.state = State(str(path), key)

    def configured(self):
        return bool(self.state.get("owner", "password"))

    def issue_pair(self, policy="local"):
        value = secrets.token_urlsafe(32)
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            # Only the most recently issued link is usable.
            db.execute("DELETE FROM records WHERE kind='pair'")
            self.state.put(
                "pair", digest(value), {"expires": time.time() + 600, "policy": policy}, db=db
            )
        return value

    def check_pair(self, value, password=None, *, policy="local"):
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.state.get("pair", digest(value), db=db)
            if (
                not record
                or record["expires"] <= time.time()
                or record.get("policy", "local") != policy
            ):
                return False
            owner = self.state.get("owner", "password", db=db)
            if not owner and policy == "local":
                if not password or not 12 <= len(password) <= 256:
                    return False
                salt = secrets.token_bytes(16)
                hashed = self.hash_password(password, salt)
                self.state.put("owner", "password", {"salt": salt.hex(), "hash": hashed}, db=db)
            self.state.delete("pair", digest(value), db=db)
        return True

    @staticmethod
    def hash_password(password, salt):
        return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()

    def check_password(self, password):
        owner = self.state.get("owner", "password")
        salt = bytes.fromhex(owner["salt"]) if owner else b"\x00" * 16
        hashed = self.hash_password(password, salt)
        return bool(owner and hmac.compare_digest(hashed, owner["hash"]))

    def create_session(self, ttl, label, *, exclusive=False, policy="local", origin=""):
        key, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        record = {
            "cookie_scope": "admin-v2",
            "csrf": csrf,
            "created": now,
            "expires": now + ttl,
            "label": label[:120],
            "policy": policy,
            "origin": origin,
        }
        with self.state.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            for identity, old in self.state.all("session", db=db):
                if exclusive or old["expires"] <= now:
                    self.state.delete("session", identity, db=db)
            active = sorted(self.state.all("session", db=db), key=lambda item: item[1]["created"])
            for identity, _ in active[:-9]:
                self.state.delete("session", identity, db=db)
            self.state.put("session", digest(key), record, db=db)
        return key, record

    def session(self, key):
        record = self.state.get("session", digest(key)) if key else None
        if not record or record["expires"] <= time.time():
            return None
        return record

    def sessions(self, current):
        return [
            {
                "id": identity,
                "current": identity == digest(current),
                **{k: value[k] for k in ("created", "expires", "label")},
            }
            for identity, value in self.state.all("session")
            if value["expires"] > time.time()
        ]

    def revoke(self, identity):
        self.state.delete("session", identity)

    def reset_password(self):
        with self.state.transaction() as db:
            db.execute("DELETE FROM records WHERE kind IN ('owner', 'session', 'pair')")


def main():
    parser = argparse.ArgumentParser(description="비공개 관리자 접근 관리")
    parser.add_argument("command", choices=["pair", "reset-password", "info"])
    args = parser.parse_args()
    auth = OwnerAuth(os.getenv("ADMIN_AUTH_DB", "/auth/admin.db"), secret("ADMIN_TOKEN"))
    mode = os.getenv("ADMIN_AUTH_MODE", "passkey")
    if mode not in {"local", "passkey"}:
        raise SystemExit("ADMIN_AUTH_MODE must be passkey or local; run ./bridge passkey-login")
    from server.passkey_client import PasskeyClient

    passkeys = PasskeyClient("admin")
    if args.command == "info":
        info = passkeys.call("admin", "info") if mode == "passkey" else {}
        print(
            json.dumps(
                {
                    "mode": mode,
                    "configured": info.get("configured", auth.configured()),
                    "origin": info.get("admin_origin"),
                    "owner_registered": info.get("registered", auth.configured()),
                }
            )
        )
    elif args.command == "reset-password":
        auth.reset_password()
        print(
            "로컬 비밀번호와 브라우저 로그인을 초기화했습니다. 패스키 또는 ./bridge admin --recovery를 사용하세요."
        )
    else:
        policy = passkeys.call("admin", "info")["policy"] if mode == "passkey" else "local"
        print(auth.issue_pair(policy))


if __name__ == "__main__":
    main()
