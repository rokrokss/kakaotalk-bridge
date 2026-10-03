#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
docker compose version
docker info --format 'Docker: {{.OSType}}/{{.Architecture}}'
docker compose config --quiet
if [[ $(uname -s) != Linux ]]; then
    echo 'FAIL: Full redroid deployment requires a prepared Linux host. API/APK builds can run here.' >&2
    exit 1
fi
if [[ ! -d /sys/module/binder_linux && ! -e /dev/binderfs/binder-control && ! -e /dev/binder ]]; then
    echo 'FAIL: Android binder is not detected. Prepare binder_linux/binderfs for the host kernel.' >&2
    exit 1
fi
echo 'PASS: Linux, Docker Compose and binder presence. Actual Android boot remains a G0 test.'
echo 'Check that DEVICE_SUBNET does not overlap LAN/VPN/Docker networks before starting.'
