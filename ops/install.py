"""Install and update the Docker stack on this Linux host or inside the Lima VM."""

import base64
import hashlib
import os
import platform
import re
import secrets
import subprocess
import time
from pathlib import Path

from ops import backup, cli, doctor
from ops.errors import BridgeError


def init_secrets(source):
    required = (
        "admin_token",
        "ingest_token",
        "read_token",
        "device_token",
        "backup_key",
        "tls_cert.pem",
        "tls_key.pem",
    )
    present = [name for name in required if (cli.ROOT / "secrets" / name).exists()]
    if present and any(
        not (cli.ROOT / "secrets" / name).is_file() or not (cli.ROOT / "secrets" / name).stat().st_size
        for name in required
    ):
        raise BridgeError("기존 설치의 인증 키가 없거나 비어 있습니다. 새 키를 만들지 말고 secrets/ 폴더를 백업에서 복구하세요.")
    # This script creates only missing keys and preserves existing TLS/signing material.
    cli.run(
        ["bash", "scripts/init-secrets.sh"],
        env={**os.environ, "BRIDGE_PREBUILT": "0" if source else "1"},
    )
    root = cli.ROOT / "secrets"
    for name, value in (
        ("mcp_link_key", secrets.token_urlsafe(32)),
        ("mcp_storage_key", base64.urlsafe_b64encode(os.urandom(32)).decode()),
        ("mcp_approval_token", secrets.token_urlsafe(32)),
        ("mcp_passkey_token", secrets.token_urlsafe(32)),
    ):
        path = root / name
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(fd, "w") as output:
                output.write(value + "\n")
        elif not path.stat().st_size:
            raise BridgeError(f"인증 키 파일 secrets/{name}이(가) 비어 있습니다. 백업에서 복구한 뒤 계속하세요.")
        path.chmod(0o444)


def host_check():
    if platform.system() != "Linux":
        raise BridgeError("실행 환경에는 Linux가 필요합니다. macOS에서는 ./bridge up으로 Lima VM을 사용하세요.")
    cli.run(["docker", "info"], capture=True)
    if (
        not Path("/sys/module/binder_linux").exists()
        and not Path("/dev/binderfs/binder-control").exists()
    ):
        raise BridgeError("Android Binder 커널 모듈이 없습니다. Binder를 지원하는 Linux 커널을 준비한 뒤 다시 실행하세요.")
    if Path("/dev/binderfs/binder").exists():
        lines = ["services:", "  redroid:", "    volumes:"]
        for name in ("binder", "hwbinder", "vndbinder"):
            lines += [
                "      - type: bind",
                f"        source: /dev/binderfs/{name}",
                f"        target: /dev/{name}",
                "        bind:",
                "          create_host_path: false",
            ]
        cli.atomic(cli.ROOT / ".bridge/host.yaml", "\n".join(lines) + "\n")
    if platform.machine() in ("aarch64", "arm64") and not cli.read_env().get("REDROID_IMAGE"):
        cli.env_update(
            {
                "REDROID_IMAGE": "redroid/redroid:14.0.0_64only-latest@sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa"
            }
        )


def image_config(args):
    if args.source:
        files = (
            cli.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                capture=True,
            ).split("\0")
            if (cli.ROOT / ".git").exists()
            else []
        )
        if not files:
            excluded = {
                ".git",
                ".bridge",
                ".venv",
                ".gradle",
                "build",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                "secrets",
                "inputs",
                "artifacts",
                "backups",
            }
            for folder, directories, names in os.walk(cli.ROOT):
                directories[:] = [name for name in directories if name not in excluded]
                for name in names:
                    if not name.startswith(".env"):
                        files.append(str((Path(folder) / name).relative_to(cli.ROOT)))
        fingerprint = hashlib.sha256()
        for file in sorted(files):
            path = cli.ROOT / file
            if path.is_file() and not path.is_symlink():
                fingerprint.update(
                    file.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest()
                )
        tag = "local-" + fingerprint.hexdigest()[:16]
        refs = {
            kind: f"kakaotalk-bridge/{kind}:{tag}" for kind in ("server", "device", "gateway")
        }
    else:
        if not args.manifest:
            raise BridgeError("--manifest로 GitHub 릴리스의 release.json을 지정하거나, --source로 이 소스를 빌드하세요.")
        refs = cli.manifest(args.manifest)
    return {
        "COLLECTOR_IMAGE": refs["server"],
        "DOT_IMAGE": refs["server"],
        "DEVICE_IMAGE": refs["device"],
        "GATEWAY_IMAGE": refs["gateway"],
    }


def prepare_android_builder():
    if platform.machine() not in ("aarch64", "arm64"):
        return
    # Exercise the actual pinned build image: a registered emulator can still
    # crash in cmp (and make apt report misleading signature failures).
    dockerfile = (cli.ROOT / "docker/device.Dockerfile").read_text()
    image = re.search(
        r"^FROM --platform=linux/amd64 (\S+) AS android-build$", dockerfile, re.MULTILINE
    )
    if not image:
        raise BridgeError("Android 빌드 이미지를 확인할 수 없습니다. 소스 빌드를 다시 시도하세요.")
    probe = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        image[1],
        "sh",
        "-ec",
        "printf probe >/tmp/probe; printf probe | cmp -s - /tmp/probe; java -version",
    ]
    try:
        cli.run(probe, capture=True, timeout=180)
        return
    except (RuntimeError, subprocess.TimeoutExpired):
        print("Android 빌드 에뮬레이터 준비 중…", flush=True)
    # This changes only the amd64 QEMU handler; other architectures and Rosetta
    # registrations are preserved. Runtime containers stay native.
    cli.run(
        [
            "docker",
            "run",
            "--privileged",
            "--rm",
            "tonistiigi/binfmt:qemu-v10.0.4-56@sha256:30cc9a4d03765acac9be2ed0afc23af1ad018aed2c28ea4be8c2eb9afe03fbd1",
            "--uninstall",
            "qemu-x86_64",
            "--install",
            "amd64",
        ]
    )
    cli.run(probe, capture=True, timeout=180)


