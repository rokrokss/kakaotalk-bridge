# 운영과 복구

[README](../README.md) · [설치와 실행](quickstart.md) · [고급 설치](onboarding.md) · [보안](security.md)

| 하려는 일 | 명령 |
| --- | --- |
| 상태 점검 | `kakaotalk-bridge doctor` |
| 업데이트 | 설치 명령 다시 실행 또는 `kakaotalk-bridge upgrade` · [업데이트](#update) |
| 중지·시작 | `kakaotalk-bridge stop`, `kakaotalk-bridge start` |
| 관리 화면 열기 | `kakaotalk-bridge admin` (서비스 시작까지 하려면 `kakaotalk-bridge up`) |
| 백업·복구 | `kakaotalk-bridge backup`, `kakaotalk-bridge restore` · [유지 관리와 복구](onboarding.md#maintain-and-recover) |
| 삭제 | `kakaotalk-bridge cleanup` · [삭제](#uninstall) |

`kakaotalk-bridge`는 어느 폴더에서나 실행할 수 있으며 설치 폴더 안의 `./bridge`와 같은 명령입니다. 0.2.2 이하 버전의 설치에는 이 명령이 없으니 설치 명령을 다시 실행해 업데이트하세요. 아래 `docker compose` 명령은 Linux 설치 폴더에서 실행하고, Docker 권한이 없으면 `sudo`를 붙이세요. Mac은 VM 안에서 실행합니다.

```bash
# Mac: enter the VM, then run docker compose with sudo
limactl shell kakaotalk-bridge
cd /srv/kakaotalk-bridge
```

<a id="check-status"></a>
## 상태 확인

```bash
kakaotalk-bridge doctor                                # Status summary (--json for JSON)
docker compose logs --tail 30 iris-collector   # Recent collector log
```

- `doctor`는 Docker·Compose·Binder, 인증 키, 비공개 HTTPS 인증서 만료일, 서비스 상태를 점검하고, 확인할 항목이 있으면 종료 코드 1을 반환합니다. 메시지 본문과 인증 정보는 출력하지 않습니다. Mac에서는 VM 안의 서비스를 점검합니다.
- 관리 화면의 **내 Bridge**는 수집, 원격 AI 사용 기록, 휴대폰 확인을 따로 보여 줍니다.
- AI 연결은 **AI 연결 → AI 연결 설정** 마지막 단계의 **서버 연결 확인**으로, 승인·활동은 **연결 새로고침**으로 확인합니다. 성공 시각은 과거 기록이며, 지금 연결되는지는 AI에게 수집 상태를 요청해 확인하세요.
- `collecting_partial`은 최근 Iris DB 접근과 수집 승인이 유효하다는 뜻입니다. 전체 기록이나 휴대폰 상태를 보장하지 않습니다.
- 수집기는 새 행이 없으면 3초마다 확인하고, 한 번에 최대 200행(약 2 MB)을 묶어 저장합니다.

| 증상 | 조치 |
| --- | --- |
| Android 화면 없음 | redroid 시작과 호스트 Binder 기기 확인 |
| Mac에서 VM을 지운 뒤 다시 설치 | 설치 명령을 다시 실행하면 저장된 VM 이름·포트로 다시 만듭니다. VM과 함께 지워진 데이터는 백업에서 복구 |
| 수집 승인 잠김 | 관리 화면이 **카카오톡 연결** 단계로 돌아가 사유를 표시합니다. 휴대폰을 확인하고 다시 승인 |
| 건너뛴 행 | 읽거나 저장하지 못한 행은 본문 없이 기록하고 수집을 계속합니다. 수는 `/v1/status`의 `coverage.skipped_rows` |
| DB 교체·ID 역행 | Android 복구나 DB 재생성 여부를 확인한 뒤 새 세대를 등록 |
| HTTPS/OAuth 실패 | dot-ingress·dot-plugin·dot-control, 공개 HTTPS와 동의 확인. 같은 HTTPS 호스트는 패스키, 분리된 관리 화면은 코드로 승인. 진입점 설정은 UID 10001이 읽을 수 있어야 함. [HTTPS 연결](dot-plugin.md) |
| OpenAI 터널 실패 | 준비 상태, 실행용 키 권한, ID, 관리자 승인. [터널 점검](openai-tunnel.md#check-revoke-and-restore) |
| 허용됐지만 성공 호출 없음 | AI에서 연결을 마친 뒤 수집 상태를 요청. 목록 조회와 이전 호출은 세지 않음 |
| 점검 결과 갱신 필요 | **태블릿 및 설정 → 상태 확인**. 오래된 점검만으로 승인이 취소되지는 않음 |
| 휴대폰 재확인 필요 | 휴대폰을 직접 확인하고 **휴대폰 확인**에서 갱신 |
| 이벤트 허용 후 알림 없음 | 클라이언트의 구독·만료·실행 상태 확인. 허용만으로 구독되지 않음. [이벤트](events.md) |
| ADB unauthorized | 원래 device-state·iris-state 키를 유지하고 `kakaotalk-bridge stop` 후 `kakaotalk-bridge start`. ADB 인증을 끄지 말 것 |

<a id="web-connection-setup"></a>
## 웹 연결 설정 서비스

관리 화면의 **AI 연결 설정**은 호스트의 비공개 설정 에이전트를 씁니다. `kakaotalk-bridge up`과 `kakaotalk-bridge upgrade`가 systemd 서비스로 설치하고 다시 시작합니다.

```bash
kakaotalk-bridge --local setup-agent serve   # Without systemd: run as root under your service manager
```

- 에이전트에는 Docker 권한이 필요하며, 관리 컨테이너에는 보호된 Unix 소켓 폴더만 전달합니다.
- Mac은 관리되는 Linux VM 안에서 실행합니다. 직접 만든 VM에서는 그 VM의 설치 안에서 작업하세요.
- 기존 키·볼륨·배포 식별자는 그대로 두세요.
- 작업은 한 번에 하나씩 진행합니다. 새로고침은 작업을 취소하지 않지만, 에이전트를 다시 시작하면 진행 중 작업은 중단으로 표시됩니다.
- 화면이 사용 불가를 알리면 표시된 안내를 따르세요. 실패하면 **다시 시도**, 점검은 **서버 연결 확인**, 반복되면 `kakaotalk-bridge doctor`.
- 화면에는 한국어 단계만 표시하고 원문 진단은 비공개 `.bridge/logs/`에 남깁니다. 실행용 키는 작업 기록에 저장하지 않습니다. [웹 설정 보안](security.md#web-connection-setup)

<a id="update"></a>
## 업데이트

```bash
# Same command as install
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash

# Or (add --version <tag> to pick one)
kakaotalk-bridge upgrade

# Git checkouts
git pull && kakaotalk-bridge update --source
```

- 설치 명령은 설치 형태를 알아보고 새 버전의 코드로 업데이트하며, 업데이트 중에는 이전 버전의 코드를 실행하지 않습니다. 릴리스 설치는 검증된 릴리스 번들과 이미지로 바꿉니다. `release.json` 없이 소스로 받은 설치(첫 릴리스 전에 받은 설치 포함)는 최신 릴리스 태그의 소스를 받아 같은 서명 키로 이미지를 다시 빌드합니다. Git 작업 폴더는 자동으로 업데이트하지 않습니다.
- 옵션이 잘못되었거나 업데이트가 실패하면 이전 코드로 되돌립니다. 설정을 마치지 못한 설치는 업데이트하지 않고 이어서 진행합니다.
- 순서: 새 이미지 다운로드 → 전체 암호화 백업(`backups/*.kcs`, Mac은 VM 안) → 서비스 교체 → 상태 확인. 실패하면 이전 버전으로 되돌립니다.
- 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지됩니다. 0.1.0의 승인은 태블릿에 로그인된 계정으로 이어지며, 계정을 읽지 못하면 다시 승인해야 합니다.
- Iris는 수집기가 시작할 때 자동으로 교체합니다. [Iris 구성 요소 업데이트](mcp-queries.md#updating-the-iris-component)
- 설치 명령은 같은 버전이면 업데이트 없이 관리 화면을 엽니다. 업데이트가 실패하면 관리 화면을 열지 않습니다.
- Linux는 전체 과정을 root로 실행합니다. 0.1.0을 설치한 Linux 서버는 설치 명령으로 업데이트하세요. sudo 때문에 root 전용이 된 코드 폴더 권한도 함께 정리합니다.
- `.env`에 `COMPOSE_PROJECT_NAME`이 없는 기존 설치는 `kakaotalk-collector` 볼륨이 있으면 그 이름을 `.env`에 고정해 같은 데이터를 계속 씁니다. [저장 위치](#storage-locations)

<a id="stop-and-restart"></a>
## 중지와 재시작

```bash
kakaotalk-bridge stop    # Keeps volumes and logins
kakaotalk-bridge start   # Applies the saved connection and the .bridge/ Compose settings
```

> `docker compose down -v`는 로그인 상태와 DB를 지웁니다. 일상적인 종료에 쓰지 마세요. `docker compose`를 직접 쓰면 `.bridge/`의 Compose 설정(Binder 마운트, 복구한 볼륨)이 빠질 수 있습니다.

- redroid는 반복 실패를 막기 위해 자동으로 다시 시작하지 않습니다. 필요하면 `kakaotalk-bridge start`를 실행하세요. 다른 서비스는 `unless-stopped`입니다.
- Linux 자동 복구: `deploy/kakaotalk-bridge-supervisor.service.example`의 경로를 고쳐 설치하세요. 30분에 redroid 재시작을 최대 3회로 제한합니다.
- 공개 HTTPS는 별도 `dot-ingress`를 거칩니다. `docker/Caddyfile.public`(비밀값 없음)은 UID 10001이 읽을 수 있어야 합니다(보통 0644).
- `adb-init`은 Android를 만들기 전에 수집기 공개 키 두 개만 준비하며, 승인된 수집기는 root ADB를 씁니다. Android·device-state·iris-state는 함께 백업·복구하고 실행 중에 키를 바꾸지 마세요. Iris 인증 파일은 등록과 함께 자동으로 교체됩니다.

<a id="storage-locations"></a>
## 저장 위치

| 항목 | 값 |
| --- | --- |
| Compose 프로젝트·로컬 이미지 | `kakaotalk-bridge`. 기존 설치는 `.env`에 고정된 프로젝트 이름을 유지해야 같은 볼륨을 씀 |
| 릴리스 이미지 | `ghcr.io/rokrokss/kakaotalk-bridge-*` |
| Mac VM 설치 경로 | `/srv/kakaotalk-bridge` |
| 태블릿의 Bridge 파일 | `/data/kakaotalk-bridge/` (root 전용) |
| Android 키보드 앱 ID | `dev.kakaocollector.bridge`. Android가 이 ID로 활성 키보드를 저장하므로 유지 |

| 볼륨 | 내용 |
| --- | --- |
| `android-data` | Android `/data`: 카카오톡 로그인·로컬 DB, 키보드 앱, 태블릿의 Bridge 파일 |
| `collector-data` | 수집된 메시지와 서버 커서 |
| `device-state` | 등록 세대와 ADB 키 |
| `iris-state` | Iris 수집기 ADB 키 |
| `admin-state` | 암호화된 선택적 로컬 비밀번호와 취소 가능한 브라우저 세션 |
| `passkey-state` | 암호화된 공개 인증 정보, RP·출처 설정, 임시 인증 상태 |
| `dot-state` | OAuth·터널 승인, 원격 호출 성공 시각, 대화 이벤트 권한·구독·처리 커서·웹훅 대기열 |

- 태블릿의 Bridge 파일: `enrollment.json`(수집 승인, 0600), `iris.apk`, `iris.pid`, `iris-auth.json`, `native/`(이름 조회용 라이브러리). 등록 정보에는 수집 토큰·게이트웨이 주소·인증서가 없습니다.
- 0.1.0이 쓰던 기기 내부 파일은 업데이트를 되돌릴 때 필요하므로, 새 수집기가 10분 넘게 동작한 뒤 정리합니다.
- 메시지는 매시간 기본 30일 이전 것을 정리합니다. `RETENTION_DAYS`로 바꾸며, 재전송 중복 제거도 이 기간 안에서 합니다. Android DB와 백업 파일은 정리하지 않습니다.
- 컨테이너 로그는 서비스마다 10 MB 파일 3개로 제한합니다.

<a id="back-up-android-and-mcp-state"></a>
## Android·MCP 상태 백업

```bash
kakaotalk-bridge backup   # 7 volumes, .env and secrets/ in one encrypted snapshot (backups/*.kcs)
```

- 복구 절차와 백업 키 보관은 [유지 관리와 복구](onboarding.md#maintain-and-recover)를 보세요.
- 볼륨을 따로 복사하거나 일부만 복구하지 마세요. Android 데이터·등록 상태·ADB 키는 서로 맞아야 합니다.
- 같은 계정으로 원본과 복원 인스턴스를 동시에 실행하지 마세요.

새 등록 세대가 필요한 수동 복구:

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch

# With .bridge/host.yaml or .bridge/volumes.yaml, include them (same Binder and volumes)
docker compose -f compose.yaml -f .bridge/host.yaml -f .bridge/volumes.yaml \
  --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

- 새 등록은 잠긴 상태로 시작합니다. 두 기기 로그인을 확인하고 다시 승인하세요.
- 남은 DB 메시지를 새 세대로 다시 읽으므로 기존 기록과 중복될 수 있습니다.

<a id="renew-certificates"></a>
## 인증서 갱신

비공개 HTTPS 포트(Linux 기본 `127.0.0.1:8443`, Mac은 설치 때 정한 로컬 포트)의 자체 서명 인증서 `secrets/tls_cert.pem`은 365일간 유효하며 자동으로 갱신하지 않습니다. `kakaotalk-bridge doctor`가 만료 30일 전부터 경고합니다.

```bash
kakaotalk-bridge backup
# Mac: run the openssl and chmod lines inside the VM, in /srv/kakaotalk-bridge.
sudo openssl req -x509 -newkey rsa:3072 -nodes -days 365 -sha256 \
  -keyout secrets/tls_key.pem -out secrets/tls_cert.pem \
  -subj '/CN=KakaoTalk Bridge Private Gateway' \
  -addext 'subjectAltName=IP:127.0.0.1,DNS:localhost'
sudo chmod 444 secrets/tls_cert.pem secrets/tls_key.pem
kakaotalk-bridge stop && kakaotalk-bridge start
```

- 이 인증서를 지정한 클라이언트(예: [HTTP API](api.md)의 `--cacert`)는 새 파일을 쓰세요. Android, 카카오톡 로그인, 수집 승인에는 영향이 없습니다.
- 소스로 빌드한 설치의 Bridge 서명 키 `secrets/bridge.jks`는 바꾸지 마세요. 키보드 앱을 업데이트할 수 없게 됩니다.

<a id="uninstall"></a>
## 삭제

```bash
kakaotalk-bridge cleanup         # Lists what goes, then asks you to type 삭제
kakaotalk-bridge cleanup --yes   # No prompt
```

- 카카오톡 로그인, 수집한 메시지, 패스키, 백업, 설정과 키를 모두 지우며 되돌릴 수 없습니다. 남겨 둘 백업은 먼저 `backups/`와 `secrets/backup_key`를 다른 곳에 복사하세요(Mac은 VM 안에 있음).
- Mac은 관리되는 Lima VM을, Linux는 이 설치의 컨테이너·볼륨(복구 전 볼륨 포함)·네트워크·이미지, 웹 연결 설정 서비스, Binder 자동 로드 설정을 지웁니다. 다른 컨테이너가 사용 중인 이미지는 남깁니다.
- 마지막으로 설치 폴더를 지웁니다. Git 작업 폴더는 소스 코드를 남기고 `.env`, `secrets/`, `.bridge/`, `backups/`, `inputs/`, `artifacts/`만 지웁니다.
- `kakaotalk-bridge expose`로 켠 Tailscale Funnel은 설정이 그대로일 때만 끕니다.
- Docker, Homebrew, Lima, Tailscale, uv 같은 공용 도구와 Lima 이미지 캐시는 지우지 않습니다. AI 앱에 추가한 연결과 Tailscale 관리 콘솔의 기기는 직접 지우세요.
