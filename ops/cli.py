"""Idempotent single-owner installation and operations; Python standard library only."""

import argparse
import contextlib
import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    # Run as a script inside the VM; make the ops package importable.
    sys.path.insert(0, str(ROOT))

from ops.errors import BridgeError


def progress(text):
    from ops.setup_output import progress as show

    show(text)


def notice(text):
    from ops.setup_output import notice as show

    show(text)


def share_code():
    """Root-run installs keep code readable for the SSH account that runs bridge mcp."""
    if os.geteuid() == 0:
        from ops.source import share_code as share

        with contextlib.suppress(OSError):
            share(ROOT)


def diagnostics():
    """The run log for helper output, or None to leave it on the terminal."""
    from ops.setup_output import log_target

    return log_target(False, {})

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
    from ops.setup_output import log_failure, log_target, provider_command, stream

    if (
        not capture
        and not kwargs
        and any(Path(str(arg)).name.lower() == "tailscale" for arg in args)
        and ("funnel" in args or "up" in args)
    ):
        return provider_command(args)
    log = log_target(capture, kwargs)
    if log is not None:
        return stream(args, log, **kwargs)
    result = subprocess.run(
        args, cwd=ROOT, text=True, capture_output=capture, check=False, **kwargs
    )
    if result.returncode:
        # Captured output can contain private paths or device data; do not echo it.
        if capture:
            log_failure(args, result)
        raise RuntimeError(f"Command failed: {Path(args[0]).name} (exit {result.returncode})")
    return result.stdout.strip() if capture else ""


def read_env():
    data = {}
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, sep, value = line.partition("=")
                if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                    raise BridgeError(".env 파일은 KEY=value 형식의 줄만 사용할 수 있습니다.")
                data[key] = value
    return data


def env_update(values):
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not re.fullmatch(
            r"[A-Za-z0-9_:/@.=-]+", value
        ):
            raise BridgeError("설정 값이 올바르지 않습니다. 영문자, 숫자와 일부 기호만 사용할 수 있습니다.")
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


# Default Compose project before 0.2. Its volumes keep this prefix on existing installs.
LEGACY_PROJECT = "kakaotalk-collector"


@functools.cache
def pin_project_name():
    """Keep an install whose .env predates the project name on its existing volumes."""
    if not (ROOT / ".env").exists() or "COMPOSE_PROJECT_NAME" in read_env():
        return
    existing = run(
        ["docker", "volume", "ls", "-q", "--filter", f"name=^{LEGACY_PROJECT}_android-data$"],
        capture=True,
    )
    env_update({"COMPOSE_PROJECT_NAME": LEGACY_PROJECT if existing.strip() else "kakaotalk-bridge"})


def compose(*args, capture=False, **kwargs):
    pin_project_name()
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
    from ops.releases import validate_manifest

    return validate_manifest(json.loads(Path(path).read_text()))


def main():
    os.umask(0o077)
    parser = KoreanArgumentParser(description="KakaoTalk Bridge 설치 및 관리")
    parser.add_argument("--local", action="store_true", help=argparse.SUPPRESS)
    # Child commands report progress and errors to the Bridge process that started them.
    parser.add_argument("--progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--raw-output", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True, metavar="명령")
    from ops.onboarding import add_arguments

    add_arguments(sub.add_parser("up", help="실행 환경을 준비하고 카카오톡 설정 화면 열기"))
    from ops.tunnel import add_arguments as tunnel_arguments

    tunnel_arguments(sub.add_parser("tunnel", help="개인 OpenAI MCP 터널 관리"))
    from ops.connections import add_arguments as connection_arguments

    connection_arguments(sub.add_parser("setup-connection", help="AI 연결 방식 선택 및 설정"))
    sub.add_parser("mcp", help="로컬 MCP stdio 어댑터 실행")
    agent = sub.add_parser("setup-agent", help="관리 화면의 연결 설정 서비스 관리")
    agent.add_argument("agent_command", choices=("install", "serve", "job"), metavar="작업")
    for name, description in (
        ("install", "Bridge 설치 (보통 ./bridge up을 사용)"),
        ("update", "같은 설치에서 이미지 업데이트 (보통 ./bridge upgrade를 사용)"),
    ):
        cmd = sub.add_parser(name, help=description)
        mode = cmd.add_mutually_exclusive_group()
        mode.add_argument("--source", action="store_true", help="현재 소스 빌드")
        mode.add_argument("--manifest", metavar="파일", help="검증된 릴리스 정보(release.json)")
        cmd.add_argument("--vm", default="kakaotalk-bridge", metavar="이름", help="Mac의 Lima VM 이름")
        cmd.add_argument("--admin-port", type=int, metavar="포트", help="내부 관리 포트")
        cmd.add_argument("--mcp-port", type=int, metavar="포트", help="로컬 공용 진입 포트")
    cmd = sub.add_parser("upgrade", help="검증된 릴리스로 설치 파일과 이미지를 함께 업데이트")
    cmd.add_argument(
        "--version", default="latest", metavar="버전", help="릴리스 버전 (기본값: 최신 정식 릴리스)"
    )
    cmd = sub.add_parser("admin", help="관리 화면 열기")
    cmd.add_argument("--url", metavar="주소", help="열 관리 화면 주소")
    cmd.add_argument("--recovery", action="store_true", help="일회용 긴급 복구 링크 발급")
    cmd.add_argument("--code-only", action="store_true", help=argparse.SUPPRESS)
    cmd.add_argument("--info", action="store_true", help=argparse.SUPPRESS)
    cmd = sub.add_parser(
        "passkey-login",
        help="관리 화면과 MCP의 패스키 설정",
    )
    cmd.add_argument(
        "--url", metavar="주소", help="관리 화면 HTTPS 주소 또는 http://localhost:<포트>"
    )
    cmd.add_argument("--public-url", metavar="주소", help="공개 HTTPS MCP 주소")
    cmd.add_argument("--enroll", action="store_true", help="일회용 등록·복구 링크 발급")
    cmd.add_argument("--link-only", action="store_true", help=argparse.SUPPRESS)
    cmd = sub.add_parser("connect", help="기존 HTTPS 프록시 주소를 MCP 주소로 설정")
    cmd.add_argument("--url", required=True, metavar="주소", help="공개 HTTPS 주소")
    cmd = sub.add_parser("import-apks", help="공식 카카오톡 APK 세트 가져오기")
    cmd.add_argument("folder", metavar="폴더", help="APK 파일이 있는 폴더")
    cmd = sub.add_parser("restore", help="./bridge backup으로 만든 백업 복구")
    cmd.add_argument("file", metavar="백업파일", help=".kcs 백업 파일")
    cmd.add_argument("--key", required=True, metavar="키파일", help="백업할 때의 secrets/backup_key")
    cmd = sub.add_parser("backup", help="Android·수집 데이터·설정 전체를 암호화해 백업")
    cmd.add_argument("--name", help=argparse.SUPPRESS)
    cmd = sub.add_parser("doctor", help="실행 환경과 서비스 상태 점검")
    cmd.add_argument("--json", action="store_true", help="점검 결과를 JSON으로 출력")
    cmd = sub.add_parser("cleanup", help="Bridge와 데이터·백업을 모두 삭제 (공용 도구는 유지)")
    cmd.add_argument("--yes", action="store_true", help="확인 없이 삭제")
    for name, description in (
        ("start", "서비스 시작"),
        ("stop", "서비스 중지 (데이터와 로그인은 유지)"),
        ("reset-password", "로컬 관리자 비밀번호 초기화 (ADMIN_AUTH_MODE=local 전용)"),
        ("expose", "Tailscale로 공개 HTTPS 주소 만들기"),
    ):
        sub.add_parser(name, help=description)
    args = parser.parse_args()
    from ops.setup_output import CHILD, RAW, operation, report_error

    if args.progress:
        os.environ[CHILD] = "1"
    if args.raw_output:
        os.environ[RAW] = "1"
    try:
        with operation(args):
            execute(args)
    except KeyboardInterrupt:
        print("중단되었습니다. 같은 명령을 실행해 이어서 진행하세요.", file=sys.stderr)
        raise SystemExit(130) from None
    except subprocess.TimeoutExpired:
        report_error(BridgeError("명령의 제한 시간이 지났습니다. 같은 명령으로 다시 시도하세요."))
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 — never show a traceback; keep it in the log
        report_error(exc)
        raise SystemExit(1) from None


