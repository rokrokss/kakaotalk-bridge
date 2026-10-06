#!/usr/bin/env bash
set -euo pipefail
# For a Lima VM built by hand from deploy/lima.yaml. Installer-managed VMs use ./bridge.
instance="${LIMA_INSTANCE:-kakaotalk-bridge}"
directory="${BRIDGE_DIR:-/srv/kakaotalk-bridge}"
# Targets the VM's Docker without switching Docker Desktop's context.
exec limactl shell --workdir=/ "$instance" sudo docker compose \
    --project-directory "$directory" \
    -f "$directory/compose.yaml" \
    -f "$directory/deploy/compose.lima.yaml" "$@"
