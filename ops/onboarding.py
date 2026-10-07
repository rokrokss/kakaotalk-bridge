"""One-command onboarding. Credentials remain in the existing runtime/auth services."""

import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

from ops import access, cli, expose, launcher, releases
from ops.errors import BridgeError
from ops.setup_output import SetupOutput, progress, provider_line, run

STEPS = (
    ("environment", "실행 환경 준비"),
    ("runtime", "개인 Bridge 시작"),
    ("network", "선택한 AI 연결 준비"),
    ("browser", "카카오톡 설정 화면 열기"),
)


def network_config():
    try:
        return cli.read_env()
    except PermissionError:
        # Linux installs may use sudo. Read only non-secret networking settings
        # instead of loosening permissions on the runtime configuration.
        return json.loads(
            privileged(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json,pathlib,sys; "
                        "values=dict(line.split('=',1) for line in pathlib.Path(sys.argv[1]).read_text().splitlines() "
                        "if '=' in line and not line.lstrip().startswith('#')); "
                        "print(json.dumps({k:values[k] for k in "
                        "('OPENAI_TUNNEL_ENABLED','ADMIN_LOCAL_PORT') if k in values}))"
                    ),
                    str(cli.ROOT / ".env"),
                ],
                capture=True,
            )
        )


def add_arguments(parser):
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--source", action="store_true", help="현재 소스 빌드")
    mode.add_argument("--manifest", help="검증된 릴리스 매니페스트 사용")
    parser.add_argument("--plan", action="store_true", help="변경 없이 진행 단계만 표시")
    parser.add_argument("--verbose", action="store_true", help="진단용 원문 출력 표시")
    parser.add_argument("--no-install", action="store_true", help="호스트 의존성 자동 설치 안 함")
    parser.add_argument("--no-browser", action="store_true", help="원격 브라우저에서 열 링크 표시")
    parser.add_argument("--vm", default="kakaotalk-bridge")
    parser.add_argument(
        "--admin-port", type=int, help="내부 유지 관리 포트 (Mac에서는 빈 포트 자동 선택)"
    )
    parser.add_argument(
        "--mcp-port", type=int, help="로컬 공용 진입 포트 (Mac에서는 빈 포트 자동 선택)"
    )
    parser.add_argument("--apk-folder", help="첫 설정에서 공식 APK 세트 가져오기")
    parser.add_argument("--url", help="기존 리버스 프록시의 공용 HTTPS 주소")
    parser.add_argument(
        "--admin-url", help="관리 화면 HTTPS 주소 또는 http://localhost:<port> (고급)"
    )
    parser.add_argument("--public-url", help="기존 프록시의 공개 MCP HTTPS 주소")
    parser.add_argument(
        "--connection",
        choices=("none", "tailscale", "https", "openai-tunnel"),
        help="선택할 AI 연결 (기본값: 기존 연결 유지, 새 연결 추가 안 함)",
    )
    parser.add_argument("--tunnel-id", help="개인 OpenAI 터널 ID (첫 설정)")
    parser.add_argument("--api-key-file", help="터널 실행용 API 키를 담은 비공개 파일")


