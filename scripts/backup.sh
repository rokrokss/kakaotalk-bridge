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
echo "암호화된 DB 백업: backups/$name"
echo 'secrets/backup_key는 별도로 보관하세요. Android /data와 기기 등록 상태는 인스턴스를 중지한 뒤 스냅샷으로 백업해야 합니다.'
