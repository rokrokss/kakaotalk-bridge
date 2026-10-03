#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
docker compose ps
docker compose exec -T api python -c '
import json, urllib.request
from pathlib import Path
r = urllib.request.Request("http://localhost:8000/v1/status", headers={"Authorization": "Bearer " + Path("/run/secrets/read_token").read_text().strip()})
print(json.dumps(json.load(urllib.request.urlopen(r, timeout=10)), indent=2, ensure_ascii=False))
'
