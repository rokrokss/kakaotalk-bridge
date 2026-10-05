"""Concise installer output; captured values and interactive prompts stay private/live."""

import contextlib
import contextvars
import os
import subprocess
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
    return cli.run(command, capture=capture)


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
            print(f"Setup log: {self.path}", flush=True)
        self.token = _current.set(self)
        return self

    def __exit__(self, *_):
        _current.reset(self.token)
        if self.log:
            self.log.close()

    def _heartbeat(self, stopped, label, started):
        while not stopped.wait(HEARTBEAT_SECONDS):
            elapsed = int(time.monotonic() - started)
            print(f"{label}… still working ({elapsed // 60}m {elapsed % 60}s elapsed).", flush=True)

    @contextlib.contextmanager
    def step(self, label):
        print(f"{label}…", flush=True)
        if self.log:
            self.log.write(f"\n{label}\n")
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
        print(f"{label} — done.", flush=True)
