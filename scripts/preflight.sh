#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
docker compose version
docker info --format 'Docker: {{.OSType}}/{{.Architecture}}'
docker compose config --quiet
if [[ $(uname -s) != Linux ]]; then
    echo '확인 필요: redroid를 실행하려면 준비된 Linux 호스트가 필요합니다. 현재 환경에서는 API·APK 빌드가 가능합니다.' >&2
    exit 1
fi
if [[ ! -d /sys/module/binder_linux && ! -e /dev/binderfs/binder-control && ! -e /dev/binder ]]; then
    echo '확인 필요: Android binder를 찾지 못했습니다. 호스트 커널의 binder_linux/binderfs를 준비하세요.' >&2
    exit 1
fi
echo 'Linux, Docker Compose, binder 확인 완료. 실제 Android 시작 여부는 G0 검증에서 확인하세요.'
echo '시작 전에 DEVICE_SUBNET이 LAN·VPN·Docker 네트워크와 겹치지 않는지 확인하세요.'
