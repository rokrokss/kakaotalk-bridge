"""The managed Lima VM on macOS; commands run inside it with ops/cli.py --local."""

import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

from ops import access, cli, launcher
from ops.errors import BridgeError


def package_source(destination):
    # Release/source archives have no .git directory. Explicitly enumerate source
    # roots so local credentials, volumes and virtualenvs cannot enter the guest.
    from ops.source import CODE_DIRS

    files = []
    if (cli.ROOT / ".git").exists() and shutil.which("git"):
        files = cli.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture=True
        ).split("\0")
    for entry in [] if files else sorted(cli.ROOT.iterdir()):
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
                files.extend(str((Path(folder) / name).relative_to(cli.ROOT)) for name in names)
        elif entry.is_file() and entry.name in {
            "bridge",
            "compose.yaml",
            "LICENSE",
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
            path = cli.ROOT / file
            if (
                path.is_file()
                and not path.is_symlink()
                and not any(
                    p in {"secrets", "inputs", "artifacts", "backups", ".bridge", ".git"}
                    for p in path.relative_to(cli.ROOT).parts
                )
                and not file.startswith(".env")
                and not path.name.startswith(".env")
                and not file.endswith((".local.plist", ".pyc", ".log", ".pem", ".key"))
            ):
                archive.add(path, arcname=file, recursive=False)


def available_port(preferred, requested=None, exclude=()):
    port = requested if requested is not None else preferred
    if not 1024 <= port <= 65535:
        raise BridgeError("포트는 1024에서 65535 사이로 지정하세요.")
    with socket.socket() as probe:
        try:
            if port in exclude:
                raise OSError("Port selected twice")
            probe.bind(("127.0.0.1", port))
        except OSError:
            if requested is not None:
                raise BridgeError(f"{port} 포트가 이미 사용 중입니다. 다른 포트를 지정하세요.") from None
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def mac(args):
    if not shutil.which("limactl"):
        raise BridgeError("Lima를 먼저 설치하세요: brew install lima (Docker Desktop은 필요하지 않습니다).")
    config_path = cli.ROOT / ".bridge/mac.json"
    if not config_path.exists() and args.command != "install":
        raise BridgeError("이 설치에는 관리되는 Lima VM이 없습니다. kakaotalk-bridge up으로 먼저 설치하세요.")
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
        return cli.run(["limactl", "shell", "--workdir=/", vm, "sudo", *command], capture=capture)

    def invoke(*command, capture=False):
        from ops.setup_output import bridge_command

        child = bridge_command(*command, entry=["python3", directory + "/ops/cli.py", "--local"])
        return guest(*child, capture=capture)

    if args.command in ("install", "update"):
        instances = cli.run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines()
        if vm in instances and not existing_config:
            raise BridgeError("같은 이름의 VM이 이미 다른 용도로 있습니다. --vm으로 다른 이름을 지정하세요.")
        if vm not in instances:
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,48}", vm)
                or not 1024 <= config["admin_port"] <= 65535
            ):
                raise BridgeError("VM 이름 또는 관리 포트가 올바르지 않습니다.")
            for port in (config["admin_port"], config["mcp_port"]):
                with socket.socket() as probe:
                    probe.settimeout(0.2)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        raise BridgeError(f"{port} 포트가 이미 사용 중입니다. 기존 서비스는 그대로 두고 비어 있는 포트를 --admin-port로 지정하세요.")
            if args.command != "install":
                raise BridgeError("먼저 kakaotalk-bridge up으로 설치하세요.")
            template = (
                (cli.ROOT / "deploy/lima.yaml")
                .read_text()
                .replace("hostPort: 18443", f"hostPort: {config['admin_port']}")
            )
            template = template.replace(
                "  - guestPortRange:",
                f"  - guestPort: 18787\n    hostPort: {config['mcp_port']}\n    hostIP: 127.0.0.1\n  - guestPortRange:",
            )
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
                cli.atomic(config_path, json.dumps(config))
                cli.progress("가상 머신 만드는 중… 처음 한 번은 몇 분 걸릴 수 있습니다.")
                cli.run(["limactl", "start", "--tty=false", "--name", vm, str(path)])
        else:
            cli.progress("가상 머신 시작 중…")
            cli.run(["limactl", "start", "--tty=false", vm])
        cli.atomic(config_path, json.dumps(config))
        cli.progress("설치 파일을 가상 머신으로 복사하는 중…")
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "source.tar.gz"
            package_source(archive)
            guest("mkdir", "-p", directory)
            remote = "/tmp/kakao-source-" + secrets.token_hex(8) + ".tar.gz"
            cli.run(["limactl", "copy", str(archive), vm + ":" + remote])
            try:
                # Execute from /tmp so moving ops/ cannot replace the running refresh code.
                helper = remote + ".py"
                cli.run(["limactl", "copy", str(cli.ROOT / "ops/source.py"), vm + ":" + helper])
                guest("python3", helper, "apply", directory, remote)
            finally:
                guest("rm", "-f", remote)
        options = [args.command]
        if args.source:
            options += ["--source"]
        elif args.manifest:
            cli.manifest(args.manifest)
            cli.run(
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
            cli.run(
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
                    {
                        "command": launcher.client_command()[0],
                        "args": [*launcher.client_command()[1:], "mcp"],
                    }
                ),
            )
        invoke("setup-agent", args.agent_command)
    elif args.command == "admin":
        if args.recovery:
            code = invoke("admin", "--recovery", "--code-only", capture=True)
            access.open_admin(code, access.admin_url(args.url))
        else:
            info = json.loads(invoke("admin", "--info", capture=True))
            access.open_admin_page(args.url or info.get("origin") or access.admin_url())
    elif args.command == "tunnel":
        if args.tunnel_command == "configure":
            from ops.tunnel import credentials

            credentials(args.tunnel_id, args.api_key_file)
            target = "/tmp/kakao-tunnel-" + secrets.token_hex(8)
            cli.run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", target])
            try:
                cli.run(
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
                cli.atomic(cli.ROOT / ".bridge/tunnel.json", json.dumps({"tunnel_id": args.tunnel_id}))
                from ops.tunnel import show_configured

                show_configured(args.tunnel_id)
            finally:
                guest("rm", "-rf", target)
        else:
            invoke("tunnel", args.tunnel_command)
            if args.tunnel_command == "disable":
                (cli.ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
                print("개인 터널을 비활성화했습니다. 공개 OAuth 연결은 유지됩니다.")
    elif args.command == "import-apks":
        target = "/tmp/kakao-import-" + secrets.token_hex(8)
        files = list(Path(args.folder).glob("*.apk"))
        if not files:
            raise BridgeError("이 폴더에 APK 파일이 없습니다.")
        # Use a private staging directory, not a shared mount of the host home.
        cli.run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", target])
        try:
            cli.run(["limactl", "copy", *[str(p.resolve()) for p in files], vm + ":" + target + "/"])
            invoke("import-apks", target)
        finally:
            guest("rm", "-rf", target)
    elif args.command == "backup":
        name = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".kcs"
        invoke("backup", "--name", name)
        cli.progress("백업을 Mac으로 복사하는 중…")
        destination = cli.ROOT / "backups" / name
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
                stderr=cli.diagnostics(),
                check=False,
            )
        if result.returncode:
            destination.unlink(missing_ok=True)
            raise BridgeError("백업은 VM 안에 만들어졌지만 Mac으로 복사하지 못했습니다. 다시 실행하세요.")
        cli.notice(
            "암호화된 백업을 복사했습니다: "
            + str(destination)
            + "\n백업과 복구 키는 VM 안에 있습니다. backups/와 secrets/backup_key를 각각 별도의 안전한 저장소에 복사하세요."
        )
    elif args.command == "restore":
        remote = "/tmp/kakao-restore-" + secrets.token_hex(8)
        cli.run(["limactl", "shell", "--workdir=/", vm, "mkdir", "-m", "700", remote])
        try:
            for source, name in ((args.file, "backup.kcs"), (args.key, "key")):
                cli.run(
                    ["limactl", "copy", str(Path(source).resolve()), vm + ":" + remote + "/" + name]
                )
            invoke("restore", remote + "/backup.kcs", "--key", remote + "/key")
            # Runtime .env is restored, but the Mac-only launch hint is not in snapshots.
            restored_tunnel = json.loads(invoke("tunnel", "status", capture=True))
            if restored_tunnel["configured"]:
                cli.atomic(
                    cli.ROOT / ".bridge/tunnel.json",
                    json.dumps({"tunnel_id": restored_tunnel["tunnel_id"]}),
                )
            else:
                (cli.ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
        finally:
            guest("rm", "-rf", remote)

    else:
        if args.command == "start":
            instances = cli.run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines()
            if vm not in instances:
                raise BridgeError("관리되는 Lima VM이 없습니다. kakaotalk-bridge up을 실행하면 다시 만듭니다.")
            cli.progress("가상 머신 시작 중…")
            cli.run(["limactl", "start", "--tty=false", vm])
        options = [args.command]
        if args.command == "connect":
            options += ["--url", args.url]
        invoke(*options)
        if args.command == "connect":
            print(args.url + "/mcp\nkakaotalk-bridge passkey-login으로 이 주소의 로그인을 설정하세요.")