def validate(args):
    # A server session must never launch a browser on the remote host.
    if os.environ.get("SSH_CONNECTION") or (
        platform.system() == "Linux"
        and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    ):
        args.no_browser = True
    saved_tunnel = (cli.ROOT / ".bridge/tunnel.json").exists() or network_config().get(
        "OPENAI_TUNNEL_ENABLED"
    ) == "1"
    if args.connection is None and not args.url and not args.public_url and saved_tunnel:
        args.connection = "openai-tunnel"
    tunnel = args.connection == "openai-tunnel"
    if tunnel:
        if args.url or args.public_url:
            raise BridgeError("개인 터널 설정에는 --admin-url을 사용하세요. 공개 HTTPS는 따로 설정합니다.")
        saved = cli.ROOT / ".bridge/admin-url"
        if not args.admin_url and saved.exists() and os.access(saved, os.R_OK):
            args.admin_url = saved.read_text().strip().removesuffix("/admin/")
        if args.admin_url:
            access.private_url(args.admin_url)
        if bool(args.tunnel_id) != bool(args.api_key_file):
            raise BridgeError("--tunnel-id와 --api-key-file을 함께 지정하세요.")
        if args.tunnel_id:
            from ops.tunnel import credentials

            credentials(args.tunnel_id, args.api_key_file)
        elif not saved_tunnel and not args.plan:
            raise BridgeError("처음 터널을 설정할 때는 --tunnel-id와 --api-key-file이 필요합니다.")
    elif args.tunnel_id or args.api_key_file:
        raise BridgeError("터널 정보는 --connection openai-tunnel과 함께 사용하세요.")
    if args.connection == "https" and not (args.url or args.public_url):
        raise BridgeError("기존 HTTPS 프록시를 쓰려면 --url 또는 --public-url을 지정하세요.")
    if args.connection == "tailscale" and (args.url or args.admin_url or args.public_url):
        raise BridgeError("Tailscale과 기존 HTTPS 프록시 옵션은 함께 쓸 수 없습니다. 하나만 선택하세요.")
    if platform.system() not in {"Darwin", "Linux"}:
        raise BridgeError("이 컴퓨터에서는 실행할 수 없습니다. macOS 또는 Android Binder를 지원하는 Linux가 필요합니다. Windows에서는 install.ps1 -Remote user@linux-host로 Linux 서버에 설치하거나 Binder를 지원하는 WSL2를 사용하세요. 기본 WSL2와 Docker Desktop은 검증하지 않았습니다.")
    if platform.machine().lower() not in {"aarch64", "arm64", "x86_64", "amd64"}:
        raise BridgeError("arm64 또는 x86_64 컴퓨터가 필요합니다.")
    if args.url:
        if args.admin_url or args.public_url:
            raise BridgeError("--url만 지정하거나, --admin-url과 --public-url을 함께 지정하세요.")
        access.validate_public_url(args.url)
        args.admin_url = args.public_url = args.url
    if args.connection == "none" and (args.url or args.public_url):
        raise BridgeError("--connection none과 공개 MCP 주소는 함께 지정할 수 없습니다.")
    if args.admin_url:
        access.private_url(args.admin_url)
    if args.public_url:
        access.validate_public_url(args.public_url)
    for port in (args.admin_port, args.mcp_port):
        if port is not None and not 1024 <= port <= 65535:
            raise BridgeError("포트는 1024에서 65535 사이로 지정하세요.")
    if args.admin_port is not None and args.admin_port == args.mcp_port:
        raise BridgeError("--admin-port와 --mcp-port는 서로 다른 포트여야 합니다.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,48}", args.vm):
        raise BridgeError("VM 이름은 영문자, 숫자, -, _로 49자 이내여야 합니다.")
    if args.manifest:
        cli.manifest(args.manifest)
    if args.apk_folder and not list(Path(args.apk_folder).glob("*.apk")):
        raise BridgeError("--apk-folder에는 공식 카카오톡 APK 세트가 있어야 합니다.")


