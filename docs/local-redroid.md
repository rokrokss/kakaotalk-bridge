# Apple Silicon Mac에서 실행하기

자동 설치, 패스키 로그인, 선택적 웹 AI 연결 설정, 전체 암호화 백업은 [한 번에 설치하기](quickstart.md)부터 시작하세요. Tailscale이나 OpenAI 터널은 필수가 아닙니다. 아래는 기존 수동 배포 절차입니다.

[README](../README.md) · [관리 화면](web-ui.md) · [ChatGPT 연결](dot-plugin.md)

Lima의 Ubuntu 24.04 arm64 VM 안에서 Docker 컨테이너를 실행하며, 이미지 빌드에는 Docker Desktop을 사용합니다. 제공 설정은 CPU 6개, 메모리 8 GiB, 가상 디스크 40 GiB를 할당합니다. Mac 홈 디렉터리는 VM에 마운트하지 않습니다.

<a id="1-prepare-and-build"></a>

## 1. 준비와 빌드

Homebrew로 Lima를 설치하고 Docker Desktop을 설치하세요. 저장소 루트에서 실행하며 기존 설치의 `.env`와 키는 재사용합니다.

```bash
cp .env.example .env
./scripts/init-secrets.sh
docker compose build api device-agent gateway
```

네트워크가 겹치면 키 생성 전에 `.env`를 수정하세요. 요구 사항은 [Linux 설치](install.md#1-prepare-configuration-and-keys)와 같습니다. 카카오톡 APK를 `inputs/kakao/`에 두거나 [Android 휴대폰에서 가져오세요](install.md#2-prepare-the-kakaotalk-apk).

<a id="2-create-the-vm-and-transfer-files"></a>

## 2. VM 생성과 파일 전송

```bash
limactl start --name=kakaotalk-test --tty=false deploy/lima.yaml
limactl shell --workdir=/ kakaotalk-test sudo mkdir -p /srv/kakaotalk-collector
```

다음은 현재 커밋의 소스와 로컬 설정을 새 VM에 복사합니다. 기존 VM을 갱신할 때는 그 VM의 키와 `.env`를 덮어쓰지 않도록 주의하세요.

```bash
set -o pipefail
git archive HEAD |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
COPYFILE_DISABLE=1 tar --no-xattrs -cf - .env secrets inputs |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
```

Mac과 VM의 UID가 달라 `--no-same-owner`로 VM의 root 소유로 복사합니다. `secrets/`의 0700 권한을 유지하세요.

이미지도 전송합니다. 아래는 기본 태그이며 `.env`에서 바꿨다면 해당 이름을 사용하세요.

```bash
docker save kakaotalk-collector/device:0.1.0 kakaotalk-collector/server:0.1.0 kakaotalk-collector/gateway:2.11.7 |
  gzip -1 | limactl shell --workdir=/ kakaotalk-test sudo docker load
```

<a id="3-start-and-sign-in"></a>

## 3. 시작과 로그인

```bash
./scripts/lima-compose.sh up -d --no-build
./scripts/lima-compose.sh ps
./scripts/lima-compose.sh exec -T admin python -m device.cli probe
```

고정 호스트 이름에 비공개 HTTPS를 설정하고 [기존 VM 안에서 패스키를 등록](passkeys.md#existing-deployments)하세요. 설정된 관리 주소에서 **패스키로 로그인**을 누른 뒤 [카카오톡 로그인 절차](web-ui.md#first-login)를 따르세요.

새 설치 도구는 `kakaotalk-test`를 자동으로 인계받지 않습니다. Mac의 `./bridge`는 별도 VM을 관리하므로 이 설치에는 수동 배포 명령을 사용하세요.

관리 요약에서 **AI 연결**, **대화 이벤트**, **태블릿 및 설정**으로 이동할 수 있습니다. 이 수동 VM에서 연결 설정을 사용하려면 기존 설치 안에서 [웹 설정 서비스 안내](operations.md#web-connection-setup)를 따르세요. Mac 소스만 수정해도 VM 소스나 실행 이미지가 갱신되지는 않습니다. 설정 서비스는 원래 VM 디렉터리·키·Compose 프로젝트를 사용해야 합니다.

`lima-compose.sh`는 VM의 `/srv/kakaotalk-collector`에서 Compose를 실행합니다. Mac에서 단순히 `docker ps`를 실행하면 Docker Desktop의 상태를 봅니다.

<a id="stop-and-restart"></a>

## 중지와 재시작

```bash
limactl stop kakaotalk-test
limactl start kakaotalk-test
./scripts/lima-compose.sh up -d --no-build
```

중지해도 볼륨은 유지됩니다. `limactl delete`, `docker compose down -v`는 일반 종료 명령이 아닙니다. MCP도 실행 중이었다면 재시작 명령에 `--profile dot`을 추가하세요.

<a id="differences-from-the-linux-defaults"></a>

## Linux 기본 구성과의 차이

`deploy/compose.lima.yaml`은 Apple Silicon에서 실행되는 Android 14 이미지를 다이제스트로 고정하며 64비트 앱만 지원합니다. binderfs inode를 `/dev/binder`, `/dev/hwbinder`, `/dev/vndbinder`에 직접 마운트하고 VM의 systemd 서비스가 시작 시 기기를 준비합니다.

이 환경에서 Android 시작, 보조 기기 로그인, Iris의 새 메시지 수집을 검증했습니다. [검증 범위](implementation.md)를 참고하세요. 상시 운영 시 전원·네트워크·잠자기를 관리하세요. Mac이 잠들면 외부 접속과 수집이 끊길 수 있습니다.
