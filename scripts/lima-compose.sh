#!/usr/bin/env bash
set -euo pipefail
# This targets the dedicated Ubuntu test VM, without switching Docker Desktop's context.
exec limactl shell --workdir=/ kakaotalk-test sudo docker compose \
    --project-directory /srv/kakaotalk-collector \
    -f /srv/kakaotalk-collector/compose.yaml \
    -f /srv/kakaotalk-collector/deploy/compose.lima.yaml "$@"