@contextlib.contextmanager
def installation_lock():
    # Kernel-owned lock is released even after a crash; never delete stale PID files.
    import fcntl

    path = cli.ROOT / ".bridge/up.lock"
    path.parent.mkdir(mode=0o700, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BridgeError("이 설치에서 다른 설정 작업이 이미 진행 중입니다. 끝난 뒤 다시 실행하세요.") from None
        yield


def privileged(command, *, capture=False):
    command = [shutil.which(command[0]) or command[0], *command[1:]]
    if os.geteuid() != 0:
        command = ["sudo", *command]
    return run(command, capture=capture)


def install_script(url, *, interactive=False):
    # Only fixed official dependency installers call this. No user-controlled URL.
    with urlopen(url, timeout=60) as response:
        content = response.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise BridgeError("내려받은 의존성 설치 프로그램의 크기가 예상과 다릅니다. 잠시 후 다시 시도하세요.")
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "install.sh"
        script.write_bytes(content)
        run(["/bin/bash", str(script)], interactive=interactive)


def require_install(args, description):
    label = {
        "the Mac execution environment": "Mac 실행 환경(Lima)",
        "the Intel Mac virtual machine driver": "Intel Mac 가상 머신 드라이버",
        "Tailscale for your secure browser connection": "보안 연결용 Tailscale",
        "Docker Engine and Compose": "Docker Engine 및 Compose",
        "Linux runtime packages": "Linux 실행 패키지",
    }.get(description, "필수 구성 요소")
    if args.no_install:
        raise BridgeError(f"{label}이(가) 없습니다. 직접 설치하거나 --no-install 없이 다시 실행하세요.")
    progress(f"{label} 설치 중… 운영체제에서 관리자 승인을 요청할 수 있습니다.")


def prepare_mac(args):
    if os.geteuid() == 0:
        raise BridgeError("Mac에서는 sudo 없이 일반 사용자로 실행하세요.")
    # GUI shells and fresh Homebrew installs may not include these paths yet.
    os.environ["PATH"] = os.pathsep.join(
        [os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"]
    )
    if not shutil.which("limactl"):
        require_install(args, "the Mac execution environment")
        if not shutil.which("brew"):
            install_script(
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
                interactive=True,
            )
        run(["brew", "install", "lima"])
    if platform.machine() == "x86_64" and not shutil.which("qemu-system-x86_64"):
        require_install(args, "the Intel Mac virtual machine driver")
        if not shutil.which("brew"):
            install_script(
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
                interactive=True,
            )
        run(["brew", "install", "qemu"])
    if args.connection == "tailscale" and not expose.tailscale_binary():
        require_install(args, "Tailscale for your secure browser connection")
        if not shutil.which("brew"):
            install_script(
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh",
                interactive=True,
            )
        run(["brew", "install", "--formula", "tailscale"])
        privileged(["brew", "services", "start", "tailscale"])


def binder_ready():
    return (
        Path("/sys/module/binder_linux").exists() or Path("/dev/binderfs/binder-control").exists()
    )


def prepare_linux(args):
    # A Docker context pointing at Desktop or another machine cannot use this host's Binder.
    is_wsl = "microsoft" in platform.release().lower()
    if is_wsl and not binder_ready():
        raise BridgeError("이 WSL 커널은 Android Binder를 지원하지 않아 아무것도 변경하지 않았습니다. install.ps1 -Remote user@linux-host로 Linux 서버에 설치하거나 Binder를 지원하는 WSL2 커널을 구성하세요.")
    packages = []
    if not shutil.which("docker"):
        require_install(args, "Docker Engine and Compose")
        install_script("https://get.docker.com")
    else:
        try:
            run(["docker", "compose", "version"], capture=True)
        except RuntimeError:
            for package in ("docker-compose-v2", "docker-compose-plugin"):
                try:
                    run(["apt-cache", "show", package], capture=True)
                    packages.append(package)
                    break
                except (OSError, RuntimeError):
                    continue
            else:
                raise BridgeError("기존 Docker Engine에 Compose v2 플러그인을 설치한 뒤 다시 실행하세요. 기존 Docker 설정은 그대로 두었습니다.") from None
    if not shutil.which("openssl"):
        packages.append("openssl")
    if not binder_ready():
        try:
            privileged(
                ["modprobe", "binder_linux", "devices=binder,hwbinder,vndbinder"], capture=True
            )
        except (OSError, RuntimeError):
            packages.append("linux-modules-extra-" + platform.release())
    if packages:
        require_install(args, "Linux runtime packages")
        if not shutil.which("apt-get"):
            raise BridgeError("자동 패키지 설치는 Ubuntu/Debian만 지원합니다. Docker Engine, Compose v2, OpenSSL, Android Binder를 직접 설치한 뒤 다시 실행하세요.")
        privileged(["apt-get", "update"])
        privileged(["apt-get", "install", "-y", *packages])
    if not binder_ready():
        try:
            privileged(["modprobe", "binder_linux", "devices=binder,hwbinder,vndbinder"])
        except (OSError, RuntimeError):
            raise BridgeError("이 커널은 Android Binder를 제공하지 않습니다. linux-modules-extra가 설치된 Ubuntu VM이나 호환되는 전용 Linux 서버를 사용하세요.") from None
    if shutil.which("systemctl"):
        # Load Binder before Docker on later boots. Do not overwrite host settings.
        privileged(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "p=Path('/etc/modules-load.d/kakaotalk-bridge.conf'); "
                    "p.exists() or p.write_text('binder_linux\\n'); "
                    "p=Path('/etc/modprobe.d/kakaotalk-bridge.conf'); "
                    "p.exists() or p.write_text('options binder_linux devices=binder,hwbinder,vndbinder\\n')"
                ),
            ]
        )
        privileged(["systemctl", "enable", "--now", "docker"])
    if args.connection == "tailscale" and not expose.tailscale_binary():
        require_install(args, "Tailscale for your secure browser connection")
        install_script("https://tailscale.com/install.sh")


