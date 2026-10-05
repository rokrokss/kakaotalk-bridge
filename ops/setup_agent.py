"""Finite connection setup over a root-only Unix socket; no shell or Docker API proxy."""

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from ops import cli, onboarding, tunnel
from server.connection_setup import validate

MAX_BODY = 4096
STEPS = {
    "tunnel": (
        "Starting the tunnel service",
        "Check the tunnel ID, runtime key permissions and server internet access, then retry.",
    ),
    "approval": (
        "Applying your tunnel approval",
        "Sign in to admin and check the tunnel approval, then retry.",
    ),
    "verify": (
        "Checking server services",
        "The server connection is not ready. Wait briefly and run Check server connection again.",
    ),
    "oauth": (
        "Configuring HTTPS and OAuth",
        "Check the HTTPS address and reverse proxy, then retry. Keep your existing admin address.",
    ),
    "tailscale": (
        "Preparing Tailscale",
        "Check Tailscale sign-in and Funnel permission, then retry.",
    ),
}


def progress(data, step):
    cli.atomic(
        cli.ROOT / ".bridge/web-setup-progress.json",
        json.dumps(
            {
                "id": data["request_id"],
                "step": step,
                "message": STEPS[step][0],
            }
        ),
    )


def current_progress(identity):
    path = cli.ROOT / ".bridge/web-setup-progress.json"
    value = json.loads(path.read_text()) if path.exists() else {}
    return value if value.get("id") == identity and value.get("step") in STEPS else {}


class ActionRequired(Exception):
    def __init__(self, url):
        self.url = url


def socket_dir():
    return cli.ROOT / ".bridge/setup-agent"


def context():
    values = cli.read_env()
    saved = cli.ROOT / ".bridge/stdio-client.json"
    stdio = (
        json.loads(saved.read_text())
        if saved.exists()
        else {"command": sys.executable, "args": [str(cli.ROOT / "bridge"), "mcp"]}
    )
    public = values.get("DOT_PUBLIC_URL", "")
    preferences = cli.ROOT / ".bridge/connection-preferences.json"
    preferred = json.loads(preferences.read_text()).get("method") if preferences.exists() else None
    return {
        "available": True,
        "mcp_url": public + "/mcp" if public and not public.endswith(".invalid") else "",
        "tunnel_id": values.get("OPENAI_TUNNEL_ID", ""),
        "tunnel_configured": values.get("OPENAI_TUNNEL_ENABLED") == "1",
        "runtime_key_saved": (cli.ROOT / "secrets/openai_tunnel_api_key").is_file(),
        "stdio": {"mcpServers": {"kakaotalk": stdio}},
        "server_stdio": {"command": sys.executable, "args": [str(cli.ROOT / "bridge"), "mcp"]},
        "managed_vm": saved.exists(),
        "preferred_method": preferred
        or (
            "openai-tunnel"
            if values.get("OPENAI_TUNNEL_ENABLED") == "1"
            else "https"
            if public and not public.endswith(".invalid")
            else "none"
        ),
    }


def quiet_run(args, *, capture=False, **kwargs):
    """No subprocess output reaches logs or the browser, including provider login links."""
    kwargs.setdefault("timeout", 30 if "tailscale" in Path(args[0]).name else 600)
    try:
        result = subprocess.run(
            args, cwd=cli.ROOT, text=True, capture_output=True, check=False, **kwargs
        )
        output = result.stdout + "\n" + result.stderr
        failed = result.returncode != 0
    except subprocess.TimeoutExpired as exc:
        parts = [exc.stdout or "", exc.stderr or ""]
        output = "\n".join(
            p.decode("utf-8", errors="replace") if isinstance(p, bytes) else p for p in parts
        )
        failed = True
    if failed:
        if "tailscale" in Path(args[0]).name:
            match = re.search(r"https://login\.tailscale\.com/[A-Za-z0-9/_?=&.%+-]+", output)
            if match:
                raise ActionRequired(match.group())
        raise RuntimeError(f"Command failed: {Path(args[0]).name}")
    return result.stdout.strip() if capture else ""


def configure_oauth(url):
    cli.connect(url)
    if cli.read_env().get("ADMIN_AUTH_MODE", "passkey") == "passkey":
        cli.passkey_setup(
            argparse.Namespace(local=True, url=None, public_url=url, enroll=False, link_only=True)
        )
    else:
        # Preserve explicit legacy local admin login instead of changing its identity.
        cli.env_update({"DOT_APPROVAL_MODE": "admin"})
        cli.compose("up", "-d", "--no-build", "--no-deps", "dot-control", "dot-plugin")


