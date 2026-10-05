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

from ops import cli
from ops.setup_output import SetupOutput, provider_line, run

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
            raise ValueError(
                "Use --admin-url for private tunnel setup; configure public HTTPS separately"
            )
        saved = cli.ROOT / ".bridge/admin-url"
        if not args.admin_url and saved.exists() and os.access(saved, os.R_OK):
            args.admin_url = saved.read_text().strip().removesuffix("/admin/")
        if args.admin_url:
            cli.private_url(args.admin_url)
        if bool(args.tunnel_id) != bool(args.api_key_file):
            raise ValueError("Supply both --tunnel-id and --api-key-file")
        if args.tunnel_id:
            from ops.tunnel import credentials

            credentials(args.tunnel_id, args.api_key_file)
        elif not saved_tunnel and not args.plan:
            raise ValueError("First tunnel setup needs --tunnel-id and --api-key-file")
    elif args.tunnel_id or args.api_key_file:
        raise ValueError("Tunnel credentials require --connection openai-tunnel")
    if args.connection == "https" and not (args.url or args.public_url):
        raise ValueError("Supply --url or --public-url for an existing HTTPS proxy")
    if args.connection == "tailscale" and (args.url or args.admin_url or args.public_url):
        raise ValueError("Use either Tailscale or existing HTTPS proxy options")
    if platform.system() not in {"Darwin", "Linux"}:
        raise RuntimeError(
            "Local execution needs macOS or a Linux kernel with Android Binder. "
            "On Windows use install.ps1 with -Remote user@linux-host, or a Binder-enabled WSL2 "
            "distribution. Stock WSL2 and Docker Desktop are not verified Android hosts."
        )
    if platform.machine().lower() not in {"aarch64", "arm64", "x86_64", "amd64"}:
        raise RuntimeError("This release needs an arm64 or x86_64 machine.")
    if args.url:
        if args.admin_url or args.public_url:
            raise ValueError("Use --url alone, or the --admin-url/--public-url pair.")
        cli.validate_public_url(args.url)
        args.admin_url = args.public_url = args.url
    if args.connection == "none" and (args.url or args.public_url):
        raise ValueError("--connection none cannot configure a public MCP address")
    if args.admin_url:
        cli.private_url(args.admin_url)
    if args.public_url:
        cli.validate_public_url(args.public_url)
    for port in (args.admin_port, args.mcp_port):
        if port is not None and not 1024 <= port <= 65535:
            raise ValueError("Choose ports between 1024 and 65535.")
    if args.admin_port is not None and args.admin_port == args.mcp_port:
        raise ValueError("The internal maintenance and shared ingress ports must differ.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,48}", args.vm):
        raise ValueError("Invalid VM name")
    if args.manifest:
        cli.manifest(args.manifest)
    if args.apk_folder and not list(Path(args.apk_folder).glob("*.apk")):
        raise ValueError("The APK folder must contain your official KakaoTalk APK set.")


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
            raise RuntimeError("Setup is already running for this installation.") from None
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
        raise RuntimeError("Dependency installer was unexpectedly large.")
    with tempfile.TemporaryDirectory() as folder:
        script = Path(folder) / "install.sh"
        script.write_bytes(content)
        run(["/bin/bash", str(script)], interactive=interactive)


def require_install(args, description):
    if args.no_install:
        raise RuntimeError(f"Missing {description}. Install it or rerun without --no-install.")
    label = {
        "the Mac execution environment": "Mac 실행 환경",
        "the Intel Mac virtual machine driver": "Intel Mac 가상 머신 드라이버",
        "Tailscale for your secure browser connection": "보안 연결용 Tailscale",
        "Docker Engine and Compose": "Docker Engine 및 Compose",
        "Linux runtime packages": "Linux 실행 패키지",
    }.get(description, "필수 구성 요소")
    print(f"{label} 설치 중… 운영체제에서 관리자 승인을 요청할 수 있습니다.", flush=True)


