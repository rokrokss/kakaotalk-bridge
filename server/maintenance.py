"""Offline restore / online SQLite backup, encrypted with streaming AES-256-GCM."""

import argparse
import os
import sqlite3
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"KCBK1\n"
CHUNK = 1024 * 1024


def key():
    value = bytes.fromhex(
        Path(os.getenv("BACKUP_KEY_FILE", "/run/secrets/backup_key")).read_text().strip()
    )
    if len(value) != 32:
        raise ValueError("Backup key must be 32 random bytes encoded as hex")
    return value


def backup(db_path: str, destination: str):
    # Backup API includes committed WAL contents without copying live database files.
    with tempfile.TemporaryDirectory() as folder:
        snapshot = str(Path(folder) / "snapshot.db")
        source = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        nonce = os.urandom(12)
        header = MAGIC + nonce
        encryptor = Cipher(algorithms.AES(key()), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(header)
        with open(snapshot, "rb") as plain, open(destination, "xb") as encrypted:
            os.chmod(destination, 0o600)
            encrypted.write(header)
            encrypted.writelines(
                encryptor.update(chunk) for chunk in iter(lambda: plain.read(CHUNK), b"")
            )
            encrypted.write(encryptor.finalize())
            encrypted.write(encryptor.tag)


def restore(source: str, db_path: str, replace=False):
    target = Path(db_path)
    if target.exists() and not replace:
        raise ValueError("Database exists; stop the API and explicitly use --replace")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix=".restore-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as plain, open(source, "rb") as encrypted:
            header = encrypted.read(len(MAGIC) + 12)
            if len(header) != len(MAGIC) + 12 or not header.startswith(MAGIC):
                raise ValueError("Not a supported collector backup")
            encrypted.seek(-16, os.SEEK_END)
            tag = encrypted.read(16)
            remaining = encrypted.tell() - 16 - len(header)
            if remaining <= 0:
                raise ValueError("Truncated backup")
            decryptor = Cipher(
                algorithms.AES(key()), modes.GCM(header[len(MAGIC) :], tag)
            ).decryptor()
            decryptor.authenticate_additional_data(header)
            encrypted.seek(len(header))
            while remaining:
                chunk = encrypted.read(min(CHUNK, remaining))
                if not chunk:
                    raise ValueError("Truncated backup")
                remaining -= len(chunk)
                plain.write(decryptor.update(chunk))
            plain.write(decryptor.finalize())  # Tag failure leaves the live DB untouched.
        restored = sqlite3.connect(scratch)
        try:
            if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid SQLite backup")
            if restored.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("Unsupported backup schema")
            restored.execute(
                "INSERT INTO metadata VALUES('cursor_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(uuid.uuid4()),),
            )
            instant = datetime.now(UTC).isoformat()
            restored.execute(
                "INSERT INTO gaps(started_at,ended_at,reason) VALUES(?,?,?)",
                (instant, instant, "backup_restored_reset_consumer_cursor"),
            )
            restored.commit()
            restored.execute("PRAGMA journal_mode=DELETE")
        finally:
            restored.close()
        if target.exists():
            old = sqlite3.connect(db_path)
            try:
                if old.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                    raise ValueError("Database is busy; stop every database reader/writer first")
            finally:
                old.close()
        for suffix in ("-wal", "-shm"):
            Path(db_path + suffix).unlink(missing_ok=True)
        os.replace(scratch, target)
    finally:
        Path(scratch).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("file")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    path = os.getenv("DB_PATH", "/data/collector.db")
    if args.command == "backup":
        backup(path, args.file)
    else:
        restore(args.file, path, args.replace)
    print(f"{args.command}: completed")


if __name__ == "__main__":
    main()
