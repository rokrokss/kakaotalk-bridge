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
SERVICES = ["redroid", "api", "gateway", "device-agent", "iris-collector", "admin"]
VOLUMES = [
    "android-data",
    "collector-data",
    "device-state",
    "iris-state",
    "admin-state",
    "dot-state",
]
REGISTRY = "ghcr.io/rokrokss/kakaotalk-bridge-"


def run(args, *, capture=False, **kwargs):
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
        ["docker", "compose", "--project-directory", str(ROOT), *files, "--profile", "dot", *args],
        capture=capture,
        env={**os.environ, **read_env()},
        **kwargs,
    )


def services():
    return SERVICES + (
        ["dot-plugin", "dot-control"]
        if read_env().get("DOT_PUBLIC_URL", "").endswith(".invalid") is False
        and read_env().get("DOT_PUBLIC_URL")
        else []
    )


def manifest(path):
    data = json.loads(Path(path).read_text())
    if data.get("schema") != 1 or not re.fullmatch(
        r"v\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", data.get("version", "")
    ):
        raise ValueError("Unsupported release manifest")
    refs = {}
    for kind in ("server", "device"):
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
        refs = {kind: f"kakaotalk-collector/{kind}:{tag}" for kind in ("server", "device")}
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
    }


def prepare_images(args):
    previous = (ROOT / ".env").read_text()
    refs = image_config(args)
    env_update(refs)
    try:
        if args.source:
            compose("build", "api", "device-agent")
        else:
            compose("pull", *SERVICES, "dot-plugin", "dot-control")
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
                "DOT_APPROVAL_MODE": "admin",
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
        print("Existing installation preserved. Use update to change its images.")
        return
    prepare_images(args)
    compose("up", "-d", "--no-build", *services())
    atomic(ROOT / ".bridge/installed", "1\n")
    print(
        "Containers started. Run ./bridge admin to set up the tablet; no KakaoTalk login was performed."
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


def private_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/admin/")
    ):
        raise ValueError("Use the private admin HTTPS address without query parameters")
    return value.rstrip("/").removesuffix("/admin") + "/admin/"


def open_admin(code, url):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise RuntimeError("Invalid pairing response")
    link = private_url(url) + "#pair=" + code
    print("One-time admin link (expires in 10 minutes):\n" + link)
    webbrowser.open(link)


def connect(url):
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
    env_update({"DOT_PUBLIC_URL": url, "DOT_APPROVAL_MODE": "admin"})
    compose("up", "-d", "--no-build", "dot-plugin", "dot-control")
    print(
        url + "/mcp\nChoose OAuth in ChatGPT, then approve the matching code in admin Connections."
    )


def expose(args):
    if not shutil.which("tailscale"):
        raise RuntimeError("Install Tailscale and sign in first, then rerun ./bridge expose.")
    status = json.loads(run(["tailscale", "status", "--json"], capture=True))
    hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if status.get("BackendState") != "Running" or not re.fullmatch(
        r"[a-z0-9.-]+\.ts\.net", hostname
    ):
        raise RuntimeError("Sign in to Tailscale and enable MagicDNS first.")
    existing = json.loads(run(["tailscale", "serve", "status", "--json"], capture=True))
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
        admin_port = config["admin_port"]
        local = argparse.Namespace(command="connect", url="https://" + hostname)
        mac(local)
    else:
        admin_port = int(read_env().get("HTTPS_PORT", "8443"))
        connect("https://" + hostname)
    # Separate HTTPS ports: admin is tailnet-only; only OAuth/MCP is public.
    run(["tailscale", "serve", "--bg", "--https=8443", f"https+insecure://localhost:{admin_port}"])

    def record_routes():
        current = json.loads(run(["tailscale", "serve", "status", "--json"], capture=True))
        atomic(record_path, json.dumps({"hostname": hostname, "config": current}))

    record_routes()
    mcp_port = (
        18787 if platform.system() == "Darwin" else int(read_env().get("DOT_HTTP_PORT", "18787"))
    )
    run(["tailscale", "funnel", "--bg", "--https=443", f"http://127.0.0.1:{mcp_port}"])
    record_routes()
    admin_url = "https://" + hostname + ":8443"
    atomic(ROOT / ".bridge/admin-url", admin_url)
    print(
        f"Private admin: {admin_url}/admin/\nPublic MCP: https://{hostname}/mcp\nRun ./bridge admin to pair this browser."
    )


def volume_names():
    config = json.loads(compose("config", "--format", "json", capture=True))
    return {name: config["volumes"][name]["name"] for name in VOLUMES}


def snapshot_command(mode, names, *, key=None, stage=None, work=None, image=None):
    image = image or read_env().get("COLLECTOR_IMAGE", "kakaotalk-collector/server:0.1.0")
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
    print(
        f"Encrypted snapshot: {destination}\nKeep secrets/backup_key separately; it is needed to restore."
    )
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
        print(
            "Restored to new volumes; the old volumes and configuration were retained. Run ./bridge start, then check both sessions. External event subscriptions must be created again."
        )
    finally:
        with contextlib.suppress(RuntimeError, OSError):
            run(["docker", "volume", "rm", work], capture=True)