def prepare_mac(args):
    if os.geteuid() == 0:
        raise RuntimeError("Run Bridge as your normal Mac user, without sudo.")
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
    if args.connection == "tailscale" and not cli.tailscale_binary():
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
        raise RuntimeError(
            "This WSL kernel has no Android Binder support. No changes were made. "
            "Use install.ps1 -Remote user@linux-host, or configure a Binder-enabled WSL2 kernel. "
            "Bridge does not replace the shared WSL kernel automatically."
        )
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
                raise RuntimeError(
                    "Install the Compose v2 plugin for your existing Docker Engine, then rerun. Existing Docker was preserved."
                ) from None
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
            raise RuntimeError(
                "Automatic package installation supports Ubuntu/Debian. On this distribution, "
                "install Docker Engine, Compose v2, OpenSSL and Android Binder, then rerun."
            )
        privileged(["apt-get", "update"])
        privileged(["apt-get", "install", "-y", *packages])
    if not binder_ready():
        try:
            privileged(["modprobe", "binder_linux", "devices=binder,hwbinder,vndbinder"])
        except (OSError, RuntimeError):
            raise RuntimeError(
                "Your kernel does not provide Android Binder. Use an Ubuntu VM with "
                "linux-modules-extra installed, or a compatible dedicated Linux host."
            ) from None
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
    if args.connection == "tailscale" and not cli.tailscale_binary():
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
                raise RuntimeError(
                    "Use the local system Docker Engine for Android. Your Docker context points "
                    "elsewhere; Bridge has not changed it. Rerun with DOCKER_HOST=unix:///var/run/docker.sock."
                )

    def call(self, *arguments, capture=False, interactive=False):
        return run(
            [*self.prefix, sys.executable, str(cli.ROOT / "bridge"), *arguments],
            capture=capture,
            interactive=interactive,
        )

    def installed(self):
        if platform.system() != "Darwin":
            return (cli.ROOT / ".bridge/installed").exists()
        config_path = cli.ROOT / ".bridge/mac.json"
        if not config_path.exists():
            return False
        config = json.loads(config_path.read_text())
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
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.call("doctor", capture=True)
                return
            except RuntimeError:
                time.sleep(3)
        raise RuntimeError(
            "Startup is taking longer than expected. Rerun bridge up to retry, or bridge doctor for details."
        )


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
        raise RuntimeError("The secure connection service is not responding.") from None


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
    tailscale = cli.tailscale_binary()
    if not tailscale:
        raise RuntimeError(
            "The secure connection tool was not installed. Rerun bridge up to retry."
        )
    prefix = ["sudo"] if platform.system() == "Linux" and os.geteuid() != 0 else []
    try:
        status = network_status([*prefix, tailscale, "status", "--json"])
    except (RuntimeError, subprocess.TimeoutExpired):
        if platform.system() == "Darwin" and "/Applications/" in tailscale:
            run(["open", "-a", "Tailscale"])
            raise RuntimeError(
                "Finish enabling Tailscale in macOS, then run bridge up again."
            ) from None
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
                    raise RuntimeError(
                        "Secure connection sign-in did not finish. Rerun bridge up to continue."
                    )
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
    cli.private_url(base)
    if fragment and not re.fullmatch(r"passkey-setup=[A-Za-z0-9_-]{43}", fragment):
        raise RuntimeError("Unexpected registration response; run bridge passkey-login.")
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
        print("기존 설치와 로그인 정보를 재사용합니다. 릴리스 업데이트는 bridge upgrade로 실행합니다.")
        print(
            "연결: "
            + (args.connection or ("https" if args.public_url else "추가 없음 (기존 연결 유지)"))
        )
        print("관리 화면: 로컬 브라우저 또는 SSH 포워딩 사용, 기존 HTTPS 주소 유지")
        print(
            "AI: 나중에 bridge setup-connection으로 stdio, 공개 HTTPS/OAuth 또는 OpenAI 터널 추가"
        )
        print("처음 사용하면 관리자 패스키 등록과 카카오톡 설치·로그인이 필요합니다.")
        return
    with installation_lock(), SetupOutput(verbose=args.verbose) as output:
        current = "environment"

        @contextlib.contextmanager
        def progress(key):
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
            with progress("environment"):
                (prepare_mac if platform.system() == "Darwin" else prepare_linux)(args)
                runtime = Runtime()
            with progress("runtime"):
                if runtime.installed():
                    runtime.call("start")
                else:
                    release = Path(args.manifest) if args.manifest else cli.ROOT / "release.json"
                    if args.source:
                        selection = ["--source"]
                    elif release.is_file():
                        cli.manifest(release)
                        selection = ["--manifest", str(release.resolve())]
                    else:
                        print(
                            "릴리스 설치 파일이 없습니다. 공식 설치 명령 또는 --source를 사용하세요.",
                            file=sys.stderr,
                        )
                        raise RuntimeError(
                            "No release manifest; source builds require explicit --source"
                        )
                    ports = []
                    for name in ("admin_port", "mcp_port"):
                        if getattr(args, name) is not None:
                            ports += ["--" + name.replace("_", "-"), str(getattr(args, name))]
                    runtime.call("install", *selection, "--vm", args.vm, *ports)
                if args.apk_folder:
                    # Identical imports are resumable; different sets are never mixed.
                    runtime.call("import-apks", str(Path(args.apk_folder).resolve()))
                runtime.wait_ready()
            with progress("network"):
                connect_network(args, runtime)
                runtime.wait_ready()
                runtime.call("setup-agent", "install")
            with progress("browser"):
                open_setup(args, runtime)
        except BaseException:
            cli.atomic(
                cli.ROOT / ".bridge/onboarding.json",
                json.dumps({"step": current, "state": "interrupted"}),
            )
            print(
                f"\n{dict(STEPS)[current]} 단계에서 중단되었습니다. 같은 명령으로 이어서 진행하세요. 데이터는 유지됩니다.",
                file=sys.stderr,
            )
            if output.path:
                print(f"진단 로그: {output.path}", file=sys.stderr)
            raise
        cli.atomic(
            cli.ROOT / ".bridge/onboarding.json", json.dumps({"step": "browser", "state": "ready"})
        )
        print(
            "\nBridge가 준비되었습니다. 브라우저에서 계속하세요. 다음에도 같은 명령을 실행하면 됩니다.\n"
            "AI 연결은 선택 사항입니다. 필요할 때 관리 화면의 ‘AI 연결’에서 추가하세요."
        )