def prepare_images(args):
    previous = (cli.ROOT / ".env").read_text()
    refs = image_config(args)
    cli.env_update(refs)
    try:
        if args.source:
            cli.progress("소스에서 이미지 만드는 중… 처음에는 수십 분 걸릴 수 있습니다.")
            prepare_android_builder()
            cli.compose("build", "api", "device-agent", "gateway")
        else:
            cli.progress("이미지 내려받는 중…")
            cli.compose("pull", *cli.SERVICES, "dot-plugin", "dot-control", "dot-ingress")
    except BaseException:
        cli.atomic(cli.ROOT / ".env", previous)
        raise
    return previous


def install(args):
    if not (cli.ROOT / ".env").exists():
        # Keep image selection architecture-aware; do not copy the amd64 example pin.
        cli.env_update(
            {
                "COMPOSE_PROJECT_NAME": "kakaotalk-bridge",
                "HTTPS_BIND": "127.0.0.1",
                "DOT_PUBLIC_URL": "https://kakao.example.invalid",
                "DOT_APPROVAL_MODE": "passkey",
                "ADMIN_AUTH_MODE": "passkey",
                "HTTPS_PORT": str(args.admin_port or 8443),
                "DOT_HTTP_PORT": str(args.mcp_port or 18787),
            }
        )
    cli.progress("실행 환경 확인 중…")
    host_check()
    existing = cli.compose("ps", "--all", "--services", capture=True).splitlines()
    if existing and not (cli.ROOT / "secrets/ingest_token").exists():
        raise BridgeError("기존 컨테이너에 맞는 인증 키가 이 폴더에 없습니다. 같은 설치의 secrets/ 폴더를 먼저 복구하세요.")
    cli.progress("인증 키 준비 중…")
    init_secrets(args.source)
    if (cli.ROOT / ".bridge/installed").exists() or existing:
        cli.progress("서비스 시작 중…")
        cli.compose("up", "-d", "--no-build", "--no-recreate", *cli.services())
        cli.atomic(cli.ROOT / ".bridge/installed", "1\n")
        print("기존 설치를 유지했습니다. 이미지를 변경하려면 update를 사용하세요.")
        return
    prepare_images(args)
    cli.progress("서비스 시작 중…")
    cli.compose("up", "-d", "--no-build", *cli.services())
    cli.atomic(cli.ROOT / ".bridge/installed", "1\n")
    cli.share_code()
    print(
        "컨테이너를 시작했습니다. ./bridge passkey-login으로 패스키를 등록하세요.\n"
        "AI 연결은 선택 사항입니다. 나중에 ./bridge setup-connection으로 설정할 수 있습니다."
    )


def update(args):
    ensure_passkey_verifier_secret()
    old = prepare_images(args)
    try:
        # The Iris collector replaces the Android-side reader with this image's build when it
        # starts, so new and rolled-back images bring their own matching component.
        # Back up under the old image selection so rollback restores a complete matching stack.
        new = (cli.ROOT / ".env").read_text()
        cli.atomic(cli.ROOT / ".env", old)
        backup.backup(helper_image=image_config(args)["COLLECTOR_IMAGE"])
        cli.atomic(cli.ROOT / ".env", new)
        migrate_auth_modes()
        cli.progress("새 버전으로 서비스 시작 중…")
        cli.compose("up", "-d", "--no-build", *cli.services())
        cli.progress("서비스 응답 확인 중…")
        for _ in range(30):
            time.sleep(2)
            if doctor.doctor(report=False):
                cli.share_code()
                print("업데이트를 완료했습니다. 기존 Android 앱 데이터와 기기 등록은 유지됩니다.")
                return
        raise BridgeError("업데이트 후 서비스가 정상적으로 시작되지 않아 이전 버전으로 되돌렸습니다. ./bridge doctor로 상태를 확인하세요.")
    except BaseException:
        cli.progress("이전 버전으로 되돌리는 중…")
        cli.atomic(cli.ROOT / ".env", old)
        cli.compose("up", "-d", "--no-build", *cli.services())
        raise


def ensure_passkey_verifier_secret():
    path = cli.ROOT / "secrets/mcp_passkey_token"
    if not path.exists():
        cli.atomic(path, secrets.token_urlsafe(32) + "\n")
        path.chmod(0o444)
    if path.stat().st_size < 32:
        raise BridgeError("secrets/mcp_passkey_token이 올바르지 않습니다. 백업에서 복구한 뒤 계속하세요.")


def migrate_auth_modes():
    values = cli.read_env()
    changes = {
        name: "passkey"
        for name in ("ADMIN_AUTH_MODE", "DOT_APPROVAL_MODE")
        if values.get(name) == "kakao"
    }
    if changes:
        cli.env_update(changes)
