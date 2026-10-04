# Linux 설치

[README](../README.md) · [Mac 설치](local-redroid.md)

단일 계정용 Docker Compose 구성입니다. Linux amd64/arm64에서 실행하며 Docker Engine, Compose v2, Bash, OpenSSL, Android binder/binderfs가 필요합니다. 처음에는 4 vCPU·8GB RAM으로 준비하세요. 최소 사양을 측정한 값은 아닙니다.

## 1. 설정과 키 준비

저장소 루트에서 실행합니다.

```bash
cp .env.example .env
./scripts/preflight.sh
```

`preflight`가 실패하면 Linux 커널과 binder 구성을 먼저 해결하세요. 공유 메모리는 `androidboot.use_memfd=1`을 사용합니다.

`.env`의 `DEVICE_SUBNET`이 LAN·VPN·다른 Docker 네트워크와 겹치지 않는지 확인합니다. 변경할 때는 `GATEWAY_IP`와 `DEVICE_IP_RANGE`도 함께 맞추되, 자동 배정 범위에 고정 gateway 주소를 넣지 않습니다. 기본값은 각각 `172.29.87.0/24`, `172.29.87.3`, `172.29.87.128/25`입니다.

```bash
./scripts/init-secrets.sh
```

이 스크립트는 기존 키를 보존합니다. `.env`는 셸 호환 `KEY=value` 형식을 유지하고, 생성한 `secrets/`와 Bridge 서명 키를 보관하세요.

## 2. 카카오톡 APK 준비

정식 설치 파일을 `inputs/kakao/`에 넣습니다. split APK라면 같은 버전·서명의 전체 설치 세트가 필요합니다. 이미 redroid에 설치했다면 비워 둘 수 있습니다.

USB로 연결한 Android 폰에서 가져오려면 호스트에 ADB와 Python 개발 환경이 필요합니다. 폰에서 USB 디버깅을 허용한 뒤 실행하세요.

```bash
uv sync --frozen --python 3.12
uv run python scripts/import-phone-apks.py
```

이 명령은 APK만 복사합니다. 폰의 앱 데이터나 로그인 설정은 바꾸지 않습니다. 카카오톡 APK와 계정 정보는 이미지에 포함하지 않습니다.

## 3. 빌드와 실행

```bash
docker compose build api device-agent
docker compose up -d
docker compose ps
```

Python·JDK·Android SDK는 이미지 안에서 준비합니다. Android 빌드 도구는 amd64 바이너리이므로 arm64 빌드 머신에는 amd64 실행 지원이 필요합니다. 없다면 별도 빌드 머신에서 arm64 런타임 이미지를 만들어 전달하세요. 카카오톡 APK도 redroid의 ABI와 호환되어야 합니다.

## 4. 관리 화면 열기

서버에 원격으로 접속한다면 PC에서 터널을 엽니다.

```bash
ssh -N -L 18443:127.0.0.1:8443 user@linux-server
```

브라우저에서 `https://localhost:18443/admin/`을 엽니다. 서버 자체에서는 `https://localhost:8443/admin/`입니다. 생성한 `secrets/tls_cert.pem`을 확인하고 브라우저에서 신뢰하도록 설정하세요.

`secrets/admin_token`으로 인증한 뒤 **설치 관리 → 설치 준비… → 설치 실행**을 누릅니다. 카카오톡 APK, 등록 앱, 입력기와 Iris를 배치합니다. Iris는 Android 화면에 별도 앱으로 열리지 않습니다.

이후 [관리 화면의 로그인 절차](web-ui.md#처음-로그인하기)를 따릅니다. 재설치는 수집 승인을 초기화하므로, 이미 수집 중인 서버에서는 일상적인 복구 수단으로 사용하지 마세요.

## 5. 수집 확인과 연결

양쪽 로그인 확인 후 관리 화면에서 **메시지 수집 시작**을 누릅니다. 핸드폰에서 나에게 메시지를 보내고 [API](api.md) 또는 [ChatGPT](dot-plugin.md)로 새 메시지가 조회되는지 확인하세요.

운영 명령과 백업은 [운영 안내](operations.md)에 있습니다.