def execute(data):
    data = validate(data)
    method = data["method"]
    if method in {"none", "stdio"}:
        return {
            "state": "ready",
            "message": "Existing connections kept."
            if method == "none"
            else "Copy the configuration into your AI client.",
        }
    if method == "check":
        progress(data, "verify")
        result = tunnel.status()
        public = context()["mcp_url"]
        if public:
            cli.compose(
                "exec",
                "-T",
                "dot-plugin",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health/live',timeout=3)",
                capture=True,
            )
        if result["configured"] and not result["ready"]:
            raise RuntimeError("Tunnel is not ready")
        if not public and not result["configured"]:
            return {
                "state": "ready",
                "message": "No public or tunnel connection is configured. Choose a method above, or use stdio with your local client.",
            }
        return {
            "state": "ready",
            "message": "Server checks passed. Ask your AI for collector status to verify the complete connection.",
            "tunnel_ready": result["ready"],
        }
    with onboarding.installation_lock():
        if method == "openai-tunnel":
            progress(data, "tunnel")
            key = data.get("api_key", "")
            if not key:
                if cli.read_env().get("OPENAI_TUNNEL_ID") != data["tunnel_id"]:
                    raise ValueError("Enter a runtime key for the new tunnel ID.")
                saved = cli.ROOT / "secrets/openai_tunnel_api_key"
                if not saved.is_file():
                    raise ValueError("Enter the runtime API key from OpenAI.")
                key = saved.read_text().strip()
            with tempfile.TemporaryDirectory(prefix="bridge-web-key-") as folder:
                path = Path(folder) / "key"
                cli.atomic(path, key + "\n")
                tunnel.configure(data["tunnel_id"], path)
            progress(data, "approval")
            tunnel.control_call(
                "/tunnel/decision", {"tunnel_id": data["tunnel_id"], "approve": True}
            )
            progress(data, "verify")
            if not tunnel.status()["ready"]:
                raise RuntimeError("Tunnel is not ready")
            return {
                "state": "ready",
                "message": "Tunnel is ready and approved. Add it in ChatGPT to finish.",
                "tunnel_ready": True,
            }
        if method == "https":
            progress(data, "oauth")
            configure_oauth(data["url"])
        elif method == "tailscale":
            progress(data, "tailscale")
            if not cli.tailscale_binary():
                onboarding.install_script("https://tailscale.com/install.sh")
            cli.run(["systemctl", "start", "tailscaled"])
            binary = cli.tailscale_binary()
            if not binary:
                raise RuntimeError("Tailscale installation did not finish")
            status = onboarding.network_status([binary, "status", "--json"])
            if status["BackendState"] != "Running":
                cli.run([binary, "up", "--timeout=15s"], timeout=30)
            cli.expose(argparse.Namespace(local=True))
            progress(data, "oauth")
            configure_oauth(cli.read_env()["DOT_PUBLIC_URL"])
        return {
            "state": "ready",
            "message": "OAuth services are configured. Add the MCP URL in your AI client and approve the connection.",
        }


def job_main():
    data = {}
    try:
        body = sys.stdin.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise ValueError("Request too large")
        data = validate(json.loads(body))
        cli.run = quiet_run
        with contextlib.redirect_stdout(io.StringIO()):
            result = execute(data)
    except ActionRequired as exc:
        result = {
            "state": "action_required",
            "message": "Complete Tailscale approval, then choose Continue setup.",
            "action_url": exc.url,
        }
    except ValueError:
        # All ValueErrors from the request contract are fixed messages, but downstream
        # parsers may contain private data. Never return their raw errors.
        result = {
            "state": "failed",
            "message": "Check the address, tunnel ID and runtime key, then retry.",
        }
    except Exception:  # noqa: BLE001 - the worker must never print provider errors or secrets
        step = current_progress(data.get("request_id")).get("step")
        result = {
            "state": "failed",
            "step": step,
            "message": STEPS[step][1]
            if step
            else "Setup stopped. Check the settings and retry. If it repeats, run bridge doctor on the server.",
        }
    print(json.dumps(result))


