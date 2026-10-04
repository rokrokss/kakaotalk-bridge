"""Encrypted offline volume snapshots. Authenticate before writing restored files."""

import base64
import errno
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"KCS1\n"
CHUNK = 1024 * 1024
VOLUMES = {
    "android-data",
    "collector-data",
    "device-state",
    "iris-state",
    "admin-state",
    "dot-state",
    "passkey-state",
}


class EncryptedWriter(io.RawIOBase):
    def __init__(self, output, key):
        self.output = output
        nonce = os.urandom(12)
        header = MAGIC + nonce
        self.encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        self.encryptor.authenticate_additional_data(header)
        output.write(header)

    def write(self, data):
        self.output.write(self.encryptor.update(data))
        return len(data)

    def finish(self):
        self.output.write(self.encryptor.finalize())
        self.output.write(self.encryptor.tag)


def create(output, key, snapshot, project):
    encrypted = EncryptedWriter(output, key)

    def attributes(info):
        if not (info.isfile() or info.isdir() or info.issym() or info.islnk()):
            return None  # Unix sockets are recreated by their owning process.
        source = (
            snapshot.parent / info.name
            if info.name.startswith("snapshot/")
            else project / info.name.removeprefix("project/")
        )
        if source.exists() and not source.is_symlink():
            try:
                names = getattr(os, "listxattr", lambda path: [])(source)
            except OSError as exc:
                if exc.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP):
                    raise
                names = []  # Some host bind filesystems do not implement xattrs.
            attrs = {name: base64.b64encode(os.getxattr(source, name)).decode() for name in names}
            if attrs:
                info.pax_headers["kakao.xattrs"] = json.dumps(attrs)
        return info

    with tarfile.open(fileobj=encrypted, mode="w|") as archive:
        for name in sorted(VOLUMES):
            if (snapshot / name).is_dir():
                archive.add(snapshot / name, arcname="snapshot/" + name, filter=attributes)
        for name in (".env", "secrets"):
            if not (project / name).exists():
                raise ValueError("Incomplete installation; cannot snapshot")
            archive.add(project / name, arcname="project/" + name, filter=attributes)
    encrypted.finish()


def decrypt(source, destination, key):
    header = source.read(len(MAGIC) + 12)
    if len(header) != len(MAGIC) + 12 or not header.startswith(MAGIC):
        raise ValueError("Unsupported snapshot")
    decryptor = Cipher(algorithms.AES(key), modes.GCM(header[len(MAGIC) :])).decryptor()
    decryptor.authenticate_additional_data(header)
    tail = b""
    with destination.open("xb") as output:
        destination.chmod(0o600)
        while chunk := source.read(CHUNK):
            data = tail + chunk
            if len(data) > 16:
                output.write(decryptor.update(data[:-16]))
            tail = data[-16:]
        if len(tail) != 16:
            raise ValueError("Truncated snapshot")
        output.write(decryptor.finalize_with_tag(tail))


def member_target(member, snapshot, project):
    parts = PurePosixPath(member.name).parts
    if any(part in ("..", "") for part in parts) or member.name.startswith("/") or len(parts) < 2:
        raise ValueError("Unsafe archive path")
    if parts[0] == "snapshot" and parts[1] in VOLUMES:
        return snapshot.joinpath(*parts[1:])
    if parts[0] == "project" and parts[1] in (".env", "secrets"):
        if member.issym() or member.islnk():
            raise ValueError("Configuration may not contain links")
        return project.joinpath(*parts[1:])
    raise ValueError("Unknown snapshot component")


