"""Concise installer output; captured values and interactive prompts stay private/live."""

import contextlib
import contextvars
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ops import cli

_current = contextvars.ContextVar("setup_output", default=None)
HEARTBEAT_SECONDS = 30


def run(command, *, capture=False, interactive=False):
    output = _current.get()
    # Captured output includes one-time authentication links. Never log it.
    if output and output.log and not capture and not interactive:
        return cli.run(command, stdout=output.log, stderr=subprocess.STDOUT)
    if interactive:
        print(
            "외부 설치 프로그램의 확인을 기다리는 중입니다. 아래 안내에 따라 진행하세요.",
            flush=True,
        )
        # Native installers may need to show their own consent/password prompts.
        token = _current.set(None)
        try:
            return cli.run(command, capture=capture)
        finally:
            _current.reset(token)
    return cli.run(command, capture=capture)


def command_streams(capture, kwargs):
    """Route child diagnostics without touching machine-readable output or prompts."""
    output = _current.get()
    if output and output.log and not capture:
        kwargs.setdefault("stdout", output.log)
        kwargs.setdefault("stderr", output.log)
    return kwargs


def report_error(error):
    """Keep internal exception text in a private log, outside terminal guidance."""
    path = getattr(error, "setup_log_path", None)
    if not path:
        try:
            folder = cli.ROOT / ".bridge/logs"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, path = tempfile.mkstemp(prefix="error-", suffix=".log", dir=folder)
            with os.fdopen(descriptor, "w") as log:
                log.write(f"{type(error).__name__}: {error}\n")
        except OSError:
            pass
    print(
        "작업을 완료하지 못했습니다. 입력값과 실행 환경을 확인한 뒤 다시 시도하세요.",
        file=sys.stderr,
    )
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


@contextlib.contextmanager
def operation(args):
    labels = {
        "install": "Bridge 설치",
        "update": "Bridge 업데이트",
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
    internal = (
        args.local
        or any(getattr(args, key, False) for key in ("link_only", "code_only", "info"))
        or getattr(args, "tunnel_command", None) == "status"
        or getattr(args, "agent_command", None) in {"serve", "job"}
    )
    if internal or args.command not in labels:
        yield
        return
    with SetupOutput() as output, output.step(labels[args.command]):
        yield


class SetupOutput:
    def __init__(self, *, verbose=False):
        self.verbose = verbose
        self.log = None
        self.path = None

    def __enter__(self):
        if not self.verbose:
            folder = cli.ROOT / ".bridge/logs"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, path = tempfile.mkstemp(prefix="setup-", suffix=".log", dir=folder)
            self.path = Path(path)
            self.log = os.fdopen(descriptor, "w")
            print(f"진단 로그: {self.path}", flush=True)
        self.token = _current.set(self)
        return self

    def __exit__(self, exc_type, error, traceback):
        _current.reset(self.token)
        if self.log:
            if error:
                self.log.write(f"\n{exc_type.__name__}: {error}\n")
                error.setup_log_path = self.path
            self.log.close()

    def _heartbeat(self, stopped, label, started):
        while not stopped.wait(HEARTBEAT_SECONDS):
            elapsed = int(time.monotonic() - started)
            print(f"{label} 중… {elapsed // 60}분 {elapsed % 60}초 경과", flush=True)

    @contextlib.contextmanager
    def step(self, label):
        print(f"{label} 중…", flush=True)
        if self.log:
            self.log.write("\nSetup step started\n")
            self.log.flush()
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
        print(f"{label} 완료", flush=True)
