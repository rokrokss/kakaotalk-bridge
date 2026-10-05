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
from ops.setup_output import SetupOutput, run

STEPS = (
    ("environment", "Preparing the execution environment"),
    ("runtime", "Starting your private bridge"),
    ("network", "Preparing optional AI connections"),
    ("browser", "Opening KakaoTalk setup"),
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
    mode.add_argument("--source", action="store_true", help="Build this checkout")
    mode.add_argument("--manifest", help="Use a verified release manifest")
    parser.add_argument("--plan", action="store_true", help="Show steps without changing anything")
    parser.add_argument("--verbose", action="store_true", help="Show detailed installation output")
    parser.add_argument(
        "--no-install", action="store_true", help="Do not install host dependencies"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Print links for a remote browser"
    )
    parser.add_argument("--vm", default="kakaotalk-bridge")
    parser.add_argument(
        "--admin-port", type=int, help="Internal maintenance port; Mac selects a free port"
    )
    parser.add_argument(
        "--mcp-port", type=int, help="Local shared ingress port; Mac selects a free port"
    )
    parser.add_argument("--apk-folder", help="Import your official APK set on first setup")
    parser.add_argument("--url", help="Shared HTTPS origin for an existing reverse proxy")
    parser.add_argument(
        "--admin-url", help="Admin HTTPS origin or http://localhost:<port> (advanced)"
    )
    parser.add_argument("--public-url", help="Public MCP HTTPS origin for an existing proxy")
    parser.add_argument(
        "--connection",
        choices=("none", "tailscale", "https", "openai-tunnel"),
        help="Optional AI connection; default keeps existing connections and adds none",
    )
    parser.add_argument("--tunnel-id", help="Personal OpenAI tunnel ID (first configuration)")
    parser.add_argument("--api-key-file", help="Private file containing the tunnel runtime API key")


def validate(args):
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
    print(f"Installing {description}. Your OS may request administrator approval.", flush=True)


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
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh", interactive=True
            )
        run(["brew", "install", "lima"])
    if platform.machine() == "x86_64" and not shutil.which("qemu-system-x86_64"):
        require_install(args, "the Intel Mac virtual machine driver")
        if not shutil.which("brew"):
            install_script(
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh", interactive=True
            )
        run(["brew", "install", "qemu"])
    if args.connection == "tailscale" and not cli.tailscale_binary():
        require_install(args, "Tailscale for your secure browser connection")
        if not shutil.which("brew"):
            install_script(
                "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh", interactive=True
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
        privileged(["systemctl", "start", "docker"])
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
            "Sign in to the secure connection service in your browser. Waiting up to 10 minutes…",
            flush=True,
        )
        # Tailscale owns the login flow. Never save its one-time links in checkpoints/logs.
        command = [*prefix, tailscale, "up", "--timeout=10m"]
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        ) as proc:
            try:
                for line in proc.stdout:
                    print(line, end="", flush=True)
                    match = re.search(r"https://login\.tailscale\.com/[A-Za-z0-9/_?=&.-]+", line)
                    if match and not args.no_browser:
                        webbrowser.open(match.group())
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
            f"\nOn your computer, keep this SSH forwarding session open:\n"
            f"  ssh -N -L 127.0.0.1:{port}:127.0.0.1:{target} user@your-server\n"
            "Then open the localhost setup link on that computer."
        )
    print("\nOpen your setup page:\n" + link, flush=True)
    if not args.no_browser:
        webbrowser.open(link)


def up(args):
    validate(args)
    if args.plan:
        print("KakaoTalk Bridge · setup plan (no changes)")
        print(
            "Runtime: "
            + (
                "private Ubuntu VM on macOS"
                if platform.system() == "Darwin"
                else "local Linux Docker Engine with Android Binder"
            )
        )
        for index, (_, label) in enumerate(STEPS, 1):
            print(f"{index}. {label}")
        print(
            "Existing installation and login data are reused; images change only with bridge update."
        )
        print(
            "Connection: "
            + (args.connection or ("https" if args.public_url else "none (reuse existing)"))
        )
        print("Admin: local browser or SSH forwarding; an existing HTTPS address is reused.")
        print(
            "AI: add stdio, public HTTPS/OAuth or an OpenAI tunnel later with bridge setup-connection."
        )
        print("First use requires an admin passkey and KakaoTalk installation/login.")
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
                    selection = (
                        ["--manifest", str(Path(args.manifest).resolve())]
                        if args.manifest
                        else ["--source"]
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
                f"\nStopped during {current}. Run the same command to continue; your data is preserved.",
                file=sys.stderr,
            )
            if output.path:
                print(f"Details: {output.path}", file=sys.stderr)
            raise
        cli.atomic(
            cli.ROOT / ".bridge/onboarding.json", json.dumps({"step": "browser", "state": "ready"})
        )
        print(
            "\nBridge is ready. Continue in your browser. Next time, run the same command.\n"
            "AI connections are optional: choose Connect your AI in admin when ready."
        )
