"""Transactional source refresh for a Lima checkout, excluding persistent state."""

import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PERSISTENT = {".bridge", ".env", ".git", "secrets", "inputs", "artifacts", "backups"}
CODE_DIRS = {
    "android",
    "assets",
    "deploy",
    "device",
    "docs",
    "docker",
    "dot_plugin",
    "iris",
    "ops",
    "scripts",
    "server",
    "tests",
    "webui",
    ".github",
}


def rollback(root):
    journal = root / ".bridge/source-journal.json"
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    scratch = Path(record["scratch"])
    for name, existed in record["items"].items():
        previous, target = scratch / "previous" / name, root / name
        if previous.exists() or not existed:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            if previous.exists():
                previous.rename(target)
    journal.unlink()
    shutil.rmtree(scratch)


def apply(root, archive_path):
    rollback(root)
    state = root / ".bridge"
    state.mkdir(mode=0o700, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="source-", dir=state))
    incoming, previous = scratch / "incoming", scratch / "previous"
    incoming.mkdir()
    previous.mkdir()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts
            if (
                not parts
                or parts[0] in PERSISTENT
                or parts[0].startswith(".env")
                or ".." in parts
                or member.name.startswith("/")
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Unsafe source archive")
        archive.extractall(incoming, filter="data")
    names = {p.name for p in incoming.iterdir()} | {
        name for name in CODE_DIRS if (root / name).exists()
    }
    if not (incoming / "ops/cli.py").exists() or not (incoming / "compose.yaml").exists():
        raise ValueError("Incomplete source archive")
    journal = state / "source-journal.json"
    descriptor, temporary = tempfile.mkstemp(dir=state)
    with os.fdopen(descriptor, "w") as output:
        json.dump(
            {"scratch": str(scratch), "items": {name: (root / name).exists() for name in names}},
            output,
        )
    os.replace(temporary, journal)
    try:
        for name in names:
            if (root / name).exists():
                (root / name).rename(previous / name)
            if (incoming / name).exists():
                (incoming / name).rename(root / name)
    except BaseException:
        rollback(root)
        raise


def commit(root):
    journal = root / ".bridge/source-journal.json"
    if journal.exists():
        record = json.loads(journal.read_text())
        journal.unlink()  # The new source is committed before optional cleanup.
        # Retain the previous source for diagnosis; it contains no installation keys.
        destination = root / ".bridge/previous-source"
        if destination.exists():
            shutil.rmtree(destination)
        (Path(record["scratch"]) / "previous").rename(destination)
        shutil.rmtree(record["scratch"])


if __name__ == "__main__":
    command, root = sys.argv[1], Path(sys.argv[2])
    if command == "apply":
        apply(root, sys.argv[3])
    elif command == "rollback":
        rollback(root)
    elif command == "commit":
        commit(root)
    else:
        raise SystemExit(2)
