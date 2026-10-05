#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
[[ $# == 1 && -f "$1" ]] || { echo '사용법: scripts/restore.sh backups/FILE.kcb' >&2; exit 1; }
[[ -z $(docker compose ps --status running -q api) ]] || { echo '복구 전에 API를 중지하세요.' >&2; exit 1; }
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
echo '복구를 완료했습니다. API를 시작하고 수집 범위와 커서를 확인하세요.'