class Runtime:
    def __init__(self):
        self.prefix = []
        if platform.system() == "Linux":
            try:
                run(["docker", "info"], capture=True)
            except (OSError, RuntimeError):
                privileged(["docker", "info"], capture=True)
                if os.geteuid() != 0:
                    self.prefix = ["sudo"]
            context = run([*self.prefix, "docker", "context", "inspect"], capture=True)
            endpoint = json.loads(context)[0]["Endpoints"]["docker"]["Host"]
            host = (
                endpoint
                if os.environ.get("DOCKER_CONTEXT")
                else os.environ.get("DOCKER_HOST", endpoint)
            )
            if host not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
                raise BridgeError("Android 실행에는 이 서버의 Docker Engine이 필요합니다. 현재 Docker 컨텍스트가 다른 곳을 가리키며 Bridge는 이를 바꾸지 않았습니다. DOCKER_HOST=unix:///var/run/docker.sock으로 다시 실행하세요.")

    def call(self, *arguments, capture=False, interactive=False):
        from ops.setup_output import bridge_command

        # Interactive children keep the terminal; quiet ones report through this process.
        command = bridge_command(*arguments) if not (capture or interactive) else [
            sys.executable, str(cli.ROOT / "bridge"), *arguments
        ]
        return run([*self.prefix, *command], capture=capture, interactive=interactive)

    def installed(self):
        if platform.system() != "Darwin":
            return (cli.ROOT / ".bridge/installed").exists()
        config_path = cli.ROOT / ".bridge/mac.json"
        if not config_path.exists():
            return False
        config = json.loads(config_path.read_text())
        instances = run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines()
        if config["vm"] not in instances:
            return False
        progress("가상 머신 시작 중…")
        run(["limactl", "start", "--tty=false", config["vm"]])
        try:
            run(
                [
                    "limactl",
                    "shell",
                    "--workdir=/",
                    config["vm"],
                    "sudo",
                    "test",
                    "-f",
                    config["directory"] + "/.bridge/installed",
                ],
                capture=True,
            )
            return True
        except RuntimeError:
            return False

    def wait_ready(self, timeout=240):
        progress("서비스 응답 확인 중…")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.call("doctor", capture=True)
                return
            except RuntimeError:
                time.sleep(3)
        # Keep the failing checks in the run log for diagnosis.
        with contextlib.suppress(RuntimeError, OSError):
            self.call("doctor")
        raise BridgeError("서비스 시작이 예상보다 오래 걸립니다. kakaotalk-bridge up을 다시 실행하거나 kakaotalk-bridge doctor로 상태를 확인하세요.")


def network_status(command):
    # Some Tailscale versions return a nonzero status while signed out, even
    # though stdout contains a valid NeedsLogin state. That is not a dead daemon.
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
    try:
        status = json.loads(result.stdout)
        if not isinstance(status, dict) or not status.get("BackendState"):
            raise ValueError("missing network state")
        return status
    except ValueError:
        raise BridgeError("보안 연결 서비스(Tailscale)가 응답하지 않습니다.") from None


