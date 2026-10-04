# Apple Silicon Mac에서 실행

[README](../README.md) · [관리 화면](web-ui.md) · [ChatGPT 연결](dot-plugin.md)

Lima의 Ubuntu 24.04 arm64 VM 안에서 Docker 컨테이너를 실행합니다. Docker Desktop은 이미지 빌드에 사용합니다. 제공된 설정은 6 CPU·8GiB RAM·40GiB 가상 디스크이며 Mac 홈 디렉터리를 VM에 마운트하지 않습니다.

## 1. 준비와 빌드

Homebrew Lima와 Docker Desktop이 필요합니다. 저장소 루트에서 실행합니다. 기존 설치의 `.env`와 키는 그대로 사용하세요.

```bash
cp .env.example .env
./scripts/init-secrets.sh
docker compose build api device-agent
```

네트워크가 겹치면 키를 만들기 전에 `.env`를 조정합니다. 상세 조건은 [Linux 설치](install.md#1-설정과-키-준비)와 같습니다. 카카오톡 APK는 `inputs/kakao/`에 준비하거나 [연결한 Android 폰에서 가져옵니다](install.md#2-카카오톡-apk-준비).

## 2. VM 생성과 파일 전달

```bash
limactl start --name=kakaotalk-test --tty=false deploy/lima.yaml
limactl shell --workdir=/ kakaotalk-test sudo mkdir -p /srv/kakaotalk-collector
```

다음은 새 VM에 현재 커밋의 소스와 로컬 설정을 복사합니다. 기존 VM을 업데이트할 때는 기존 키와 `.env`를 덮어쓰지 않도록 확인하세요.

```bash
set -o pipefail
git archive HEAD |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
COPYFILE_DISABLE=1 tar --no-xattrs -cf - .env secrets inputs |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
```

Mac과 VM의 UID가 다르므로 `--no-same-owner`로 VM root 소유로 복사합니다. `secrets/`의 0700 권한은 유지합니다.

이미지도 전달합니다. 아래는 기본 태그이며 `.env`에서 이미지 이름을 바꿨다면 그 이름을 사용합니다.

```bash
docker save kakaotalk-collector/device:0.1.0 kakaotalk-collector/server:0.1.0 |
  gzip -1 | limactl shell --workdir=/ kakaotalk-test sudo docker load
```

## 3. 실행과 로그인

```bash
./scripts/lima-compose.sh up -d --no-build
./scripts/lima-compose.sh ps
./scripts/lima-compose.sh exec -T admin python -m device.cli probe
```

`https://localhost:18443/admin/`에서 [로그인 절차](web-ui.md#처음-로그인하기)를 진행합니다. 인증서와 관리자 키는 앞에서 VM에 복사한 `secrets/`의 값입니다.

`lima-compose.sh`는 VM 내부 `/srv/kakaotalk-collector`의 Compose를 실행합니다. Mac에서 일반 `docker ps`를 실행하면 Docker Desktop의 상태가 나오므로 혼동하지 마세요.

## 종료와 재시작

```bash
limactl stop kakaotalk-test
limactl start kakaotalk-test
./scripts/lima-compose.sh up -d --no-build
```

종료는 볼륨을 보존합니다. `limactl delete`와 `docker compose down -v`는 일반 종료 명령이 아닙니다. MCP도 운영 중이면 재시작 명령에 `--profile dot`을 추가합니다.

## Linux 기본 설정과 다른 점

`deploy/compose.lima.yaml`은 Apple Silicon에서 실행 가능한 Android 14의 64비트 전용 이미지를 digest로 고정합니다. binderfs inode를 `/dev/binder`, `/dev/hwbinder`, `/dev/vndbinder`에 직접 bind mount하며 VM의 systemd 서비스가 부팅 시 장치를 준비합니다.

이 환경에서 Android 부팅·보조 로그인·Iris 신규 메시지 수집을 확인했습니다. [검증 범위](implementation.md)를 참고하세요. 상시 운영에서는 Mac이 잠들면 외부 접속과 수집도 중단될 수 있으므로 전원·네트워크·잠자기 설정을 함께 관리해야 합니다.
