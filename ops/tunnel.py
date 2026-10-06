"""Provision a personal OpenAI tunnel without changing public OAuth or admin routing."""

import contextlib
import json
import re
import secrets
from pathlib import Path

from ops import cli
from ops.errors import BridgeError

TUNNEL_ID = r"tunnel_[a-z0-9]{32}"


def add_arguments(parser):
    commands = parser.add_subparsers(dest="tunnel_command", required=True)
    configure = commands.add_parser("configure", help="개인 터널 시작 (관리 화면에서 승인 필요)")
    configure.add_argument("--tunnel-id", required=True)
    configure.add_argument("--api-key-file", required=True)
    commands.add_parser("status", help="인증 정보를 제외한 터널 설정 및 준비 상태 표시")
    commands.add_parser("disable", help="개인 터널 권한 취소 및 서비스 중지")


def credentials(identity, key_file):
    if not re.fullmatch(TUNNEL_ID, identity):
        raise BridgeError("OpenAI에서 받은 tunnel_로 시작하는 터널 ID(소문자·숫자 32자)를 입력하세요.")
    key = Path(key_file).read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,512}", key):
        raise BridgeError("실행용 API 키 파일에는 OpenAI API 키 하나만 들어 있어야 합니다.")
    return key


def control_call(path, body):
    return json.loads(
        cli.compose(
            "exec",
            "-T",
            "admin",
            "python",
            "-c",
            "import json,sys; from webui.connections import Connections; "
            "p=json.load(sys.stdin); print(json.dumps(Connections().call('POST',p['path'],p['body'])))",
            input=json.dumps({"path": path, "body": body}),
            capture=True,
        )
    )


def revoke(identity):
    control_call("/tunnel/decision", {"tunnel_id": identity, "approve": False})


def status():
    values = cli.read_env()
    enabled = values.get("OPENAI_TUNNEL_ENABLED") == "1"
    result = {
        "configured": enabled,
        "tunnel_id": values.get("OPENAI_TUNNEL_ID", ""),
        "ready": False,
    }
    if enabled:
        try:
            cli.compose(
                "exec",
                "-T",
                "dot-tunnel",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://openai-tunnel:8080/readyz',timeout=3)",
                capture=True,
            )
            result["ready"] = True
        except (RuntimeError, OSError):
            pass
    return result


def configure(identity, key_file):
    key = credentials(identity, key_file)
    if not (cli.ROOT / "secrets/mcp_storage_key").is_file():
        raise BridgeError("터널을 설정하기 전에 ./bridge up으로 Bridge를 설치하세요.")
    values = cli.read_env()
    private = cli.ROOT / "secrets/mcp_tunnel_authorization"
    if private.exists() and not re.fullmatch(
        r"Bearer [A-Za-z0-9_-]{43,}", private.read_text().strip()
    ):
        raise BridgeError("기존 개인 터널 인증 정보(secrets/mcp_tunnel_authorization)를 복구하세요.")
    paths = [
        cli.ROOT / name
        for name in (
            ".env",
            "secrets/openai_tunnel_api_key",
            "secrets/mcp_tunnel_authorization",
            ".bridge/tunnel.json",
        )
    ]
    before = {
        path: (path.read_text(), path.stat().st_mode & 0o777) if path.exists() else None
        for path in paths
    }
    # Pull before changing the currently running installation.
    cli.compose("pull", "openai-tunnel")
    previous = values.get("OPENAI_TUNNEL_ID")
    if values.get("OPENAI_TUNNEL_ENABLED") == "1" and previous != identity:
        revoke(previous)
    try:
        cli.compose("stop", "openai-tunnel", "dot-tunnel")
        for name, value in (
            ("openai_tunnel_api_key", key),
            ("mcp_tunnel_authorization", "Bearer " + secrets.token_urlsafe(32)),
        ):
            path = cli.ROOT / "secrets" / name
            if name != "mcp_tunnel_authorization" or not path.exists():
                cli.atomic(path, value + "\n")
            path.chmod(0o444)  # Docker secrets must be readable by non-root containers.
        cli.env_update({"OPENAI_TUNNEL_ENABLED": "1", "OPENAI_TUNNEL_ID": identity})
        cli.compose(
            "up",
            "-d",
            "--no-build",
            "dot-control",
            "dot-plugin",
            *(["dot-ingress"] if "dot-ingress" in cli.services() else []),
        )
        # Atomic file replacement needs new mounts even if only the API key changed.
        cli.compose(
            "up",
            "-d",
            "--no-build",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "90",
            "dot-tunnel",
            "openai-tunnel",
        )
        cli.atomic(cli.ROOT / ".bridge/tunnel.json", json.dumps({"tunnel_id": identity}))
    except (RuntimeError, OSError):
        try:
            with contextlib.suppress(RuntimeError, OSError):
                cli.compose("stop", "openai-tunnel", "dot-tunnel")
            for path, saved in before.items():
                if saved is None:
                    path.unlink(missing_ok=True)
                else:
                    cli.atomic(path, saved[0])
                    path.chmod(saved[1])
            cli.compose(
                "up",
                "-d",
                "--no-build",
                *[
                    service
                    for service in cli.services()
                    if service not in {"dot-tunnel", "openai-tunnel"}
                ],
            )
            if values.get("OPENAI_TUNNEL_ENABLED") == "1":
                cli.compose(
                    "up", "-d", "--no-build", "--force-recreate", "dot-tunnel", "openai-tunnel"
                )
        except (RuntimeError, OSError):
            raise BridgeError("터널 설정에 실패했고 이전 설정 복구도 끝나지 않았습니다. 설정을 확인하고 ./bridge doctor를 실행하세요. 인증 정보는 출력하지 않았습니다.") from None
        # Revoked grants stay revoked; rollback never restores data access.
        raise BridgeError("터널 설정에 실패해 이전 설정으로 되돌렸습니다. 터널 ID를 바꾸던 중이었다면 관리 화면에서 이전 터널을 다시 승인하세요.") from None
    show_configured(identity)


def show_configured(identity):
    print(
        "개인 터널을 설정했습니다. 관리 화면 → AI 연결 → 개인 터널 허용을 누르세요.\n"
        "ChatGPT에서 터널(Tunnel)을 선택하고 다음 ID를 지정하세요: "
        + identity
        + ". OAuth 로그인은 필요하지 않습니다.\n"
        "관리 화면 주소와 공개 OAuth 연결은 유지됩니다."
    )


def run(args):
    if args.tunnel_command == "configure":
        configure(args.tunnel_id, args.api_key_file)
    elif args.tunnel_command == "status":
        print(json.dumps(status(), indent=2))
    else:
        values = cli.read_env()
        if values.get("OPENAI_TUNNEL_ENABLED") == "1":
            revoke(values["OPENAI_TUNNEL_ID"])
            cli.compose("stop", "openai-tunnel", "dot-tunnel")
            cli.env_update({"OPENAI_TUNNEL_ENABLED": "0"})
            cli.compose("up", "-d", "--no-build", "--no-deps", "dot-control", "dot-plugin")
        (cli.ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
        print("개인 터널을 비활성화했습니다. 공개 OAuth 연결은 유지됩니다.")
