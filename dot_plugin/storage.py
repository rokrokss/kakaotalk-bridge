"""Small persistent state store; OAuth credentials and callbacks are encrypted at rest."""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class State:
    def __init__(self, path, key):
        self.path = path
        self.crypto = Fernet(key)
        self.lock = threading.RLock()
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, value BLOB NOT NULL, PRIMARY KEY(kind,id))"
            )
        os.chmod(path, 0o600)

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def get(self, kind, key, default=None, *, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.get(kind, key, default, db=conn)
        row = db.execute("SELECT value FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(self.crypto.decrypt(row[0])) if row else default

    def put(self, kind, key, value, *, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.put(kind, key, value, db=conn)
        data = self.crypto.encrypt(canonical(value).encode())
        db.execute(
            "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value",
            (kind, key, data),
        )

    def delete(self, kind, key, *, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.delete(kind, key, db=conn)
        db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))

    def all(self, kind, *, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.all(kind, db=conn)
        return [
            (key, json.loads(self.crypto.decrypt(value)))
            for key, value in db.execute("SELECT id,value FROM records WHERE kind=?", (kind,))
        ]

    def take(self, kind, key):
        with self.transaction() as db:
            db.execute("BEGIN IMMEDIATE")
            result = self.get(kind, key, db=db)
            self.delete(kind, key, db=db)
            return result
