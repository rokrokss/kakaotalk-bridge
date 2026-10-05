"""Idempotent single-owner installation and operations; Python standard library only."""

import argparse
import base64
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
SERVICES = ["redroid", "api", "gateway", "device-agent", "iris-collector", "admin"]
VOLUMES = [
    "android-data",
    "collector-data",
    "device-state",
    "iris-state",
    "admin-state",
    "dot-state",
    "passkey-state",
]
REGISTRY = "ghcr.io/rokrokss/kakaotalk-bridge-"


class KoreanArgumentParser(argparse.ArgumentParser):
    """Localize terminal guidance without changing argument names or diagnostics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positionals.title = "명령 및 필수 입력"
        self._optionals.title = "옵션"
        for action in self._actions:
            if isinstance(action, argparse._HelpAction):
                action.help = "사용법을 표시하고 종료"

    def format_usage(self):
        return super().format_usage().replace("usage: ", "사용법: ", 1)

    def format_help(self):
        return super().format_help().replace("usage: ", "사용법: ", 1)

    def error(self, message):
        from ops.setup_output import report_error

        self.print_usage(sys.stderr)
        report_error(ValueError(message))
        self.exit(2, "명령과 옵션은 --help로 확인할 수 있습니다.\n")


def run(args, *, capture=False, **kwargs):
    from ops.setup_output import command_streams, provider_command

    if (
        not capture
        and not kwargs
        and any(Path(str(arg)).name.lower() == "tailscale" for arg in args)
        and ("funnel" in args or "up" in args)
    ):
        return provider_command(args)
    kwargs = command_streams(capture, kwargs)
    result = subprocess.run(
        args, cwd=ROOT, text=True, capture_output=capture, check=False, **kwargs
    )
    if result.returncode:
        # Captured output can contain private paths or device data; do not echo it.
        raise RuntimeError(f"Command failed: {Path(args[0]).name} (exit {result.returncode})")
    return result.stdout.strip() if capture else ""


def read_env():
    data = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, sep, value = line.partition("=")
                if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise RuntimeError("Use KEY=value lines in .env")
                data[key] = value
    return data


def env_update(values):
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not re.fullmatch(
            r"[A-Za-z0-9_:/@.=-]+", value
        ):
            raise ValueError("Invalid configuration value")
    lines = (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []
    lines = [line for line in lines if line.partition("=")[0] not in values]
    atomic(ROOT / ".env", "\n".join([*lines, *(f"{k}={v}" for k, v in values.items())]) + "\n")


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, scratch = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(data)
        os.replace(scratch, path)
    finally:
        Path(scratch).unlink(missing_ok=True)


def compose(*args, capture=False, **kwargs):
    files = ["-f", str(ROOT / "compose.yaml")]
    for file in ("host.yaml", "volumes.yaml"):
        if (ROOT / ".bridge" / file).exists():
            files += ["-f", str(ROOT / ".bridge" / file)]
    return run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            *files,
            "--profile",
            "dot",
            "--profile",
            "tunnel",
            "--profile",
            "local-admin",
            *args,
        ],
        capture=capture,
        env={**os.environ, **read_env()},
        **kwargs,
    )


def services():
    selected = SERVICES + (
        ["dot-plugin", "dot-control", "dot-ingress"]
        if read_env().get("DOT_PUBLIC_URL", "").endswith(".invalid") is False
        and read_env().get("DOT_PUBLIC_URL")
        else (["dot-control"] if read_env().get("ADMIN_AUTH_MODE", "passkey") == "passkey" else [])
    )
    if read_env().get("OPENAI_TUNNEL_ENABLED") == "1":
        selected += ["dot-plugin", "dot-control", "dot-tunnel", "openai-tunnel"]
        saved = ROOT / ".bridge/admin-url"
        if saved.exists() and saved.read_text().strip().startswith("https://"):
            # Older tunnel installs can route private HTTPS admin through this
            # listener without a public MCP URL. Preserve their access.
            selected += ["dot-ingress"]
    if read_env().get("ADMIN_LOCAL_ORIGIN"):
        selected += ["admin-local"]
    return list(dict.fromkeys(selected))


def manifest(path):
    data = json.loads(Path(path).read_text())
    if data.get("schema") != 1 or not re.fullmatch(
        r"v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", data.get("version", "")
    ):
        raise ValueError("Unsupported release manifest")
    refs = {}
    for kind in ("server", "device", "gateway"):
        ref = data.get("images", {}).get(kind, "")
        if not re.fullmatch(re.escape(REGISTRY + kind) + r"@sha256:[a-f0-9]{64}", ref):
            raise ValueError("Use the digest-pinned official release manifest")
        refs[kind] = ref
    return refs


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
    present = [name for name in required if (ROOT / "secrets" / name).exists()]
    if present and any(
        not (ROOT / "secrets" / name).is_file() or not (ROOT / "secrets" / name).stat().st_size
        for name in required
    ):
        raise RuntimeError(
            "Existing installation has missing or empty keys. Restore secrets/; do not generate a new identity."
        )
    # This script creates only missing keys and preserves existing TLS/signing material.
    run(
        ["bash", "scripts/init-secrets.sh"],
        env={**os.environ, "BRIDGE_PREBUILT": "0" if source else "1"},
    )
    root = ROOT / "secrets"
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
            raise RuntimeError(f"Empty credential file: {name}; restore it before continuing")
        path.chmod(0o444)


def host_check():
    if platform.system() != "Linux":
        raise RuntimeError("The runtime requires Linux; use Lima on macOS")
    run(["docker", "info"], capture=True)
    if (
        not Path("/sys/module/binder_linux").exists()
        and not Path("/dev/binderfs/binder-control").exists()
    ):
        raise RuntimeError("Android binder is missing. Follow docs/install.md before installing.")
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
        atomic(ROOT / ".bridge/host.yaml", "\n".join(lines) + "\n")
    if platform.machine() in ("aarch64", "arm64") and not read_env().get("REDROID_IMAGE"):
        env_update(
            {
                "REDROID_IMAGE": "redroid/redroid:14.0.0_64only-latest@sha256:0a611199ba2e0b5d60af39b3327a517f6407231f4352114ed3bd3cbfe2be69aa"
            }
        )


def image_config(args):
    if args.source:
        files = (
            run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                capture=True,
            ).split("\0")
            if (ROOT / ".git").exists()
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
            for folder, directories, names in os.walk(ROOT):
                directories[:] = [name for name in directories if name not in excluded]
                for name in names:
                    if not name.startswith(".env"):
                        files.append(str((Path(folder) / name).relative_to(ROOT)))
        fingerprint = hashlib.sha256()
        for file in sorted(files):
            path = ROOT / file
            if path.is_file() and not path.is_symlink():
                fingerprint.update(
                    file.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest()
                )
        tag = "local-" + fingerprint.hexdigest()[:16]
        refs = {
            kind: f"kakaotalk-collector/{kind}:{tag}" for kind in ("server", "device", "gateway")
        }
    else:
        if not args.manifest:
            raise RuntimeError(
                "Choose --manifest release.json from a GitHub release, or --source to build this checkout."
            )
        refs = manifest(args.manifest)
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
    dockerfile = (ROOT / "docker/device.Dockerfile").read_text()
    image = re.search(
        r"^FROM --platform=linux/amd64 (\S+) AS android-build$", dockerfile, re.MULTILINE
    )
    if not image:
        raise RuntimeError("Cannot identify the Android build image")
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
        run(probe, capture=True, timeout=180)
        return
    except (RuntimeError, subprocess.TimeoutExpired):
        print("Android 빌드 에뮬레이터 준비 중…", flush=True)
    # This changes only the amd64 QEMU handler; other architectures and Rosetta
    # registrations are preserved. Runtime containers stay native.
    run(
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
    run(probe, capture=True, timeout=180)


def prepare_images(args):
    previous = (ROOT / ".env").read_text()
    refs = image_config(args)
    env_update(refs)
    try:
        if args.source:
            prepare_android_builder()
            compose("build", "api", "device-agent", "gateway")
        else:
            compose("pull", *SERVICES, "dot-plugin", "dot-control", "dot-ingress")
    except BaseException:
        atomic(ROOT / ".env", previous)
        raise
    return previous


def install(args):
    if not (ROOT / ".env").exists():
        # Keep image selection architecture-aware; do not copy the amd64 example pin.
        env_update(
            {
                "COMPOSE_PROJECT_NAME": "kakaotalk-collector",
                "HTTPS_BIND": "127.0.0.1",
                "DOT_PUBLIC_URL": "https://kakao.example.invalid",
                "DOT_APPROVAL_MODE": "passkey",
                "ADMIN_AUTH_MODE": "passkey",
                "HTTPS_PORT": str(args.admin_port or 8443),
                "DOT_HTTP_PORT": str(args.mcp_port or 18787),
            }
        )
    host_check()
    existing = compose("ps", "--all", "--services", capture=True).splitlines()
    if existing and not (ROOT / "secrets/ingest_token").exists():
        raise RuntimeError(
            "Existing containers have no local credentials. Restore the matching secrets first."
        )
    init_secrets(args.source)
    if (ROOT / ".bridge/installed").exists() or existing:
        compose("up", "-d", "--no-build", "--no-recreate", *services())
        atomic(ROOT / ".bridge/installed", "1\n")
        print("기존 설치를 유지했습니다. 이미지를 변경하려면 update를 사용하세요.")
        return
    prepare_images(args)
    compose("up", "-d", "--no-build", *services())
    atomic(ROOT / ".bridge/installed", "1\n")
    print(
        "컨테이너를 시작했습니다. ./bridge passkey-login으로 패스키를 등록하세요.\n"
        "AI 연결은 선택 사항입니다. 나중에 ./bridge setup-connection으로 설정할 수 있습니다."
    )


def doctor(report=True):
    reports = {}
    for name, args in (
        ("docker", ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"]),
        ("compose", ["docker", "compose", "version", "--short"]),
    ):
        try:
            reports[name] = {"ok": True, "version": run(args, capture=True)}
        except (RuntimeError, OSError):
            reports[name] = {"ok": False}
    reports["binder"] = {
        "ok": Path("/sys/module/binder_linux").exists()
        or Path("/dev/binderfs/binder-control").exists()
    }
    try:
        raw = compose("ps", "--all", "--format", "json", capture=True)
        rows = (
            json.loads(raw)
            if raw.startswith("[")
            else [json.loads(line) for line in raw.splitlines()]
        )
        reports["services"] = [
            {k: row.get(k, "") for k in ("Service", "State", "Health")} for row in rows
        ]
    except (RuntimeError, ValueError):
        reports["services"] = []
    reports["missing_secrets"] = [
        name
        for name in (
            "admin_token",
            "ingest_token",
            "read_token",
            "device_token",
            "backup_key",
            "mcp_storage_key",
            "mcp_approval_token",
            "tls_cert.pem",
            "tls_key.pem",
        )
        if not (ROOT / "secrets" / name).is_file()
    ]
    if read_env().get("OPENAI_TUNNEL_ENABLED") == "1":
        from ops.tunnel import status

        reports["tunnel"] = status()
        reports["missing_secrets"] += [
            name
            for name in ("openai_tunnel_api_key", "mcp_tunnel_authorization")
            if not (ROOT / "secrets" / name).is_file()
        ]
    if report:
        print(json.dumps(reports, indent=2))
    expected = set(services())
    healthy = {
        row["Service"]
        for row in reports["services"]
        if row["State"] == "running" and row["Health"] in ("", "healthy")
    }
    return (
        all(reports[name]["ok"] for name in ("docker", "compose", "binder"))
        and not reports["missing_secrets"]
        and expected <= healthy
    )


def admin_code():
    return compose("exec", "-T", "admin", "python", "-m", "webui.auth", "pair", capture=True)


def admin_info():
    return json.loads(
        compose("exec", "-T", "admin", "python", "-m", "webui.auth", "info", capture=True)
    )


def admin_url(override=None):
    if override:
        return private_url(override)
    path = ROOT / ".bridge/admin-url"
    if path.exists():
        return private_url(path.read_text().strip())
    if platform.system() == "Darwin":
        path = ROOT / ".bridge/mac.json"
        port = (
            str(json.loads(path.read_text()).get("local_admin_port", 18789))
            if path.exists()
            else "18789"
        )
    else:
        port = read_env().get("ADMIN_LOCAL_PORT", "18789")
    return private_url("http://localhost:" + port)


def open_admin_page(url):
    url = private_url(url)
    print("관리 화면: " + url + "\n설정한 방식으로 로그인하세요.")
    webbrowser.open(url)


def ensure_passkey_verifier_secret():
    path = ROOT / "secrets/mcp_passkey_token"
    if not path.exists():
        atomic(path, secrets.token_urlsafe(32) + "\n")
        path.chmod(0o444)
    if path.stat().st_size < 32:
        raise RuntimeError("Invalid mcp_passkey_token; restore it before continuing")


def migrate_auth_modes():
    values = read_env()
    changes = {
        name: "passkey"
        for name in ("ADMIN_AUTH_MODE", "DOT_APPROVAL_MODE")
        if values.get(name) == "kakao"
    }
    if changes:
        env_update(changes)


def passkey_setup(args):
    if platform.system() == "Darwin" and not args.local:
        config = json.loads((ROOT / ".bridge/mac.json").read_text())
        command = [
            "limactl",
            "shell",
            "--workdir=/",
            config["vm"],
            "sudo",
            config["directory"] + "/bridge",
            "--local",
            "passkey-login",
            "--link-only",
        ]
        saved_origin = ROOT / ".bridge/admin-url"
        if args.url or saved_origin.exists():
            command += ["--url", args.url or saved_origin.read_text().strip()]
        elif config.get("local_admin_port"):
            command += ["--url", "http://localhost:" + str(config["local_admin_port"])]
        if args.public_url:
            command += ["--public-url", args.public_url]
        if args.enroll:
            command += ["--enroll"]
        link = run(command, capture=True)
        atomic(saved_origin, private_url(link.partition("#")[0]))
    else:
        # A new limited verifier credential can be added without rotating existing identities.
        ensure_passkey_verifier_secret()
        migrate_auth_modes()
        compose("up", "-d", "--no-build", "--no-deps", "dot-control", capture=True)

        def helper(operation, payload=None):
            return compose(
                "exec",
                "-T",
                "dot-control",
                "python",
                "-m",
                "server.passkeys",
                operation,
                input=payload,
                capture=True,
            )

        info = json.loads(helper("info"))
        saved_origin = ROOT / ".bridge/admin-url"
        origin = private_url(
            args.url
            or (saved_origin.read_text().strip() if saved_origin.exists() else None)
            or info.get("admin_origin")
            or admin_url()
        ).removesuffix("/admin/")
        public = args.public_url or read_env().get("DOT_PUBLIC_URL", "")
        if public.endswith(".invalid"):
            public = ""
        if public:
            validate_public_url(public)
            if public != read_env().get("DOT_PUBLIC_URL"):
                raise ValueError("Run ./bridge connect --url with the public origin first")
        # A localhost passkey cannot authenticate a different public RP. Keep
        # the admin identity and use the existing code-confirmation consent flow.
        passkey_public = (
            public
            if (
                origin.startswith("https://")
                and urlsplit(origin).hostname == urlsplit(public).hostname
            )
            else ""
        )
        if (
            not info["configured"]
            or info["admin_origin"] != origin
            or info["public_origin"] != passkey_public
        ):
            helper(
                "configure", json.dumps({"admin_origin": origin, "public_origin": passkey_public})
            )
        updates = {"ADMIN_AUTH_MODE": "passkey"}
        if public:
            updates["DOT_APPROVAL_MODE"] = "passkey" if passkey_public else "admin"
        if origin.startswith("http://localhost:"):
            updates.update(
                {"ADMIN_LOCAL_ORIGIN": origin, "ADMIN_LOCAL_HOST": urlsplit(origin).netloc}
            )
        env_update(updates)
        atomic(ROOT / ".bridge/admin-url", private_url(origin))
        compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "60",
            "admin",
            *(["admin-local"] if origin.startswith("http://localhost:") else []),
            *(["dot-plugin", "dot-control", "dot-ingress"] if public else []),
            capture=True,
        )
        link = private_url(origin)
        if args.enroll or not info["registered"]:
            token = helper("enroll")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
                raise RuntimeError("Invalid enrollment response")
            link += "#passkey-setup=" + token
    if args.link_only:
        print(link)
    else:
        print("아래 설정 링크를 여세요 (등록 링크는 10분 후 만료):\n" + link)
        webbrowser.open(link)


def private_url(value):
    parsed = urlsplit(value)
    if (
        not (
            parsed.scheme == "https"
            or (
                parsed.scheme == "http"
                and parsed.netloc == f"localhost:{parsed.port}"
                and parsed.port is not None
                and 1024 <= parsed.port <= 65535
            )
        )
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/admin/")
    ):
        raise ValueError(
            "Use an HTTPS admin address or http://localhost:<port>, without query parameters"
        )
    return value.rstrip("/").removesuffix("/admin") + "/admin/"


def open_admin(code, url):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise RuntimeError("Invalid pairing response")
    link = private_url(url) + "#pair=" + code
    print("일회용 관리 화면 링크 (10분 후 만료):\n" + link)
    webbrowser.open(link)


def validate_public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname.endswith(".invalid")
    ):
        raise ValueError("Use your public HTTPS origin, with no trailing slash")


def connect(url):
    validate_public_url(url)
    mode = read_env().get("DOT_APPROVAL_MODE", "passkey")
    env_update({"DOT_PUBLIC_URL": url, "DOT_APPROVAL_MODE": mode})
    atomic(ROOT / ".bridge/public-url", url)
    compose("up", "-d", "--no-build", "dot-plugin", "dot-control", "dot-ingress")
    print(url + "/mcp\n./bridge passkey-login으로 이 주소의 로그인을 설정하세요.")


def tailscale_binary():
    installed = shutil.which("tailscale")
    app = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    return installed or (str(app) if platform.system() == "Darwin" and app.is_file() else None)


def expose(args):
    tailscale = tailscale_binary()
    if not tailscale:
        raise RuntimeError("Install Tailscale and sign in first, then rerun ./bridge expose.")
    tailscale = (["sudo"] if platform.system() == "Linux" and os.geteuid() != 0 else []) + [
        tailscale
    ]
    status = json.loads(run([*tailscale, "status", "--json"], capture=True))
    hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if status.get("BackendState") != "Running" or not re.fullmatch(
        r"[a-z0-9.-]+\.ts\.net", hostname
    ):
        raise RuntimeError("Sign in to Tailscale and enable MagicDNS first.")
    existing = json.loads(run([*tailscale, "serve", "status", "--json"], capture=True))
    record_path = ROOT / ".bridge/expose.json"
    owned = json.loads(record_path.read_text()) if record_path.exists() else None
    if existing and (
        not owned or owned.get("hostname") != hostname or owned.get("config") != existing
    ):
        raise RuntimeError(
            "Tailscale already serves another app. Its routes were preserved; follow the manual ports in docs/onboarding.md."
        )
    if platform.system() == "Darwin" and not args.local:
        config = json.loads((ROOT / ".bridge/mac.json").read_text())
        local = argparse.Namespace(command="connect", url="https://" + hostname)
        mac(local)
    else:
        connect("https://" + hostname)

    def record_routes():
        current = json.loads(run([*tailscale, "serve", "status", "--json"], capture=True))
        atomic(record_path, json.dumps({"hostname": hostname, "config": current}))

    mcp_port = (
        config.get("mcp_port", 18787)
        if platform.system() == "Darwin" and not args.local
        else int(read_env().get("DOT_HTTP_PORT", "18787"))
    )
    run([*tailscale, "funnel", "--bg", "--https=443", f"http://127.0.0.1:{mcp_port}"])
    record_routes()
    # Migrate only the old route whose complete configuration we verified above.
    # Record each successful step so a failed migration can be retried safely.
    if existing.get("Web", {}).get(hostname + ":8443"):
        run([*tailscale, "serve", "--https=8443", "off"])
        record_routes()
    saved_admin = ROOT / ".bridge/admin-url"
    admin_url = (
        saved_admin.read_text().strip().removesuffix("/admin/")
        if saved_admin.exists()
        else "https://" + hostname
    )
    atomic(saved_admin, admin_url)
    atomic(ROOT / ".bridge/public-url", "https://" + hostname)
    print(
        f"관리 화면: {admin_url}/admin/\nMCP: https://{hostname}/mcp\n./bridge passkey-login으로 OAuth 승인을 설정하세요."
    )


def volume_names():
    config = json.loads(compose("config", "--format", "json", capture=True))
    return {name: config["volumes"][name]["name"] for name in VOLUMES}


def snapshot_command(mode, names, *, key=None, stage=None, work=None, image=None):
    env = read_env()
    image = (
        image
        or env.get("DOT_IMAGE")
        or env.get("COLLECTOR_IMAGE", "kakaotalk-collector/server:0.1.0")
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--user",
        "0",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "FOWNER",
        "--cap-add",
        "SETFCAP",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "python",
    ]
    for name, volume in names.items():
        cmd += ["-v", f"{volume}:/snapshot/{name}" + (":ro" if mode == "create" else "")]
    key_path = str(key or ROOT / "secrets/backup_key")
    project_path = str(stage or ROOT)
    if any(c in key_path + project_path for c in ",:\r\n"):
        raise ValueError("Mount paths may not contain commas, colons or newlines")
    cmd += ["--mount", f"type=bind,src={key_path},dst=/key,readonly"]
    cmd += ["-v", f"{stage or ROOT}:/project" + (":ro" if mode == "create" else "")]
    if work:
        cmd += [
            "-v",
            f"{work}:/work",
            "-e",
            f"RESTORE_UID={os.getuid()}",
            "-e",
            f"RESTORE_GID={os.getgid()}",
        ]
    cmd += [image, "-m", "ops.snapshot", mode]
    return cmd


def backup(helper_image=None, name=None):
    root = ROOT / "backups"
    root.mkdir(mode=0o700, exist_ok=True)
    destination = root / (
        name or (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".kcs")
    )
    names = volume_names()
    existing = set(
        run(["docker", "volume", "ls", "--format", "{{.Name}}"], capture=True).splitlines()
    )
    names = {name: value for name, value in names.items() if value in existing}
    running = compose("ps", "--status", "running", "--services", capture=True).splitlines()
    compose("stop")
    try:
        with destination.open("xb") as output:
            destination.chmod(0o600)
            result = subprocess.run(
                snapshot_command("create", names, image=helper_image),
                cwd=ROOT,
                stdout=output,
                check=False,
            )
        if result.returncode:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Backup failed; partial archive removed")
    finally:
        if running:
            compose("start", *running)
    print(f"암호화된 백업: {destination}\n복구에 필요한 secrets/backup_key는 별도로 보관하세요.")
    return destination


def recover_activation():
    journal = ROOT / ".bridge/restore-activation.json"
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    stage = Path(record["stage"])
    for item in (".env", "secrets"):
        previous = stage / (item.replace(".", "") + "-previous")
        if previous.exists():
            if (ROOT / item).exists():
                (ROOT / item).rename(stage / item)
            previous.rename(ROOT / item)
    override = ROOT / ".bridge/volumes.yaml"
    if record["volumes"] is None:
        override.unlink(missing_ok=True)
    else:
        atomic(override, record["volumes"])
    journal.unlink()


def activate_restore(stage, names):
    for item in ("secrets", ".env"):
        if not (stage / item).exists() or not (ROOT / item).exists():
            raise RuntimeError(
                "Incomplete snapshot or installation; original configuration retained"
            )
    override = ROOT / ".bridge/volumes.yaml"
    journal = ROOT / ".bridge/restore-activation.json"
    atomic(
        journal,
        json.dumps(
            {"stage": str(stage), "volumes": override.read_text() if override.exists() else None}
        ),
    )
    try:
        for item in ("secrets", ".env"):
            (ROOT / item).rename(stage / (item.replace(".", "") + "-previous"))
            (stage / item).rename(ROOT / item)
        content = "volumes:\n" + "".join(
            f"  {name}:\n    name: {value}\n    external: true\n" for name, value in names.items()
        )
        atomic(override, content)
        atomic(ROOT / ".bridge/restored-pending", "1\n")
        journal.unlink()
    except BaseException:
        recover_activation()
        raise


def restore(path, key):
    archive, key = Path(path).resolve(), Path(key).resolve()
    if not archive.is_file() or not key.is_file():
        raise ValueError("Archive and recovery key must exist")
    if compose("ps", "--status", "running", "--services", capture=True):
        raise RuntimeError(
            "Stop the stack with ./bridge stop before restoring. Old volumes will be retained."
        )
    suffix = "restore-" + secrets.token_hex(6)
    names = {
        name: read_env().get("COMPOSE_PROJECT_NAME", "kakaotalk-collector")
        + "_"
        + suffix
        + "_"
        + name
        for name in VOLUMES
    }
    stage = ROOT / ".bridge" / suffix
    stage.mkdir(mode=0o700, parents=True)
    work = suffix + "-scratch"
    for name in [*names.values(), work]:
        run(["docker", "volume", "create", name], capture=True)
    try:
        with archive.open("rb") as source:
            result = subprocess.run(
                snapshot_command("restore", names, key=key, stage=stage, work=work),
                cwd=ROOT,
                stdin=source,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(
                "Restore verification failed. Existing volumes and keys were not changed."
            )
        activate_restore(stage, names)
        restored = read_env()
        if restored.get("OPENAI_TUNNEL_ENABLED") == "1":
            atomic(
                ROOT / ".bridge/tunnel.json",
                json.dumps({"tunnel_id": restored["OPENAI_TUNNEL_ID"]}),
            )
        else:
            (ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
        print(
            "새 볼륨으로 복구했습니다. 이전 볼륨과 설정은 유지됩니다. ./bridge start를 실행하고 두 기기의 로그인을 확인하세요. 외부 이벤트 구독은 다시 만들어야 합니다."
        )
    finally:
        with contextlib.suppress(RuntimeError, OSError):
            run(["docker", "volume", "rm", work], capture=True)


def update(args):
    ensure_passkey_verifier_secret()
    old = prepare_images(args)
    try:
        old_env = dict(
            line.split("=", 1)
            for line in old.splitlines()
            if "=" in line and not line.startswith("#")
        )
        old_device = old_env.get("DEVICE_IMAGE", "kakaotalk-collector/device:0.1.0")
        new_device = read_env()["DEVICE_IMAGE"]

        def iris_hash(image):
            return run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "sha256sum",
                    image,
                    "/opt/iris.apk",
                ],
                capture=True,
            ).split()[0]

        if iris_hash(old_device) != iris_hash(new_device):
            raise RuntimeError(
                "This update changes the installed Iris binary. A separate component migration is required; images were not deployed."
            )
        # Back up under the old image selection so rollback restores a complete matching stack.
        new = (ROOT / ".env").read_text()
        atomic(ROOT / ".env", old)
        backup(helper_image=image_config(args)["COLLECTOR_IMAGE"])
        atomic(ROOT / ".env", new)
        migrate_auth_modes()
        compose("up", "-d", "--no-build", *services())
        for _ in range(30):
            time.sleep(2)
            if doctor(report=False):
                print("업데이트를 완료했습니다. 기존 Android 앱 데이터와 기기 등록은 유지됩니다.")
                return
        raise RuntimeError("Health check failed after update")
    except BaseException:
        atomic(ROOT / ".env", old)
        compose("up", "-d", "--no-build", *services())
        raise


def package_source(destination):
    # Release/source archives have no .git directory. Explicitly enumerate source
    # roots so local credentials, volumes and virtualenvs cannot enter the guest.
    from ops.source import CODE_DIRS

    files = []
    if (ROOT / ".git").exists() and shutil.which("git"):
        files = run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture=True
        ).split("\0")
    for entry in [] if files else sorted(ROOT.iterdir()):
        if entry.is_symlink():
            continue
        if entry.is_dir() and entry.name in CODE_DIRS:
            for folder, directories, names in os.walk(entry, followlinks=False):
                directories[:] = [
                    name
                    for name in directories
                    if name not in {"build", ".git", ".gradle", "__pycache__", "node_modules"}
                    and not (Path(folder) / name).is_symlink()
                ]
                files.extend(str((Path(folder) / name).relative_to(ROOT)) for name in names)
        elif entry.is_file() and entry.name in {
            "bridge",
            "compose.yaml",
            "pyproject.toml",
            "uv.lock",
            "requirements.lock",
            ".dockerignore",
            ".gitignore",
            "README.md",
            "CONTRIBUTING.md",
            "release.json",
        }:
            files.append(entry.name)
    with tarfile.open(destination, "w:gz") as archive:
        for file in sorted(set(files)):
            path = ROOT / file
            if (
                path.is_file()
                and not path.is_symlink()
                and not any(
                    p in {"secrets", "inputs", "artifacts", "backups", ".bridge", ".git"}
                    for p in path.relative_to(ROOT).parts
                )
                and not file.startswith(".env")
                and not path.name.startswith(".env")
                and not file.endswith((".local.plist", ".pyc", ".log", ".pem", ".key"))
            ):
                archive.add(path, arcname=file, recursive=False)


def available_port(preferred, requested=None, exclude=()):
    port = requested if requested is not None else preferred
    if not 1024 <= port <= 65535:
        raise ValueError("Choose a port between 1024 and 65535")
    with socket.socket() as probe:
        try:
            if port in exclude:
                raise OSError("Port selected twice")
            probe.bind(("127.0.0.1", port))
        except OSError:
            if requested is not None:
                raise RuntimeError(f"Port {port} is already in use. Choose another port.") from None
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def mac(args):
    if not shutil.which("limactl"):
        raise RuntimeError("Install Lima first: brew install lima. Docker Desktop is not required.")
    config_path = ROOT / ".bridge/mac.json"
    if not config_path.exists() and args.command != "install":
        raise RuntimeError("Run ./bridge install first; this checkout has no managed Lima runtime.")
    existing_config = config_path.exists()
    if existing_config:
        config = json.loads(config_path.read_text())
    else:
        admin_port = available_port(18443, args.admin_port)
        mcp_port = available_port(18787, args.mcp_port, (admin_port,))
        config = {
            "vm": args.vm,
            "directory": "/srv/kakaotalk-bridge",
            "admin_port": admin_port,
            "mcp_port": mcp_port,
            "local_admin_port": available_port(18789, None, (admin_port, mcp_port)),
        }
    vm, directory = config["vm"], config["directory"]

    def guest(*command, capture=False):
        return run(["limactl", "shell", "--workdir=/", vm, "sudo", *command], capture=capture)

    def invoke(*command, capture=False):
        return guest("python3", directory + "/ops/cli.py", "--local", *command, capture=capture)

    if args.command in ("install", "update"):
        instances = run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines()
        if vm in instances and not existing_config:
            raise RuntimeError(
                "A VM with this name already exists outside this installation. Choose another --vm name."
            )
        if vm not in instances:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,48}", vm)
                or not 1024 <= config["admin_port"] <= 65535
            ):
                raise ValueError("Invalid VM name or admin port")
            for port in (config["admin_port"], config.get("mcp_port", 18787)):
                with socket.socket() as probe:
                    probe.settimeout(0.2)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        raise RuntimeError(
                            f"Local port {port} is already in use; preserve the existing service and choose a free admin port or follow manual setup."
                        )
            if args.command != "install":
                raise RuntimeError("Install first")
            template = (
                (ROOT / "deploy/lima.yaml")
                .read_text()
                .replace("hostPort: 18443", f"hostPort: {config['admin_port']}")
            )
            template = template.replace(
                "  - guestPortRange:",
                f"  - guestPort: 18787\n    hostPort: {config.get('mcp_port', 18787)}\n    hostIP: 127.0.0.1\n  - guestPortRange:",
            )
            if config.get("local_admin_port"):
                template = template.replace(
                    "  - guestPortRange:",
                    f"  - guestPort: 18789\n    hostPort: {config['local_admin_port']}\n    hostIP: 127.0.0.1\n  - guestPortRange:",
                )
            if platform.machine() == "x86_64":
                template = template.replace("arch: aarch64", "arch: x86_64").replace(
                    "vmType: vz", "vmType: qemu"
                )
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "lima.yaml"
                path.write_text(template)
                # Persist port choices before provisioning so a failed first boot
                # resumes the same VM and forwarding configuration.
                atomic(config_path, json.dumps(config))
                run(["limactl", "start", "--tty=false", "--name", vm, str(path)])
        else:
            run(["limactl", "start", "--tty=false", vm])
        atomic(config_path, json.dumps(config))
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "source.tar.gz"
            package_source(archive)
            guest("mkdir", "-p", directory)
            remote = "/tmp/kakao-source-" + secrets.token_hex(8) + ".tar.gz"
            run(["limactl", "copy", str(archive), vm + ":" + remote])
            try:
                # Execute from /tmp so moving ops/ cannot replace the running refresh code.
                helper = remote + ".py"
                run(["limactl", "copy", str(ROOT / "ops/source.py"), vm + ":" + helper])
                guest("python3", helper, "apply", directory, remote)
            finally:
                guest("rm", "-f", remote)
        options = [args.command]
        if args.source:
            options += ["--source"]
        elif args.manifest:
            manifest(args.manifest)
            run(
                [
                    "limactl",
                    "copy",
                    str(Path(args.manifest).resolve()),
                    vm + ":/tmp/kakao-release.json",
                ]
            )
            guest("mv", "/tmp/kakao-release.json", directory + "/release.json")
            options += ["--manifest", directory + "/release.json"]
        try:
            invoke(*options)
        except BaseException:
            guest("python3", helper, "rollback", directory)
            raise
        else:
            guest("python3", helper, "commit", directory)
        finally:
            guest("rm", "-f", helper)
    elif args.command == "setup-agent":
        # The web service runs inside Linux; desktop clients use the host adapter.
        if args.agent_command == "install":
            run(
                [
                    "limactl",
                    "shell",
                    "--workdir=/",
                    vm,
                    "sudo",
                    "python3",
                    "-c",
                    (
                        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); "
                        "p.write_text(sys.stdin.read()); p.chmod(0o600)"
                    ),
                    directory + "/.bridge/stdio-client.json",
                ],
                input=json.dumps(
                    {"command": sys.executable, "args": [str(ROOT / "bridge"), "mcp"]}
                ),
            )
        invoke("setup-agent", args.agent_command)
    elif args.command == "admin":
        if args.recovery:
            code = invoke("admin", "--recovery", "--code-only", capture=True)
            open_admin(code, admin_url(args.url))
        else:
            info = json.loads(invoke("admin", "--info", capture=True))
            open_admin_page(args.url or info.get("origin") or admin_url())
    elif args.command == "tunnel":
        if args.tunnel_command == "configure":
            from ops.tunnel import credentials

            credentials(args.tunnel_id, args.api_key_file)
            target = "/tmp/kakao-tunnel-" + secrets.token_hex(8)
            run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", target])
            try:
                run(
                    [
                        "limactl",
                        "copy",
                        str(Path(args.api_key_file).resolve()),
                        vm + ":" + target + "/key",
                    ]
                )
                invoke(
                    "tunnel",
                    "configure",
                    "--tunnel-id",
                    args.tunnel_id,
                    "--api-key-file",
                    target + "/key",
                )
                atomic(ROOT / ".bridge/tunnel.json", json.dumps({"tunnel_id": args.tunnel_id}))
                from ops.tunnel import show_configured

                show_configured(args.tunnel_id)
            finally:
                guest("rm", "-rf", target)
        else:
            invoke("tunnel", args.tunnel_command)
            if args.tunnel_command == "disable":
                (ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
                print("개인 터널을 비활성화했습니다. 공개 OAuth 연결은 유지됩니다.")
    elif args.command == "import-apks":
        target = "/tmp/kakao-import-" + secrets.token_hex(8)
        files = list(Path(args.folder).glob("*.apk"))
        if not files:
            raise ValueError("No APK files in this folder")
        # Use a private staging directory, not a shared mount of the host home.
        run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", target])
        try:
            run(["limactl", "copy", *[str(p.resolve()) for p in files], vm + ":" + target + "/"])
            invoke("import-apks", target)
        finally:
            guest("rm", "-rf", target)
    elif args.command == "backup":
        name = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".kcs"
        invoke("backup", "--name", name)
        destination = ROOT / "backups" / name
        destination.parent.mkdir(mode=0o700, exist_ok=True)
        with destination.open("xb") as output:
            result = subprocess.run(
                [
                    "limactl",
                    "shell",
                    "--workdir=/",
                    vm,
                    "sudo",
                    "cat",
                    directory + "/backups/" + name,
                ],
                stdout=output,
                check=False,
            )
        if result.returncode:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Backup remains in the VM; copying to the Mac failed")
        print("암호화된 백업을 복사했습니다: " + str(destination))
        print(
            "백업과 복구 키는 VM 안에 있습니다. backups/와 secrets/backup_key를 각각 별도의 안전한 저장소에 복사하세요. docs/onboarding.md를 참고하세요."
        )
    elif args.command == "restore":
        remote = "/tmp/kakao-restore-" + secrets.token_hex(8)
        run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", remote])
        try:
            for source, name in ((args.file, "backup.kcs"), (args.key, "key")):
                run(
                    ["limactl", "copy", str(Path(source).resolve()), vm + ":" + remote + "/" + name]
                )
            invoke("restore", remote + "/backup.kcs", "--key", remote + "/key")
            # Runtime .env is restored, but the Mac-only launch hint is not in snapshots.
            restored_tunnel = json.loads(invoke("tunnel", "status", capture=True))
            if restored_tunnel["configured"]:
                atomic(
                    ROOT / ".bridge/tunnel.json",
                    json.dumps({"tunnel_id": restored_tunnel["tunnel_id"]}),
                )
            else:
                (ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
        finally:
            guest("rm", "-rf", remote)

    else:
        if args.command == "start":
            run(["limactl", "start", "--tty=false", vm])
        options = [args.command]
        if args.command == "connect":
            options += ["--url", args.url]
        invoke(*options)
        if args.command == "connect":
            print(args.url + "/mcp\n./bridge passkey-login으로 이 주소의 로그인을 설정하세요.")


def main():
    os.umask(0o077)
    parser = KoreanArgumentParser(description="KakaoTalk Bridge 설치 및 관리")
    parser.add_argument("--local", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    from ops.onboarding import add_arguments

    add_arguments(sub.add_parser("up", help="실행 환경을 준비하고 카카오톡 설정 화면 열기"))
    from ops.tunnel import add_arguments as tunnel_arguments

    tunnel_arguments(sub.add_parser("tunnel", help="개인 OpenAI MCP 터널 관리"))
    from ops.connections import add_arguments as connection_arguments

    connection_arguments(sub.add_parser("setup-connection", help="AI 연결 방식 선택 및 설정"))
    sub.add_parser("mcp", help="로컬 MCP stdio 어댑터 실행")
    agent = sub.add_parser("setup-agent", help="관리 화면의 연결 설정 서비스 관리")
    agent.add_argument("agent_command", choices=("install", "serve", "job"))
    for name in ("install", "update"):
        cmd = sub.add_parser(name)
        mode = cmd.add_mutually_exclusive_group()
        mode.add_argument("--source", action="store_true")
        mode.add_argument("--manifest")
        cmd.add_argument("--vm", default="kakaotalk-bridge")
        cmd.add_argument("--admin-port", type=int)
        cmd.add_argument("--mcp-port", type=int)
    cmd = sub.add_parser("admin")
    cmd.add_argument("--url")
    cmd.add_argument("--recovery", action="store_true", help="일회용 긴급 복구 링크 발급")
    cmd.add_argument("--code-only", action="store_true", help=argparse.SUPPRESS)
    cmd.add_argument("--info", action="store_true", help=argparse.SUPPRESS)
    cmd = sub.add_parser(
        "passkey-login",
        help="관리 화면과 MCP의 패스키 설정",
    )
    cmd.add_argument("--url", help="관리 화면 HTTPS 주소 또는 http://localhost:<port>")
    cmd.add_argument("--public-url", help="공개 HTTPS MCP 주소")
    cmd.add_argument("--enroll", action="store_true", help="일회용 등록·복구 링크 발급")
    cmd.add_argument("--link-only", action="store_true", help=argparse.SUPPRESS)
    cmd = sub.add_parser("connect")
    cmd.add_argument("--url", required=True)
    cmd = sub.add_parser("import-apks")
    cmd.add_argument("folder")
    cmd = sub.add_parser("restore")
    cmd.add_argument("file")
    cmd.add_argument("--key", required=True)
    cmd = sub.add_parser("backup")
    cmd.add_argument("--name", help=argparse.SUPPRESS)
    for name in ("doctor", "start", "stop", "reset-password", "expose"):
        sub.add_parser(name)
    args = parser.parse_args()
    from ops.setup_output import operation, report_error

    try:
        with operation(args):
            execute(args)
    except KeyboardInterrupt:
        print("중단되었습니다. 같은 명령을 실행해 이어서 진행하세요.", file=sys.stderr)
        raise SystemExit(130) from None
    except subprocess.TimeoutExpired:
        print("설정 명령의 제한 시간이 지났습니다. 같은 명령으로 다시 시도하세요.", file=sys.stderr)
        raise SystemExit(1) from None
    except (RuntimeError, ValueError, OSError) as exc:
        report_error(exc)
        raise SystemExit(1) from None


def execute(args):
    from ops.onboarding import up

    if args.command == "up":
        up(args)
        return
    if args.command == "setup-connection":
        from ops.connections import setup

        setup(args)
        return
    if args.command == "setup-agent":
        if platform.system() == "Darwin" and not args.local:
            mac(args)
        else:
            from ops import setup_agent

            {
                "install": setup_agent.install,
                "serve": setup_agent.serve,
                "job": setup_agent.job_main,
            }[args.agent_command]()
        return
    if (
        args.command == "backup"
        and args.name
        and not re.fullmatch(r"[a-zA-Z0-9_-]+\.kcs", args.name)
    ):
        raise ValueError("Invalid snapshot filename")
    if args.local or platform.system() == "Linux":
        recover_activation()
    if args.command == "passkey-login":
        passkey_setup(args)
    elif args.command == "expose":
        expose(args)
    elif platform.system() == "Darwin" and not args.local:
        mac(args)
    elif args.command == "install":
        install(args)
    elif args.command == "update":
        update(args)
    elif args.command == "admin":
        if args.info:
            print(json.dumps(admin_info()))
        elif args.recovery:
            code = admin_code()
            if args.code_only:
                print(code)
            else:
                open_admin(code, admin_url(args.url))
        else:
            info = admin_info()
            open_admin_page(args.url or info.get("origin") or admin_url())
    elif args.command == "doctor":
        if not doctor():
            raise SystemExit(1)
    elif args.command == "mcp":
        compose("run", "--rm", "--no-deps", "-T", "mcp")
    elif args.command == "connect":
        connect(args.url)
    elif args.command == "tunnel":
        from ops.tunnel import run as run_tunnel

        run_tunnel(args)
    elif args.command == "backup":
        backup(name=args.name)
    elif args.command == "restore":
        restore(args.file, args.key)
    elif args.command == "import-apks":
        files = sorted(Path(args.folder).glob("*.apk"))
        if not files:
            raise ValueError("No APK files in this folder")
        destination = ROOT / "inputs/kakao"
        destination.mkdir(parents=True, exist_ok=True)
        existing = sorted(destination.glob("*.apk"))
        if existing:

            def hashes(paths):
                result = []
                for path in paths:
                    with path.open("rb") as stream:
                        result.append(hashlib.file_digest(stream, "sha256").hexdigest())
                return sorted(result)

            if hashes(existing) == hashes(files):
                print("이미 가져온 APK 세트입니다. 기존 파일을 유지합니다.")
                return
            raise RuntimeError(
                "inputs/kakao already contains APKs. Move the old set aside first; do not mix versions."
            )
        for index, file in enumerate(files):
            shutil.copyfile(file, destination / f"{index}.apk")
        print("APK 세트를 복사했습니다. 관리 화면의 ‘수집 구성 요소 설치’에서 검증하고 설치하세요.")
    elif args.command == "reset-password":
        compose("exec", "-T", "admin", "python", "-m", "webui.auth", "reset-password")
    elif args.command == "stop":
        compose("stop")
    elif args.command == "start":
        # Older encrypted snapshots predate this verifier-only service credential.
        ensure_passkey_verifier_secret()
        migrate_auth_modes()
        pending = ROOT / ".bridge/restored-pending"
        compose(
            "up",
            "-d",
            "--no-build",
            *(["--force-recreate"] if pending.exists() else []),
            *services(),
        )
        pending.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
