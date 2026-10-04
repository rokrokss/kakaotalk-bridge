"""Provision only the two collector ADB identities before Android starts."""

import base64
import os
import struct
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def public_key(private):
    key = serialization.load_pem_private_key(private, password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
        raise ValueError("ADB requires a 2048-bit RSA identity")
    numbers = key.public_key().public_numbers()
    n, e = numbers.n, numbers.e
    encoded = (
        struct.pack("<II", 64, -pow(n, -1, 1 << 32) % (1 << 32))
        + n.to_bytes(256, "little")
        + pow(2, 4096, n).to_bytes(256, "little")
        + struct.pack("<I", e)
    )
    return base64.b64encode(encoded).decode()


def client_key(root):
    directory = Path(root) / ".android"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    private = directory / "adbkey"
    if not private.exists():
        # Local generation only: no daemon, device connection or key in command arguments.
        subprocess.run(["adb", "keygen", str(private)], check=True, capture_output=True)
    private.chmod(0o600)
    public = public_key(private.read_bytes())
    (directory / "adbkey.pub").write_text(public + " bridge@collector\n")
    return public


def provision(device="/device-state", iris="/iris-state", android="/android-data"):
    keys = sorted({client_key(device), client_key(iris)})
    target = Path(android) / "misc/adb"
    target.mkdir(mode=0o2750, parents=True, exist_ok=True)
    os.chown(target, 1000, 2000)
    target.chmod(0o2750)
    staged = target / "adb_keys.bridge-next"
    with staged.open("w") as output:
        output.write("".join(key + " bridge@collector\n" for key in keys))
    os.chown(staged, 1000, 2000)
    staged.chmod(0o640)
    staged.replace(target / "adb_keys")
    return len(keys)


if __name__ == "__main__":
    os.umask(0o077)
    count = provision()
    print(f"ADB authorization ready for {count} collector identities; private keys preserved.")
