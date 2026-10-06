# 운영과 복구

업데이트하려면 처음 사용한 설치 명령을 다시 실행하세요([업데이트](#update)). `./bridge doctor`로 상태를 확인하고 `./bridge backup`, `./bridge restore`로 백업·복구합니다. `./bridge up`은 업데이트 없이 서비스를 시작하고 관리 화면을 엽니다.

설치, 패스키, Aurora 설정, 전체 암호화 백업은 [개인 Bridge 설정](onboarding.md)을 참고하세요.

[README](../README.md) · [보안](security.md)

아래 `docker compose` 명령은 Linux 설치 폴더에서 실행합니다. Docker 권한이 없으면 `sudo`를 붙이세요. Mac 설치는 `limactl shell kakaotalk-bridge`(기본 VM 이름)로 VM에 들어가 `/srv/kakaotalk-bridge`에서 `sudo`로 실행합니다.

<a id="check-status"></a>
## 상태 확인

관리 화면의 **내 Bridge**에서 시작하세요. 수집, 원격 AI 사용 기록, 휴대폰 직접 확인은 독립된 상태입니다. 서비스는 **AI 연결 → 연결 추가 또는 변경 → 서버 연결 확인**, 승인·활동은 **연결 새로고침**으로 확인합니다. 성공 시각은 과거 사용 기록이며 현재 연결을 보장하지 않습니다. 전체 요청 경로를 검증하려면 연결된 AI에 수집 상태를 요청하세요.

```bash
./bridge doctor
docker compose logs --tail 30 iris-collector
```

`./bridge doctor`는 Docker·Compose·Binder, 인증 키, 비공개 HTTPS 인증서 만료일, 서비스 상태를 한국어로 요약하고 확인이 필요한 항목이 있으면 종료 코드 1을 반환합니다. `--json`은 같은 결과를 JSON으로 출력합니다. 메시지 본문과 인증 정보는 출력하지 않습니다. Mac에서는 VM 안의 서비스를 점검합니다.

`collecting_partial`은 최근 Iris DB 접근과 보조 기기 승인이 유효하다는 뜻입니다. 전체 기록의 누락 검사나 휴대폰 자동 확인을 뜻하지 않습니다.

| 증상 | 확인할 내용 |
| --- | --- |
| Android 화면 없음 | redroid 시작과 호스트 binder 기기 |
| Mac에서 VM을 삭제한 뒤 다시 설치 | 설치 명령을 다시 실행하면 저장된 VM 이름과 포트로 Bridge 템플릿을 사용해 생성합니다. VM과 함께 삭제된 데이터는 백업에서 복구해야 합니다. |
| 수집 승인 잠김 | 관리 화면의 승인 상태 사유 확인. 휴대폰을 확인하고 다시 승인 |
| 건너뛴 행 | Iris가 읽지 못하거나 서버가 저장하지 못한 행은 본문 없이 건너뛰기 기록으로 남기고 수집을 계속함. 수는 `/v1/status`의 `coverage.skipped_rows` |
| DB 교체·ID 역행 | Android 복구·DB 재생성 여부. 새 세대 등록 전에 원인 확인 |
| HTTPS/OAuth 실패 | dot-ingress·dot-plugin·dot-control, 공개 HTTPS·동의. 같은 HTTPS는 패스키, 분리된 관리 화면은 코드 승인. 진입점 설정을 UID 10001이 읽을 수 있어야 함. [연결 설정](dot-plugin.md) |
| OpenAI 터널 실패 | 준비 상태, 실행용 키 권한, ID, 관리자 승인. [터널 점검](openai-tunnel.md#check-revoke-and-restore) |
| 허용되었지만 성공 호출 없음 | AI 설정 완료 후 수집 상태 요청. 목록 조회·이전 호출은 집계하지 않음 |
| 점검 결과 갱신 필요 | **태블릿 및 설정 → 상태 확인**. 오래된 화면 점검만으로 승인이 취소되지는 않음 |
| 휴대폰 재확인 필요 | 휴대폰을 직접 확인하고 **휴대폰 확인** 갱신. 필요하면 태블릿 점검 새로고침 |
| 이벤트 허용 후 알림 없음 | 클라이언트 구독·만료·실행 상태 확인. 허용만으로 구독되지 않음. [이벤트](events.md) |
| ADB unauthorized | 원래 device-state·iris-state 키 유지. `./bridge stop` 후 `./bridge start`로 시작하면 Android보다 먼저 `adb-init`이 키를 준비함. ADB 인증을 끄지 말 것 |

수집기는 새 행이 없으면 3초마다 확인하고, 한 번에 최대 200행(약 2 MB)을 읽어 행 단위가 아닌 묶음 요청으로 저장합니다. 남은 행이 있으면 바로 다음 페이지를 읽습니다. 지연은 카카오톡·redroid 연결 상태에 따라 달라집니다.

<a id="web-connection-setup"></a>
## 웹 연결 설정

`./bridge up`과 `./bridge upgrade`는 systemd의 비공개 설정 에이전트를 설치·재시작하고 관리 출처를 유지합니다. 기존 키·볼륨·배포 식별자를 보존하세요.

Mac에서는 관리되는 Linux VM 안에서 실행하며 직접 만든 VM을 인계하지 않습니다. 직접 만든 VM에서는 그 VM의 설치 안에서 작업하세요. systemd가 없다면 설치 폴더에서 root로 `./bridge --local setup-agent serve`를 서비스 관리자로 실행하세요. 에이전트에는 Docker 접근 권한이 필요하며 관리 컨테이너에는 보호된 Unix 소켓 폴더만 전달합니다.

폼이 사용 불가를 알리면 표시된 복구 안내를 따르세요. 작업은 한 번에 하나만 진행하며 화면을 다시 열어 단계·경과 시간을 볼 수 있습니다. 새로고침은 취소하지 않지만 에이전트 재시작은 진행 중 작업을 중단으로 표시합니다. 문제 해결 후 **확인 후 다시 시도**, 서버 점검 실패에는 **다시 확인**을 사용하세요. 반복되면 `./bridge doctor`로 진단하세요.

단계 안내는 한국어이며 내부 명령 출력과 오류를 그대로 표시하지 않습니다. 터미널 설정의 원문 진단은 비공개 `.bridge/logs/`에 보관합니다. 작업 기록과 마지막 성공 방식은 별도로 저장하며 실행용 키를 포함하지 않습니다. 점검·실패는 성공한 방식 선택을 바꾸지 않습니다. HTTPS·터널 안내는 현재 설정에서 생성하고 저장하지 않은 폼 편집은 복원하지 않습니다. [웹 설정 보안](security.md#web-connection-setup)

<a id="update"></a>
## 업데이트

기존 설치는 처음 사용한 설치 명령을 다시 실행해 업데이트하세요.

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

설치 폴더가 있으면 최신 정식 릴리스를 내려받아 검증하고 업데이트한 뒤(`./bridge upgrade`) `./bridge up`으로 관리 화면을 엽니다. Linux에서는 전체 과정을 root로 실행합니다. 이미 같은 버전이면 업데이트 없이 관리 화면을 엽니다. 업데이트가 실패하면 중단하며 관리 화면을 열지 않습니다.

설치 폴더에서 `./bridge upgrade`로 업데이트만 실행할 수도 있습니다. 특정 버전은 `./bridge upgrade --version <태그>`로 지정합니다. Git 작업 폴더는 `git pull` 후 `./bridge update --source`를 사용하세요. 0.1.0을 설치한 Linux 서버는 `./bridge up`이나 `./bridge upgrade` 대신 설치 명령을 다시 실행하세요. sudo로 업데이트해 root 전용이 된 코드 폴더의 권한도 함께 정리합니다.

업데이트는 새 이미지를 먼저 내려받고, 이전 구성의 전체 암호화 백업(`backups/*.kcs`, Mac은 VM 안)을 만든 뒤 서비스를 교체하고 상태를 확인합니다. 서비스가 정상적으로 시작되지 않으면 이전 버전으로 되돌립니다. 설정, Android 데이터, 카카오톡 로그인, 수집 승인은 유지되며 0.1.0의 승인도 태블릿에 로그인된 계정으로 이어집니다. 그때 태블릿의 계정을 읽을 수 없으면 다시 승인해야 합니다. 수집기가 시작할 때 기기의 Iris를 이미지의 빌드로 교체하므로 별도 이전 작업이 필요하지 않습니다([Iris 구성 요소 업데이트](mcp-queries.md#updating-the-iris-component)).

`.env`에 `COMPOSE_PROJECT_NAME`이 없는 기존 설치는 `kakaotalk-collector` 볼륨이 있으면 그 이름을 `.env`에 고정해 같은 데이터를 계속 사용합니다. [저장 위치](#storage-locations)

<a id="stop-and-restart"></a>
## 중지와 재시작

```bash
./bridge stop
./bridge start
```

`stop`은 볼륨과 로그인 상태를 유지합니다. `start`는 저장된 연결 방식과 `.bridge/`의 Compose 설정(Binder 마운트, 복구한 볼륨)을 함께 적용합니다. `docker compose`를 직접 사용하면 이 설정이 빠질 수 있습니다. **`docker compose down -v`는 로그인 상태와 DB를 삭제하므로 일상적인 종료에 사용하지 마세요.**

공개 HTTPS는 별도 `dot-ingress`를 거쳐야 합니다. 읽기 전용 `docker/Caddyfile.public`에는 비밀값이 없고 UID 10001이 읽을 수 있어야 합니다(일반적으로 0644).

`adb-init`은 Android 생성 전에 수집기 공개 키 두 개만 준비합니다. 승인된 수집기는 root ADB를 사용할 수 있습니다. Android·device-state·iris-state를 함께 백업·복구하고 실행 중 키를 교체하지 마세요. Iris 인증 파일은 자동 관리하며 등록과 함께 교체됩니다.

반복 실패를 피하기 위해 redroid 자동 재시작은 꺼져 있습니다. 필요하면 `./bridge start`로 다시 시작하세요. 다른 장기 실행 서비스는 `unless-stopped`입니다. Linux 자동 복구는 `deploy/kakaotalk-bridge-supervisor.service.example`의 경로를 수정해 설치하세요. 감독 서비스는 30분 내 redroid 재시작을 3회로 제한합니다.

<a id="storage-locations"></a>
## 저장 위치

새 설치의 Compose 프로젝트와 로컬 이미지 이름은 `kakaotalk-bridge`, 릴리스 이미지는 `ghcr.io/rokrokss/kakaotalk-bridge-*`, Mac VM의 설치 경로는 `/srv/kakaotalk-bridge`입니다. 기존 설치는 `.env`에 고정된 Compose 프로젝트 이름을 유지해야 같은 볼륨을 사용합니다. Android 키보드 앱 ID `dev.kakaocollector.bridge`는 Android가 활성 키보드를 이 ID로 저장하므로 그대로 사용합니다.

| 볼륨 | 내용 |
| --- | --- |
| `android-data` | Android `/data`: 카카오톡 로그인·로컬 DB, 키보드 앱, 태블릿의 Bridge 파일 |
| `collector-data` | 수집된 메시지와 서버 커서 |
| `device-state` | 등록 세대와 ADB 키 |
| `iris-state` | Iris 수집기 ADB 키 |
| `admin-state` | 암호화된 선택적 로컬 비밀번호와 취소 가능한 브라우저 세션 |
| `passkey-state` | 암호화된 공개 인증 정보, RP·출처 설정, 임시 인증 상태 |
| `dot-state` | OAuth·터널 승인, 원격 호출 성공 시각, 대화 이벤트 권한·구독·처리 커서·웹훅 대기열 |

태블릿의 Bridge 파일은 root 전용 폴더 `/data/kakaotalk-bridge/`에 있습니다. 수집 승인을 담은 `enrollment.json`(0600), Iris 실행 파일 `iris.apk`, 프로세스 ID `iris.pid`, Iris 인증 파일 `iris-auth.json`, 이름 조회에 쓰는 라이브러리 폴더 `native/`입니다. 등록 정보에는 수집 토큰·게이트웨이 주소·인증서가 들어 있지 않습니다. 0.1.0이 쓰던 기기 내부 파일은 업데이트가 실패해 이전 버전으로 되돌아갈 때 필요하므로 새 수집기가 10분 넘게 동작한 뒤 정리합니다.

서버는 매시간 기본 30일 이전 메시지를 정리합니다. `RETENTION_DAYS`로 변경하세요. 재전송 중복 제거도 이 기간 안에 적용합니다. Android DB와 백업 파일은 정리하지 않습니다. 컨테이너 로그는 각각 10 MB 파일 3개로 제한합니다.

<a id="back-up-android-and-mcp-state"></a>
## Android·MCP 상태 백업

`./bridge backup`은 볼륨 7개, `.env`, `secrets/`를 하나의 암호화 스냅샷(`backups/*.kcs`)으로 만듭니다. 동작과 복구는 [유지 관리와 복구](onboarding.md#maintain-and-recover)를 참고하세요. Android 데이터·등록 상태·ADB 키는 서로 맞아야 하므로 볼륨을 따로 복사하거나 일부만 복구하지 마세요. Android에는 Iris 인증 정보, 수집기 볼륨에는 승인된 ADB 식별 정보가 있습니다. 같은 계정으로 원본·복원 인스턴스를 동시에 실행하지 마세요.

새 등록 세대가 필요한 수동 복구에는 다음을 사용합니다.

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

`.bridge/host.yaml`이나 `.bridge/volumes.yaml`이 있으면 `-f compose.yaml -f .bridge/host.yaml -f .bridge/volumes.yaml`처럼 함께 지정해야 같은 Binder 설정과 볼륨을 사용합니다. 새 등록은 잠긴 상태로 시작하므로 두 기기 로그인을 확인하고 다시 승인해야 합니다. 남은 DB 메시지를 새 세대로 다시 읽으므로 기존 기록과 중복될 수 있습니다.

<a id="renew-certificates"></a>
## 인증서 갱신

`secrets/tls_cert.pem`은 비공개 HTTPS 포트(Linux 기본 `127.0.0.1:8443`, Mac은 설치 때 정한 로컬 포트)의 자체 서명 인증서입니다. 365일간 유효하며 자동으로 갱신하지 않습니다. `./bridge doctor`가 만료 30일 전부터 경고하고 만료 후에는 확인 필요로 표시합니다.

갱신하려면 백업한 뒤 설치 폴더에서 같은 이름과 SAN으로 인증서와 키를 함께 다시 만들고 서비스를 다시 시작하세요. Mac은 `openssl`, `chmod` 두 명령만 VM의 `/srv/kakaotalk-bridge`에서 실행합니다.

```bash
./bridge backup
# Mac: run the openssl and chmod lines inside the VM, in /srv/kakaotalk-bridge.
sudo openssl req -x509 -newkey rsa:3072 -nodes -days 365 -sha256 \
  -keyout secrets/tls_key.pem -out secrets/tls_cert.pem \
  -subj '/CN=KakaoTalk Bridge Private Gateway' \
  -addext 'subjectAltName=IP:127.0.0.1,DNS:localhost'
sudo chmod 444 secrets/tls_cert.pem secrets/tls_key.pem
./bridge stop && ./bridge start
```

이 인증서를 신뢰하도록 지정한 클라이언트(예: [HTTP API](api.md)의 `--cacert`)는 새 파일을 사용하세요. Android, 카카오톡 로그인, 수집 승인에는 영향이 없습니다. 소스로 빌드한 설치의 Bridge 서명 키(`secrets/bridge.jks`)는 바꾸지 마세요. 바꾸면 키보드 앱을 업데이트할 수 없습니다.
