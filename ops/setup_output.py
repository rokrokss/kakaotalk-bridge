"""Concise installer output: Korean progress on screen, tool output in one private log.

Child Bridge processes, including those inside the Lima VM, send their progress and
errors to the parent as marked stdout lines. Everything else they print goes to the
parent's log, so one run has one log and one progress display.
"""

import contextlib
import contextvars
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from ops import cli
from ops.errors import BridgeError

_current = contextvars.ContextVar("setup_output", default=None)
HEARTBEAT_SECONDS = 30
MARK = "@@kakaotalk-bridge@@ "
# Set for child Bridge processes so they report through MARK lines.
CHILD = "BRIDGE_PROGRESS"
# Set when the person asked for raw output; children then skip their own logs.
RAW = "BRIDGE_RAW_OUTPUT"
GENERIC = "작업을 완료하지 못했습니다. 입력값과 실행 환경을 확인한 뒤 다시 시도하세요."


def child():
    return os.environ.get(CHILD) == "1"


def relaying():
    """Whether child commands should report progress instead of printing to the screen."""
    output = _current.get()
    return child() or bool(output and output.log)


def raw():
    output = _current.get()
    return os.environ.get(RAW) == "1" or bool(output and output.verbose)


def bridge_command(*arguments, entry=None):
    """A child Bridge command that reports through this process when it is relaying."""
    entry = entry or [sys.executable, str(cli.ROOT / "bridge")]
    flags = ["--progress"] if relaying() else ["--raw-output"] if raw() else []
    return [*entry, *flags, *arguments]


def _emit(**message):
    print(MARK + json.dumps(message, ensure_ascii=False), flush=True)


def progress(text):
    """A short Korean status line for the person running Bridge."""
    if child():
        _emit(progress=text)
        return
    output = _current.get()
    if output:
        output.substep(text)
    else:
        print(text, flush=True)


def notice(text):
    """Guidance the person must see, even when a child command prints it."""
    if child():
        _emit(notice=text)
    else:
        print(text, flush=True)


def _relay(line, state):
    try:
        message = json.loads(line[len(MARK) :])
    except ValueError:
        return False
    if "progress" in message:
        progress(message["progress"])
    elif "notice" in message:
        notice(message["notice"])
    elif "error" in message:
        # The innermost failing command reports first and knows the actual cause.
        state.setdefault("error", message["error"])
    return True


def stream(command, log, **kwargs):
    """Run a child with its output in the log, relaying its marked progress and errors."""
    if "input" in kwargs or "timeout" in kwargs:
        # Small helper commands; they do not report progress.
        result = subprocess.run(
            command,
            cwd=cli.ROOT,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            **kwargs,
        )
        code = result.returncode
        state = {}
    else:
        state = {}
        with subprocess.Popen(
            command,
            cwd=cli.ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        ) as process:
            try:
                for line in process.stdout:
                    if not (line.startswith(MARK) and _relay(line, state)):
                        log.write(line)
                code = process.wait()
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                raise
            finally:
                log.flush()
    if code:
        if state.get("error"):
            raise BridgeError(state["error"])
        raise RuntimeError(f"Command failed: {Path(command[0]).name} (exit {code})")
    return ""


def log_target(capture, kwargs):
    """The run log for a quiet command, or None to leave its streams as they are."""
    output = _current.get()
    if output and output.log and not capture and "stdout" not in kwargs and "stderr" not in kwargs:
        return output.log
    return None


def log_failure(command, result):
    """Captured output stays private, but a failed command's errors belong in the log."""
    output = _current.get()
    if output and output.log and result.stderr:
        output.log.write(f"\n$ {Path(command[0]).name} failed (exit {result.returncode})\n")
        output.log.write(result.stderr)
        output.log.flush()


def run(command, *, capture=False, interactive=False):
    if interactive:
        # Native installers may need to show their own consent/password prompts.
        with interaction():
            print(
                "외부 설치 프로그램의 확인을 기다리는 중입니다. 아래 안내에 따라 진행하세요.",
                flush=True,
            )
            token = _current.set(None)
            try:
                return cli.run(command, capture=capture)
            finally:
                _current.reset(token)
    return cli.run(command, capture=capture)


@contextlib.contextmanager
def interaction():
    """Pause elapsed-time messages while the person answers a prompt."""
    output = _current.get()
    if output:
        output.paused.set()
    try:
        yield
    finally:
        if output:
            output.paused.clear()