class Jobs:
    def __init__(self, runner=None):
        self.lock = threading.Lock()
        self.runner = runner or self.run_child
        self.path = cli.ROOT / ".bridge/web-setup.json"
        self.job = json.loads(self.path.read_text()) if self.path.exists() else {"state": "idle"}
        if self.job["state"] in {"running", "action_required"}:
            self.job.update(
                {
                    "state": "interrupted",
                    "message": "Setup was interrupted. Review the connection and retry.",
                }
            )
        self.thread = None

    @staticmethod
    def run_child(data):
        with subprocess.Popen(
            [sys.executable, str(cli.ROOT / "bridge"), "--local", "setup-agent", "job"],
            stdin=subprocess.PIPE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cli.ROOT,
            start_new_session=True,
        ) as child:
            try:
                output, _ = child.communicate(json.dumps(data), timeout=900)
            except subprocess.TimeoutExpired:
                # Stop descendants too: a timed-out Docker command must not mutate
                # the installation concurrently with a subsequent setup attempt.
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise
            if child.returncode:
                raise RuntimeError("Setup worker stopped")
        return json.loads(output)

    def snapshot(self):
        with self.lock:
            job = dict(self.job)
            if job.get("state") == "running":
                job.update(current_progress(job.get("id")))
            return {"job": job, **context()}

    def submit(self, data):
        data = validate(data)
        with self.lock:
            if self.job.get("id") == data["request_id"]:
                return dict(self.job)
            if self.job["state"] == "running":
                raise BlockingIOError("Another connection setup is running.")
            self.job = {
                "id": data["request_id"],
                "method": data["method"],
                "state": "running",
                "message": "Preparing connection services…",
                "started_at": time.time(),
            }
            cli.atomic(self.path, json.dumps(self.job))
            self.thread = threading.Thread(target=self.finish, args=(data,), daemon=True)
            self.thread.start()
            return dict(self.job)

    def finish(self, data):
        try:
            result = self.runner(data)
        except Exception:  # noqa: BLE001 - do not persist or return exception text containing secrets
            result = {
                "state": "failed",
                "message": "Setup stopped before completion. Check connection status and retry.",
            }
        with self.lock:
            self.job.update(result)
            self.job["finished_at"] = time.time()
            if result.get("state") == "ready" and data["method"] != "check":
                cli.atomic(
                    cli.ROOT / ".bridge/connection-preferences.json",
                    json.dumps({"method": data["method"]}),
                )
            # Runtime keys never enter job state. Provider login links stay in memory.
            saved = {k: v for k, v in self.job.items() if k != "action_url"}
            cli.atomic(self.path, json.dumps(saved))


def serve():
    folder = socket_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    lock = (folder / "agent.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = folder / "agent.sock"
    path.unlink(missing_ok=True)
    jobs = Jobs()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def reply(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/status":
                return self.reply(404, {"detail": "not_found"})
            self.reply(200, jobs.snapshot())

        def do_POST(self):
            if self.path != "/jobs":
                return self.reply(404, {"detail": "not_found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 0 < length <= MAX_BODY
                    or self.headers.get("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length", [])) != 1
                ):
                    return self.reply(413, {"detail": "invalid_request_size"})
                body = json.loads(self.rfile.read(length))
                self.reply(202, jobs.submit(body))
            except (ValueError, TypeError):
                self.reply(400, {"detail": "invalid_setup_request"})
            except BlockingIOError:
                self.reply(409, {"detail": "setup_running"})

    with socketserver.UnixStreamServer(str(path), Handler) as server:
        path.chmod(0o600)
        try:
            server.serve_forever()
        finally:
            path.unlink(missing_ok=True)
            lock.close()


def install():
    if os.geteuid() != 0:
        cli.run(
            ["sudo", sys.executable, str(cli.ROOT / "bridge"), "--local", "setup-agent", "install"]
        )
        return
    if not shutil.which("systemctl") or not Path("/run/systemd/system").is_dir():
        print(
            "Web connection setup needs a running setup agent. Run bridge setup-agent serve under your service manager."
        )
        return
    folder = socket_dir()
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    identity = hashlib.sha256(str(cli.ROOT).encode()).hexdigest()[:12]
    unit = "kakaotalk-setup-" + identity + ".service"

    def quote(value):
        if any(c in value for c in "\n\r\0"):
            raise ValueError("Invalid service path")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'

    content = (
        "[Unit]\nDescription=KakaoTalk Bridge connection setup\nAfter=docker.service\n"
        # Paths are absolute; workers and CLI subprocesses set cwd explicitly.
        "[Service]\nType=simple\n"
        "ExecStart="
        + quote(sys.executable).replace("$", "$$")
        + " "
        + quote(str(cli.ROOT / "bridge")).replace("$", "$$")
        + " --local setup-agent serve\n"
        "Restart=on-failure\nRestartSec=3\nUMask=0077\nKillMode=control-group\n"
        "StandardOutput=null\nStandardError=null\n[Install]\nWantedBy=multi-user.target\n"
    )
    target = Path("/etc/systemd/system") / unit
    changed = not target.exists() or target.read_text() != content
    if changed:
        cli.atomic(target, content)
        cli.run(["systemctl", "daemon-reload"], capture=True)
    cli.run(["systemctl", "enable", "--now", unit], capture=True)
    # Reload Python source on repeated up/upgrade, including unchanged unit files.
    cli.run(["systemctl", "restart", unit], capture=True)
    print("Web connection setup service is ready.")