def extract_verified(plain, snapshot, project):
    # New, empty volumes only. No existing state can be overwritten by this function.
    for root in (snapshot, project):
        if root == snapshot:
            if any(any(p.iterdir()) for p in root.iterdir() if p.is_dir()):
                raise ValueError("Restore volumes must be empty")
        elif any(root.iterdir()):
            raise ValueError("Restore configuration directory must be empty")
    with tarfile.open(plain, "r:") as archive:
        members = archive.getmembers()
        targets = {m.name: member_target(m, snapshot, project) for m in members}
        if len(targets) != len(members):
            raise ValueError("Duplicate archive entry")
        if (
            not {
                "project/.env",
                "project/secrets",
                "snapshot/android-data",
                "snapshot/collector-data",
                "snapshot/device-state",
            }
            <= targets.keys()
        ):
            raise ValueError("Incomplete snapshot")
        links = {m.name for m in members if m.issym() or m.islnk()}
        for member in members:
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError("Unsupported archive entry")
            if any(str(parent) in links for parent in PurePosixPath(member.name).parents):
                raise ValueError("Archive writes through a link")
            if member.islnk() and (
                member.linkname not in targets
                or member.linkname in links
                or member.linkname.split("/")[:2] != member.name.split("/")[:2]
            ):
                raise ValueError("Unsafe hard link")
        # Materialize files before links, never following an archive-supplied symlink.
        for member in sorted(members, key=lambda m: m.issym() or m.islnk()):
            target = targets[member.name]
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(exist_ok=True)
            elif member.isfile():
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, CHUNK)
            elif member.islnk():
                os.link(targets[member.linkname], target)
            else:
                os.symlink(member.linkname, target)
        for member in reversed(members):
            target = targets[member.name]
            uid, gid = member.uid, member.gid
            if member.name.startswith("project/"):
                uid = int(os.getenv("RESTORE_UID", str(os.getuid())))
                gid = int(os.getenv("RESTORE_GID", str(os.getgid())))
            os.chown(target, uid, gid, follow_symlinks=False)
            if not member.issym():
                os.chmod(target, member.mode & 0o7777)
                os.utime(target, (member.mtime, member.mtime))
                for name, value in json.loads(member.pax_headers.get("kakao.xattrs", "{}")).items():
                    os.setxattr(target, name, base64.b64decode(value, validate=True))


def reset_external_state(snapshot, project):
    for name in ("dot-state", "collector-data", "passkey-state"):
        if not any((snapshot / name).iterdir()):
            os.chown(snapshot / name, 10001, 10001)
    # Restoring old cursors must not silently skip or acknowledge messages in a new timeline.
    database = snapshot / "collector-data/collector.db"
    with sqlite3.connect(database) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Invalid collector database")
        db.execute(
            "INSERT INTO metadata VALUES('cursor_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(uuid.uuid4()),),
        )
        db.execute(
            "INSERT INTO gaps(started_at,ended_at,reason) VALUES(?,?,?)",
            (datetime.now(UTC).isoformat(), None, "full_snapshot_restored"),
        )
    # Browser credentials, OAuth grants, and event callbacks are never revived by a backup.
    for filename in ("admin-state/admin.db", "dot-state/dot.db", "passkey-state/passkeys.db"):
        path = snapshot / filename
        if path.exists():
            with sqlite3.connect(path) as db:
                if filename.startswith("admin"):
                    db.execute(
                        "DELETE FROM records WHERE kind IN ('session','pair','kakao','kakao-flow','kakao-enroll','google','google-flow')"
                    )
                elif filename.startswith("passkey"):
                    db.execute("DELETE FROM records WHERE kind NOT IN ('passkey','credential')")
                else:
                    db.execute("DELETE FROM records WHERE kind != 'settings'")


def restore(source, key, snapshot, project, work):
    plain = work / "archive.tar"
    try:
        decrypt(source, plain, key)
        extract_verified(plain, snapshot, project)
        reset_external_state(snapshot, project)
    finally:
        plain.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    key = bytes.fromhex(Path("/key").read_text().strip())
    if len(key) != 32:
        raise ValueError("Invalid recovery key")
    if sys.argv[1] == "create":
        create(sys.stdout.buffer, key, Path("/snapshot"), Path("/project"))
    elif sys.argv[1] == "restore":
        restore(sys.stdin.buffer, key, Path("/snapshot"), Path("/project"), Path("/work"))
    else:
        raise ValueError("Unknown snapshot operation")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — do not print decrypted paths or data
        print(
            "Snapshot operation failed. Check the recovery key, disk space and archive integrity.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
