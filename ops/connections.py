"""Choose an optional AI connection without replacing the admin identity."""

import argparse
import getpass
import json
import sys
import tempfile
from pathlib import Path

from ops import cli, onboarding, tunnel
from ops.errors import BridgeError

METHODS = ("none", "stdio", "https", "tailscale", "openai-tunnel")


def add_arguments(parser):
    parser.add_argument("--method", choices=METHODS)
    parser.add_argument("--url", help="공개 HTTPS MCP 주소 (관리 화면 주소 유지)")
    parser.add_argument("--tunnel-id")
    parser.add_argument("--api-key-file")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-install", action="store_true")


def ask(prompt):
    if not sys.stdin.isatty():
        raise BridgeError("입력할 수 없는 환경에서는 --method와 필요한 옵션을 함께 지정하세요.")
    return input(prompt).strip()


def setup(args):
    method = args.method
    if method is None:
        print(
            "AI 연결은 선택 사항이며 여러 방식을 함께 사용할 수 있습니다. 기존 연결은 유지됩니다.\n"
            "1. 나중에 결정 (현재 설정 유지)\n"
            "2. 로컬 AI 클라이언트 — stdio\n"
            "3. 공개 HTTPS — 직접 구성한 리버스 프록시 + OAuth\n"
            "4. 공개 HTTPS — Tailscale Funnel + OAuth\n"
            "5. ChatGPT — 개인 OpenAI 터널"
        )
        choice = ask("선택 [1]: ") or "1"
        if choice not in {"1", "2", "3", "4", "5"}:
            raise BridgeError("1부터 5 사이의 번호를 선택하세요.")
        method = METHODS[int(choice) - 1]
    if args.url and method != "https":
        raise BridgeError("--url은 --method https와 함께 사용하세요.")
    if (args.tunnel_id or args.api_key_file) and method != "openai-tunnel":
        raise BridgeError("터널 정보는 --method openai-tunnel과 함께 사용하세요.")
    if method == "none":
        print("연결을 변경하지 않았습니다. AI 연결 없이도 수집과 관리 화면을 사용할 수 있습니다.")
        return
    if method == "stdio":
        print("로컬 AI 클라이언트의 MCP 설정에 아래 서버를 추가하세요:")
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "kakaotalk": {
                            "command": sys.executable,
                            "args": [str(cli.ROOT / "bridge"), "mcp"],
                        }
                    }
                },
                indent=2,
            )
        )
        print(
            "클라이언트가 설치된 Docker Engine 또는 전용 Lima VM에 접근할 수 있어야 합니다.\n"
            "원격 서버에서는 SSH로 같은 bridge mcp 명령을 실행하세요(TTY 없이 실행)."
        )
        return
    with tempfile.TemporaryDirectory(prefix="bridge-connection-") as folder:
        if method == "https":
            args.url = args.url or ask("공개 HTTPS 주소 (https://your-host): ")
            cli.validate_public_url(args.url)
        if method == "openai-tunnel":
            print(
                "OpenAI 워크스페이스의 터널 ID와 실행용 API 키를 사용하세요.\n"
                "제공업체 설정 안내: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels"
            )
            args.tunnel_id = args.tunnel_id or ask("터널 ID: ")
            if not args.api_key_file:
                if not sys.stdin.isatty():
                    raise BridgeError("입력할 수 없는 환경에서는 --api-key-file을 지정하세요.")
                path = Path(folder) / "runtime-key"
                cli.atomic(path, getpass.getpass("실행용 API 키 (입력 내용 숨김): ").strip() + "\n")
                args.api_key_file = str(path)
            tunnel.credentials(args.tunnel_id, args.api_key_file)
        options = argparse.Namespace(
            connection=method,
            admin_url=None,
            public_url=args.url,
            tunnel_id=args.tunnel_id,
            api_key_file=args.api_key_file,
            no_browser=args.no_browser,
            no_install=args.no_install,
        )
        with onboarding.installation_lock():
            runtime = onboarding.Runtime()
            if not runtime.installed():
                raise BridgeError("AI 연결을 추가하기 전에 ./bridge up으로 Bridge를 먼저 설치하세요.")
            runtime.call("start")
            if method == "tailscale":
                prepare = (
                    onboarding.prepare_mac
                    if cli.platform.system() == "Darwin"
                    else onboarding.prepare_linux
                )
                prepare(options)
            onboarding.connect_network(options, runtime)
            # This configures OAuth consent automatically, retaining the existing
            # passkey RP. Tunnel consent still requires an explicit admin decision.
            onboarding.open_setup(options, runtime)
            if method in {"https", "tailscale"}:
                print(
                    "AI 클라이언트에 공개 /mcp 주소를 추가하고 OAuth를 선택하세요.\n"
                    "동의 화면을 따라 진행하세요. 코드가 표시되면 관리 화면 → AI 연결에서 일치하는 요청을 승인하세요."
                )