def update(args):
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
        compose("up", "-d", "--no-build", *services())
        for _ in range(30):
            time.sleep(2)
            if doctor(report=False):
                print("Update complete. Existing Android app data and enrollment were preserved.")
                return
        raise RuntimeError("Health check failed after update")
    except BaseException:
        atomic(ROOT / ".env", old)
        compose("up", "-d", "--no-build", *services())
        raise


def package_source(destination):
    files = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture=True
    ).split("\0")
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
            ):
                archive.add(path, arcname=file, recursive=False)


def mac(args):
    if not shutil.which("limactl"):
        raise RuntimeError("Install Lima first: brew install lima. Docker Desktop is not required.")
    config_path = ROOT / ".bridge/mac.json"
    if not config_path.exists() and args.command != "install":
        raise RuntimeError("Run ./bridge install first; this checkout has no managed Lima runtime.")
    config = (
        json.loads(config_path.read_text())
        if config_path.exists()
        else {"vm": args.vm, "directory": "/srv/kakaotalk-bridge", "admin_port": args.admin_port}
    )
    vm, directory = config["vm"], config["directory"]

    def guest(*command, capture=False):
        return run(["limactl", "shell", "--workdir=/", vm, "sudo", *command], capture=capture)

    def invoke(*command, capture=False):
        return guest("python3", directory + "/ops/cli.py", "--local", *command, capture=capture)

    if args.command in ("install", "update"):
        instances = run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines()
        if vm not in instances:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,48}", vm)
                or not 1024 <= config["admin_port"] <= 65535
            ):
                raise ValueError("Invalid VM name or admin port")
            for port in (config["admin_port"], 18787):
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
                "  - guestPort: 18787\n    hostPort: 18787\n    hostIP: 127.0.0.1\n  - guestPortRange:",
            )
            if platform.machine() == "x86_64":
                template = template.replace("arch: aarch64", "arch: x86_64").replace(
                    "vmType: vz", "vmType: qemu"
                )
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "lima.yaml"
                path.write_text(template)
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
    elif args.command == "admin":
        code = invoke("admin", "--code-only", capture=True)
        open_admin(
            code,
            args.url
            or (
                (ROOT / ".bridge/admin-url").read_text().strip()
                if (ROOT / ".bridge/admin-url").exists()
                else f"https://localhost:{config['admin_port']}"
            ),
        )
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
        print("Copied encrypted snapshot to " + str(destination))
        print(
            "Backup and recovery key are inside the VM. Copy backups/ and secrets/backup_key to separate private storage; see docs/onboarding.md."
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
        finally:
            guest("rm", "-rf", remote)

    else:
        options = [args.command]
        if args.command == "connect":
            options += ["--url", args.url]
        invoke(*options)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "update"):
        cmd = sub.add_parser(name)
        mode = cmd.add_mutually_exclusive_group()
        mode.add_argument("--source", action="store_true")
        mode.add_argument("--manifest")
        cmd.add_argument("--vm", default="kakaotalk-bridge")
        cmd.add_argument("--admin-port", type=int, default=18443)
    cmd = sub.add_parser("admin")
    cmd.add_argument("--url")
    cmd.add_argument("--code-only", action="store_true", help=argparse.SUPPRESS)
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
    try:
        if (
            args.command == "backup"
            and args.name
            and not re.fullmatch(r"[a-zA-Z0-9_-]+\.kcs", args.name)
        ):
            raise ValueError("Invalid snapshot filename")
        if args.local or platform.system() == "Linux":
            recover_activation()
        if args.command == "expose":
            expose(args)
        elif platform.system() == "Darwin" and not args.local:
            mac(args)
        elif args.command == "install":
            install(args)
        elif args.command == "update":
            update(args)
        elif args.command == "admin":
            code = admin_code()
            if args.code_only:
                print(code)
            else:
                open_admin(
                    code,
                    args.url
                    or (
                        (ROOT / ".bridge/admin-url").read_text().strip()
                        if (ROOT / ".bridge/admin-url").exists()
                        else "https://localhost:" + read_env().get("HTTPS_PORT", "8443")
                    ),
                )
        elif args.command == "doctor":
            if not doctor():
                raise SystemExit(1)
        elif args.command == "connect":
            connect(args.url)
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
            if any(destination.glob("*.apk")):
                raise RuntimeError(
                    "inputs/kakao already contains APKs. Move the old set aside first; do not mix versions."
                )
            for index, file in enumerate(files):
                shutil.copyfile(file, destination / f"{index}.apk")
            print(
                "APK set copied. Use Set up collection components in admin to verify and install it."
            )
        elif args.command == "reset-password":
            compose("exec", "-T", "admin", "python", "-m", "webui.auth", "reset-password")
        elif args.command == "stop":
            compose("stop")
        elif args.command == "start":
            pending = ROOT / ".bridge/restored-pending"
            compose(
                "up",
                "-d",
                "--no-build",
                *(["--force-recreate"] if pending.exists() else []),
                *services(),
            )
            pending.unlink(missing_ok=True)
    except (RuntimeError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
