"""Optional Linux host service: restart only stopped redroid, max 3 times / 30 minutes.

Requires host Python 3.12+ and Docker access. Run in the Compose project directory.
Does not recreate/delete containers, log in, or touch Android application data.
"""

import json
import os
import subprocess
import time
from pathlib import Path


def tick(state_path: Path):
    result = subprocess.run(
        ["docker", "compose", "ps", "--all", "--format", "json", "redroid"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    text = result.stdout.strip()
    if not text:
        return "not_created"
    states = (
        json.loads(text)
        if text.startswith("[")
        else [json.loads(line) for line in text.splitlines()]
    )
    if len(states) != 1:
        return "unexpected_container_count"
    status = states[0]["State"]
    if status not in ("exited", "dead", "created"):
        return status
    now = time.time()
    attempts = json.loads(state_path.read_text()) if state_path.exists() else []
    recent = [t for t in attempts if now - t < 1800]
    if len(recent) >= 3:
        return "restart_limit_reached"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(".tmp")
    temp.write_text(json.dumps([*recent, now]))
    temp.replace(state_path)
    subprocess.run(
        ["docker", "compose", "start", "redroid"],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "restarted"


def main():
    state = Path(os.getenv("SUPERVISOR_STATE", "artifacts/supervisor.json"))
    while True:
        try:
            print(tick(state), flush=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            print("supervisor_error", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