def connect_network(args, runtime):
    if args.connection == "openai-tunnel":
        if args.tunnel_id:
            runtime.call(
                "tunnel",
                "configure",
                "--tunnel-id",
                args.tunnel_id,
                "--api-key-file",
                str(Path(args.api_key_file).resolve()),
            )
        return
    if args.public_url:
        runtime.call("connect", "--url", args.public_url, capture=True)
        return
    if args.connection != "tailscale":
        return
    tailscale = expose.tailscale_binary()
    if not tailscale:
        raise BridgeError("보안 연결 도구(Tailscale)가 설치되지 않았습니다. kakaotalk-bridge up을 다시 실행하세요.")
    prefix = ["sudo"] if platform.system() == "Linux" and os.geteuid() != 0 else []
    try:
        status = network_status([*prefix, tailscale, "status", "--json"])
    except (RuntimeError, subprocess.TimeoutExpired):
        if platform.system() == "Darwin" and "/Applications/" in tailscale:
            run(["open", "-a", "Tailscale"])
            raise BridgeError("macOS에서 Tailscale 활성화를 마친 뒤 kakaotalk-bridge up을 다시 실행하세요.") from None
        if platform.system() == "Darwin":
            privileged(["brew", "services", "start", "tailscale"])
        else:
            privileged(["systemctl", "start", "tailscaled"])
        status = network_status([*prefix, tailscale, "status", "--json"])
    if status.get("BackendState") != "Running":
        print(
            "브라우저에서 Tailscale에 로그인하세요. 최대 10분 동안 기다리는 중…",
            flush=True,
        )
        # Tailscale owns the login flow. Never save its one-time links in checkpoints/logs.
        command = [*prefix, tailscale, "up", "--timeout=10m"]
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        ) as proc:
            try:
                for line in proc.stdout:
                    for link in provider_line(line):
                        if not args.no_browser:
                            webbrowser.open(link)
                if proc.wait():
                    raise BridgeError("Tailscale 로그인이 끝나지 않았습니다. kakaotalk-bridge up을 다시 실행해 이어서 진행하세요.")
            except BaseException:
                proc.terminate()
                proc.wait()
                raise
    # Keep provider permission/HTTPS/Funnel approval links visible to the user.
    runtime.call("expose", interactive=True)


def open_setup(args, runtime):
    command = ["passkey-login", "--link-only"]
    if args.admin_url:
        command += ["--url", args.admin_url]
    if args.public_url:
        command += ["--public-url", args.public_url]
    link = runtime.call(*command, capture=True).strip()
    base, _, fragment = link.partition("#")
    access.private_url(base)
    if fragment and not re.fullmatch(r"passkey-setup=[A-Za-z0-9_-]{43}", fragment):
        raise BridgeError("패스키 등록 링크를 받지 못했습니다. kakaotalk-bridge passkey-login을 실행하세요.")
    if base.startswith("http://localhost:") and (
        args.no_browser or os.environ.get("SSH_CONNECTION")
    ):
        from urllib.parse import urlsplit

        port = urlsplit(base).port
        target = network_config().get("ADMIN_LOCAL_PORT") or "18789"
        print(
            f"\n사용할 컴퓨터에서 아래 SSH 포워딩을 실행한 상태로 두세요:\n"
            f"  ssh -N -L 127.0.0.1:{port}:127.0.0.1:{target} user@your-server\n"
            "그 컴퓨터에서 localhost 설정 링크를 여세요."
        )
    print("\n설정 화면을 여세요:\n" + link, flush=True)
    if not args.no_browser:
        webbrowser.open(link)


