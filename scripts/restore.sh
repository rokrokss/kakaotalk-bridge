#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
[[ $# == 1 && -f "$1" ]] || { echo 'Usage: scripts/restore.sh backups/FILE.kcb' >&2; exit 1; }
[[ -z $(docker compose ps --status running -q api) ]] || { echo 'Stop the API before restoring.' >&2; exit 1; }
docker compose run --rm --no-deps -T api python -c '
import shutil, sys, tempfile
from pathlib import Path
from server.maintenance import restore
with tempfile.TemporaryDirectory() as folder:
    source = Path(folder) / "backup.kcb"
    with source.open("wb") as output:
        shutil.copyfileobj(sys.stdin.buffer, output)
    restore(str(source), "/data/collector.db", replace=True)
' < "$1"
echo 'Restore complete. Start the API and verify coverage and cursors.'