def execute(args):
    from ops import access, backup, doctor, expose, install, lima
    from ops.onboarding import up

    if args.command == "upgrade":
        from ops.releases import upgrade

        upgrade(args)
        return
    if args.command == "up":
        up(args)
        return
    if args.command == "cleanup":
        from ops.cleanup import cleanup

        cleanup(args)
        return
    if args.command == "setup-connection":
        from ops.connections import setup

        setup(args)
        return
    if args.command == "setup-agent":
        if platform.system() == "Darwin" and not args.local:
            lima.mac(args)
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
        raise BridgeError("백업 파일 이름이 올바르지 않습니다.")
    if args.local or platform.system() == "Linux":
        backup.recover_activation()
    if args.command == "passkey-login":
        access.passkey_setup(args)
    elif args.command == "expose":
        expose.expose(args)
    elif platform.system() == "Darwin" and not args.local:
        lima.mac(args)
    elif args.command == "install":
        install.install(args)
    elif args.command == "update":
        install.update(args)
    elif args.command == "admin":
        if args.info:
            print(json.dumps(access.admin_info()))
        elif args.recovery:
            code = access.admin_code()
            if args.code_only:
                print(code)
            else:
                access.open_admin(code, access.admin_url(args.url))
        else:
            info = access.admin_info()
            access.open_admin_page(args.url or info.get("origin") or access.admin_url())
    elif args.command == "doctor":
        if not doctor.doctor(report="json" if args.json else True):
            raise SystemExit(1)
    elif args.command == "mcp":
        compose("run", "--rm", "--no-deps", "-T", "mcp")
    elif args.command == "connect":
        access.connect(args.url)
    elif args.command == "tunnel":
        from ops.tunnel import run as run_tunnel

        run_tunnel(args)
    elif args.command == "backup":
        backup.backup(name=args.name)
    elif args.command == "restore":
        backup.restore(args.file, args.key)
    elif args.command == "import-apks":
        files = sorted(Path(args.folder).glob("*.apk"))
        if not files:
            raise BridgeError("이 폴더에 APK 파일이 없습니다.")
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
            raise BridgeError("inputs/kakao에 이미 다른 APK 세트가 있습니다. 버전이 섞이지 않도록 기존 파일을 다른 곳으로 옮긴 뒤 다시 실행하세요.")
        for index, file in enumerate(files):
            shutil.copyfile(file, destination / f"{index}.apk")
        print("APK 세트를 복사했습니다. 관리 화면의 ‘수집 구성 요소 설치’에서 검증하고 설치하세요.")
    elif args.command == "reset-password":
        compose("exec", "-T", "admin", "python", "-m", "webui.auth", "reset-password")
    elif args.command == "stop":
        compose("stop")
    elif args.command == "start":
        # Older encrypted snapshots predate this verifier-only service credential.
        install.ensure_passkey_verifier_secret()
        install.migrate_auth_modes()
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
