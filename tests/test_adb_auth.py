import base64
import struct
import subprocess
from pathlib import Path
from unittest.mock import Mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from device import adb_auth, cli


def test_provision_preserves_private_identity_and_restricts_keys(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ("device", "iris")]
    originals = []
    for root in roots:
        folder = root / ".android"
        folder.mkdir(parents=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        (folder / "adbkey").write_bytes(private)
        originals.append(private)
        raw = base64.b64decode(adb_auth.public_key(private))
        assert len(raw) == 524
        words, inverse = struct.unpack("<II", raw[:8])
        assert words == 64
        assert int.from_bytes(raw[8:264], "little") == key.public_key().public_numbers().n
        assert (inverse * key.public_key().public_numbers().n) % (1 << 32) == (1 << 32) - 1
    monkeypatch.setattr(adb_auth.os, "chown", Mock())
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("must preserve keys")))
    android = tmp_path / "android"
    assert adb_auth.provision(*roots, android) == 2
    target = android / "misc/adb/adb_keys"
    assert target.stat().st_mode & 0o777 == 0o640
    assert len(target.read_text().splitlines()) == 2
    assert adb_auth.provision(*roots, android) == 2
    for root, original in zip(roots, originals, strict=True):
        assert Path(root, ".android/adbkey").read_bytes() == original


def test_secure_adb_reboot_recovers_root_only_after_authentication(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", Mock())
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    adb = Mock(side_effect=["2000", "restarting adbd as root", "0"])
    monkeypatch.setattr(cli, "adb", adb)
    cli.connect()
    assert ("root",) in [call.args for call in adb.call_args_list]
    adb.reset_mock(side_effect=True)
    adb.return_value = ""
    cli.connect()
    assert ("root",) not in [call.args for call in adb.call_args_list]
