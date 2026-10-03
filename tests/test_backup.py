import os

import pytest
from cryptography.exceptions import InvalidTag

from server.maintenance import backup, restore
from server.models import Observation
from server.store import Store
from tests.test_api import event


def test_encrypted_backup_restore_and_tamper_preserves_live_db(tmp_path, monkeypatch):
    secret = tmp_path / "key"
    secret.write_text(os.urandom(32).hex())
    monkeypatch.setenv("BACKUP_KEY_FILE", str(secret))
    original = Store(str(tmp_path / "original.db"))
    original.ingest(Observation.model_validate(event()))
    file = tmp_path / "backup.kcb"
    backup(original.path, str(file))
    assert "안녕하세요".encode() not in file.read_bytes()
    target = str(tmp_path / "restored.db")
    restore(str(file), target)
    assert Store(target).messages()["items"][0]["body"] == "안녕하세요"
    assert (
        Store(target).status()["coverage"]["cursor_epoch"]
        != original.status()["coverage"]["cursor_epoch"]
    )
    with pytest.raises(ValueError, match="Database exists"):
        restore(str(file), target)
    broken = bytearray(file.read_bytes())
    broken[-1] ^= 1
    file.write_bytes(broken)
    with pytest.raises(InvalidTag):
        restore(str(file), target, replace=True)
    assert len(Store(target).messages()["items"]) == 1