def up(args):
    validate(args)
    if args.plan:
        print("KakaoTalk Bridge · 설정 계획 (변경 없음)")
        print(
            "실행 환경: "
            + (
                "macOS의 전용 Ubuntu VM"
                if platform.system() == "Darwin"
                else "Android Binder를 사용하는 로컬 Linux Docker Engine"
            )
        )
        for index, (_, label) in enumerate(STEPS, 1):
            print(f"{index}. {label}")
        print("기존 설치와 로그인 정보를 재사용합니다. 업데이트는 kakaotalk-bridge upgrade로 실행합니다.")
        print(
            "연결: "
            + (args.connection or ("https" if args.public_url else "추가 없음 (기존 연결 유지)"))
        )
        print("관리 화면: 로컬 브라우저 또는 SSH 포워딩 사용, 기존 HTTPS 주소 유지")
        print(
            "AI: 나중에 kakaotalk-bridge setup-connection으로 stdio, 공개 HTTPS/OAuth 또는 OpenAI 터널 추가"
        )
        print("처음 사용하면 관리자 패스키 등록과 카카오톡 설치·로그인이 필요합니다.")
        return
    with installation_lock(), SetupOutput(verbose=args.verbose) as output:
        # First, so commands in later guidance and error messages already work.
        launcher.install()
        current = "environment"

        @contextlib.contextmanager
        def stage(key):
            nonlocal current
            current = key
            index, label = next(
                (i, label) for i, (name, label) in enumerate(STEPS, 1) if name == key
            )
            cli.atomic(
                cli.ROOT / ".bridge/onboarding.json", json.dumps({"step": key, "state": "running"})
            )
            with output.step(f"[{index}/{len(STEPS)}] {label}"):
                yield

        try:
            with stage("environment"):
                (prepare_mac if platform.system() == "Darwin" else prepare_linux)(args)
                runtime = Runtime()
            with stage("runtime"):
                if runtime.installed():
                    runtime.call("start")
                else:
                    release = Path(args.manifest) if args.manifest else cli.ROOT / "release.json"
                    if args.source:
                        selection = ["--source"]
                    elif release.is_file():
                        cli.manifest(release)
                        selection = ["--manifest", str(release.resolve())]
                    elif (cli.ROOT / releases.SOURCE_RECORD).is_file():
                        # A downloaded source installation keeps building its own images.
                        selection = ["--source"]
                    else:
                        raise BridgeError("릴리스 정보(release.json)가 없습니다. 공식 설치 명령을 사용하거나, 소스 빌드라면 --source를 지정하세요.")
                    ports = []
                    for name in ("admin_port", "mcp_port"):
                        if getattr(args, name) is not None:
                            ports += ["--" + name.replace("_", "-"), str(getattr(args, name))]
                    runtime.call("install", *selection, "--vm", args.vm, *ports)
                if args.apk_folder:
                    # Identical imports are resumable; different sets are never mixed.
                    progress("카카오톡 APK 세트 가져오는 중…")
                    runtime.call("import-apks", str(Path(args.apk_folder).resolve()))
                runtime.wait_ready()
            with stage("network"):
                connect_network(args, runtime)
                runtime.wait_ready()
                progress("웹 설정 서비스 준비 중…")
                runtime.call("setup-agent", "install")
            with stage("browser"):
                open_setup(args, runtime)
        except BaseException:
            cli.atomic(
                cli.ROOT / ".bridge/onboarding.json",
                json.dumps({"step": current, "state": "interrupted"}),
            )
            print(
                f"\n{dict(STEPS)[current]} 단계에서 중단되었습니다. 문제를 해결한 뒤 같은 명령으로 이어서 진행하세요. 데이터는 유지됩니다.",
                file=sys.stderr,
            )
            raise
        cli.atomic(
            cli.ROOT / ".bridge/onboarding.json", json.dumps({"step": "browser", "state": "ready"})
        )
        print(
            "\nBridge가 준비되었습니다. 브라우저에서 계속하세요. 다음에도 같은 명령을 실행하면 됩니다.\n"
            "AI 연결은 선택 사항입니다. 필요할 때 관리 화면의 ‘AI 연결’에서 추가하세요."
        )
