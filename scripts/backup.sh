#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
umask 077
mkdir -p backups
name="collector-$(date -u +%Y%m%dT%H%M%SZ)-$$.kcb"
cleanup() { docker compose exec -T api rm -f "/tmp/$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose exec -T api python -m server.maintenance backup "/tmp/$name"
docker compose cp "api:/tmp/$name" "backups/$name"
chmod 600 "backups/$name"
echo "Encrypted DB backup: backups/$name"
echo 'Keep secrets/backup_key separately. Android /data and enrollment state require a stopped-instance snapshot.'
