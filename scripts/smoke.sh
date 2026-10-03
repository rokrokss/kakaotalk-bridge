#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
project="kakaocollector-smoke-$$"
export DEVICE_SUBNET=172.29.88.0/24 DEVICE_IP_RANGE=172.29.88.128/25 GATEWAY_IP=172.29.88.3 HTTPS_PORT=18443
export SMOKE_PROJECT="$project"
cleanup() { docker compose -p "$project" down --volumes --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT
docker compose -p "$project" up -d --no-build api gateway
# Start only the console; never launch redroid or invoke device actions in this fixture.
docker compose -p "$project" up -d --no-build --no-deps admin
if command -v uv >/dev/null; then
    uv run python scripts/smoke.py
else
    python3 scripts/smoke.py
fi
docker compose -p "$project" restart api
docker compose -p "$project" exec -T api python -c '
import sqlite3
db = sqlite3.connect("/data/collector.db")
assert db.execute("SELECT count(*) FROM candidates").fetchone()[0] == 1
print("PASS: container restart preserves collected data")
'
# Exercise the mounted backup key, non-root volume permissions and encrypted file path.
docker compose -p "$project" exec -T api python -c '
from server.maintenance import backup, restore
from server.store import Store
backup("/data/collector.db", "/tmp/test.kcb")
restore("/tmp/test.kcb", "/tmp/restored.db")
assert len(Store("/tmp/restored.db").messages()["items"]) == 1
print("PASS: encrypted backup and verified restore inside non-root container")
'