def report_error(error):
    """Show Korean guidance; keep internal exception text in the private log."""
    message = str(error) if isinstance(error, BridgeError) and str(error) else GENERIC
    detail = (
        "".join(traceback.format_exception(error))
        if not isinstance(error, (BridgeError, RuntimeError, ValueError, OSError))
        else f"{type(error).__name__}: {error}\n"
    )
    if child():
        # The parent keeps stdout and stderr in its log and shows only the marked message.
        sys.stderr.write(detail)
        sys.stderr.flush()
        _emit(error=message)
        return
    path = getattr(error, "setup_log_path", None)
    if path:
        try:
            with open(path, "a") as log:
                log.write(detail)
        except OSError:
            pass
    else:
        try:
            folder = cli.ROOT / ".bridge/logs"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, path = tempfile.mkstemp(prefix="error-", suffix=".log", dir=folder)
            with os.fdopen(descriptor, "w") as log:
                log.write(detail)
        except OSError:
            path = None
    print(message, file=sys.stderr)
    if path:
        print(f"진단 로그: {path}", file=sys.stderr)


def provider_line(line):
    """Expose only trusted approval URLs; never persist provider sign-in links."""
    import re

    links = re.findall(r"https://login\.tailscale\.com/[A-Za-z0-9/_?=&.%+-]+", line)
    if links:
        for link in links:
            print(f"Tailscale 로그인·승인 페이지를 여세요: {link}", flush=True)
    else:
        output = _current.get()
        if output and output.log:
            output.log.write(line)
            output.log.flush()
    return links


def provider_command(command):
    """Translate progress while allowing Tailscale's approval URL to remain live."""
    print("Tailscale 연결 설정 중… 승인이 필요하면 아래 링크를 여세요.", flush=True)
    with subprocess.Popen(
        command, cwd=cli.ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    ) as process:
        try:
            for line in process.stdout:
                provider_line(line)
            if process.wait():
                raise RuntimeError(f"Tailscale setup failed (exit {process.returncode})")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait()
            raise
    return ""


LABELS = {
    "install": "Bridge 설치",
    "update": "Bridge 업데이트",
    "upgrade": "Bridge 업데이트",
    "start": "서비스 시작",
    "stop": "서비스 중지",
    "setup-connection": "AI 연결 설정",
    "connect": "HTTPS 연결 설정",
    "expose": "외부 접속 설정",
    "backup": "백업 생성",
    "restore": "백업 복구",
    "import-apks": "APK 가져오기",
    "passkey-login": "패스키 설정",
    "tunnel": "터널 설정",
    "setup-agent": "웹 설정 서비스 준비",
    "admin": "관리 화면 준비",
    "reset-password": "관리자 비밀번호 초기화",
}


@contextlib.contextmanager
def operation(args):
    internal = (
        args.local
        or child()
        or os.environ.get(RAW) == "1"
        or any(getattr(args, key, False) for key in ("link_only", "code_only", "info"))
        or getattr(args, "tunnel_command", None) == "status"
        or getattr(args, "agent_command", None) in {"serve", "job"}
    )
    if internal or args.command not in LABELS:
        yield
        return
    with SetupOutput() as output, output.step(LABELS[args.command]):
        yield


class SetupOutput:
    def __init__(self, *, verbose=False):
        self.verbose = verbose
        self.log = None
        self.path = None
        self.paused = threading.Event()
        self.current = None

    def __enter__(self):
        if not self.verbose:
            folder = cli.ROOT / ".bridge/logs"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, path = tempfile.mkstemp(prefix="setup-", suffix=".log", dir=folder)
            self.path = Path(path)
            self.log = os.fdopen(descriptor, "w")
        self.token = _current.set(self)
        return self

    def __exit__(self, exc_type, error, traceback):
        _current.reset(self.token)
        if self.log:
            if error:
                self.log.write(f"\n{exc_type.__name__}: {error}\n")
                with contextlib.suppress(AttributeError):
                    error.setup_log_path = self.path
            self.log.close()

    def _write(self, text):
        if self.log:
            self.log.write(f"\n[{time.strftime('%H:%M:%S')}] {text}\n")
            self.log.flush()

    def substep(self, text):
        self.current = (text, time.monotonic())
        print(f"  · {text}", flush=True)
        self._write(text)

    def _heartbeat(self, stopped, label, started):
        while not stopped.wait(HEARTBEAT_SECONDS):
            if self.paused.is_set():
                continue
            text, since = self.current or (label, started)
            prefix = "  · " if self.current else ""
            base = text.removesuffix("…").removesuffix(" 중")
            elapsed = int(time.monotonic() - since)
            print(f"{prefix}{base} 중… {elapsed // 60}분 {elapsed % 60}초 경과", flush=True)

    @contextlib.contextmanager
    def step(self, label):
        print(f"{label} 중…", flush=True)
        self._write(f"▶ {label}")
        self.current = None
        stopped = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat, args=(stopped, label, time.monotonic()), daemon=True
        )
        heartbeat.start()
        try:
            yield
        finally:
            stopped.set()
            heartbeat.join()
            self.current = None
        print(f"{label} 완료", flush=True)
        self._write(f"✓ {label}")
