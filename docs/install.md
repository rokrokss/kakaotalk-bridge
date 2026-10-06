# Linux 설치

자동 설치, 패스키 로그인, 웹 AI 연결 설정, 전체 암호화 백업은 [한 번에 설치하기](quickstart.md)부터 시작하세요. Tailscale이나 OpenAI 터널은 필수가 아닙니다. 아래는 HTTPS 관리 주소를 사용하는 기존 수동 배포 절차입니다.

[README](../README.md) · [Mac 설치](local-redroid.md)

Linux amd64/arm64의 단일 계정용 Docker Compose 구성입니다. Docker Engine, Compose v2, Bash, OpenSSL, Android binder/binderfs가 필요합니다. CPU 4개와 메모리 8 GB로 시작할 것을 권장하지만 측정된 최소 사양은 아닙니다.

<a id="1-prepare-configuration-and-keys"></a>

## 1. 설정과 키 준비

저장소 루트에서 실행하세요.

```bash
cp .env.example .env
./bridge doctor
```

`doctor`가 실패하면 Linux 커널과 binder 설정을 먼저 해결하세요. 공유 메모리는 `androidboot.use_memfd=1`을 사용합니다.

`.env`의 `DEVICE_SUBNET`이 LAN·VPN·다른 Docker 네트워크와 겹치지 않는지 확인하세요. 변경하면 `GATEWAY_IP`, `DEVICE_IP_RANGE`도 함께 바꾸고 고정 게이트웨이 주소를 자동 할당 범위 밖에 두세요. 기본값은 각각 `172.29.87.0/24`, `172.29.87.3`, `172.29.87.128/25`입니다.

```bash
./scripts/init-secrets.sh
```

기존 키는 유지합니다. `.env`는 셸과 호환되는 `KEY=value` 형식을 사용하고 생성된 `secrets/`와 Bridge 서명 키를 보관하세요.

<a id="2-prepare-the-kakaotalk-apk"></a>

## 2. 카카오톡 APK 준비

공식 설치 파일을 `inputs/kakao/`에 두세요. 분할 APK는 버전과 서명이 일치하는 전체 세트가 필요합니다. redroid에 이미 카카오톡이 설치되어 있다면 비워 둘 수 있습니다.

USB로 연결한 Android 휴대폰에서 가져오려면 호스트에 ADB와 Python 개발 환경을 설치하고 휴대폰에서 USB 디버깅을 켜세요.

```bash
uv sync --frozen --python 3.12
uv run python scripts/import-phone-apks.py
```

APK만 복사하며 휴대폰 앱 데이터나 로그인 설정은 바꾸지 않습니다. 이미지에 카카오톡 APK나 계정 인증 정보는 포함되지 않습니다.

<a id="3-build-and-start"></a>

## 3. 빌드와 시작

```bash
docker compose build api device-agent gateway
docker compose up -d
docker compose ps
```

Python·JDK·Android SDK는 이미지 내부에서 준비됩니다. Android 빌드 도구가 amd64 바이너리를 사용하므로 arm64 빌드 호스트에는 amd64 실행 지원이 필요합니다. 지원이 없다면 별도 빌드 장비에서 arm64 실행 이미지를 만들어 옮기세요. 카카오톡 APK도 redroid의 ABI를 지원해야 합니다.

<a id="4-open-the-admin-console"></a>

## 4. 관리 화면 열기

비공개 Tailscale Serve 또는 리버스 프록시로 신뢰할 수 있는 고정 HTTPS 호스트 이름을 설정하고 [패스키](passkeys.md)를 등록하세요. Tailscale 없이 로컬·SSH 관리 화면을 사용하려면 [자동 설치](quickstart.md#local-and-ssh-admin-access)를 따르세요.

Tailscale Funnel로 MCP를 공개하려면 다음 명령으로 기존 관리 출처를 유지하며 설정할 수 있습니다.

```bash
./bridge expose
./bridge passkey-login
```

출력된 관리 주소를 열고 패스키로 인증하세요. 기존 `https://<node>.ts.net:8443/admin/` 같은 비공개 주소는 공개 MCP와 별개로 유지됩니다. 새 공용 HTTPS 구성은 443 포트의 `/admin/`, `/mcp`를 사용합니다. localhost 패스키는 공개 호스트에서 사용할 수 없으므로 출처가 다르면 관리 화면의 코드 승인을 사용합니다. 관리 출처를 계속 유지하세요.

**카카오톡 설정**에 따라 **태블릿 및 설정** 화면의 Aurora에서 카카오톡을 설치하거나 APK 세트를 가져오세요. 수집 구성 요소는 자동으로 설치되며 수동 복구에는 **설치 → 수집 구성 요소 설치**를 사용할 수 있습니다.

[첫 로그인](web-ui.md#first-login) 절차를 따르세요. 새 설정 작업은 기존 등록을 유지합니다. 이전 CLI의 `bootstrap`은 수집 승인을 초기화하므로 일상적인 복구에 사용하지 마세요.

<a id="5-verify-collection-and-connect-ai"></a>

## 5. 수집 확인과 AI 연결

두 기기의 로그인을 확인한 뒤 **메시지 수집 시작**을 누르세요. 휴대폰에서 나에게 메시지를 보내고 [API](api.md) 또는 [ChatGPT](dot-plugin.md)에서 조회하세요.

AI 연결은 선택 사항입니다. 수동 설치에 [웹 연결 설정 서비스](operations.md#web-connection-setup)를 추가하면 **AI 연결 → 연결 추가 또는 변경**을 사용할 수 있습니다. 또는 `./bridge setup-connection`을 사용하세요. 기존 관리 출처와 키는 유지하세요.

관리 명령과 백업은 [운영](operations.md)을 참고하세요.
