# 운영과 복구

같은 설치 명령을 다시 실행하면 기존 릴리스의 설치 파일과 이미지를 함께 업데이트하고 관리 화면을 엽니다. 설치 폴더에서 `./bridge upgrade`로 업데이트만 하거나 `./bridge up`으로 업데이트 없이 실행할 수도 있습니다. `./bridge doctor`로 상태를 확인하고, `./bridge backup`과 `./bridge restore --help`로 백업·복구를 관리합니다.

새 설치 프로그램, 패스키, Aurora 설정, 전체 암호화 백업은 [개인 Bridge 설정](onboarding.md)을 참고하세요. 아래는 기존 수동 배포 절차입니다.

[README](../README.md) · [보안](security.md)

Linux 호스트 기준 명령입니다. Mac의 Lima에서는 `docker compose` 대신 `./scripts/lima-compose.sh`를 사용하세요.

<a id="check-status"></a>
## 상태 확인

관리 화면의 **내 Bridge**에서 시작하세요. 수집, 원격 AI 사용 기록, 휴대폰 직접 확인은 독립된 상태입니다. 서비스는 **AI 연결 → 연결 추가 또는 변경 → 서버 연결 확인**, 승인·활동은 **연결 새로고침**으로 확인합니다. 성공 시각은 과거 사용 기록이며 현재 연결을 보장하지 않습니다. 전체 요청 경로를 검증하려면 연결된 AI에 수집 상태를 요청하세요.

```bash
docker compose --profile dot ps
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`collecting_partial`은 최근 Iris DB 접근과 보조 기기 승인이 유효하다는 뜻입니다. 전체 기록의 누락 검사나 휴대폰 자동 확인을 뜻하지 않습니다.

| 증상 | 확인할 내용 |
| --- | --- |
| Android 화면 없음 | redroid 시작과 호스트 binder 기기 |
| Mac에서 VM을 삭제한 뒤 다시 설치 | 설치 명령을 다시 실행하면 저장된 VM 이름과 포트로 Bridge 템플릿을 사용해 생성합니다. VM과 함께 삭제된 데이터는 백업에서 복구해야 합니다. |
| 수집 승인 잠김 | 관리 화면의 승인 상태 사유 확인. 휴대폰을 확인하고 다시 승인 |
| 읽지 못한 메시지 | 복호화하지 못한 행은 건너뛰고 수집 상태의 `skipped_rows`에 집계 |
| 복호화·JSON 오류 | Iris 로그. 잘못된 메시지를 건너뛰지 않고 수집 중단 |
| DB 교체·ID 역행 | Android 복구·DB 재생성 여부. 새 세대 등록 전에 원인 확인 |
| HTTPS/OAuth 실패 | dot-ingress·dot-plugin·dot-control, 공개 HTTPS·동의. 같은 HTTPS는 패스키, 분리된 관리 화면은 코드 승인. 진입점 설정을 UID 10001이 읽을 수 있어야 함. [연결 설정](dot-plugin.md) |
| OpenAI 터널 실패 | 준비 상태, 실행용 키 권한, ID, 관리자 승인. [터널 점검](openai-tunnel.md#check-revoke-and-restore) |
| 허용되었지만 성공 호출 없음 | AI 설정 완료 후 수집 상태 요청. 목록 조회·이전 호출은 집계하지 않음 |
| 점검 결과 갱신 필요 | **태블릿 및 설정 → 상태 확인**. 오래된 화면 점검만으로 승인이 취소되지는 않음 |
| 휴대폰 재확인 필요 | 휴대폰을 직접 확인하고 **휴대폰 확인** 갱신. 필요하면 태블릿 점검 새로고침 |
| 이벤트 허용 후 알림 없음 | 클라이언트 구독·만료·실행 상태 확인. 허용만으로 구독되지 않음. [이벤트](events.md) |
| ADB unauthorized | 원래 device-state·iris-state 키 유지. Android 중지 후 adb-init을 다시 실행하고 Compose로 시작해 키 준비. ADB 인증을 끄지 말 것 |

기본적으로 Iris는 3초마다 최대 50건을 읽고 대기 기록이 있으면 계속 가져옵니다. 지연은 카카오톡·redroid 연결 상태에 따라 달라집니다.

<a id="web-connection-setup"></a>
## 웹 연결 설정

설치 프로그램이 관리하는 배포는 소스와 앱 이미지를 업데이트한 뒤 기존 설치에서 `./bridge up`을 실행하세요. systemd의 비공개 설정 에이전트를 설치·재시작하고 관리 출처를 유지합니다. `up`만으로 이미지를 업데이트하지는 않습니다. 기존 키·볼륨·배포 식별자를 보존하세요.

Mac에서는 관리되는 Linux VM 안에서 실행합니다. 이전 수동 VM을 자동으로 인계하지 않으므로 그 VM의 기존 설치 안에서 작업하세요. systemd가 없다면 설치 폴더에서 root로 `./bridge --local setup-agent serve`를 서비스 관리자로 실행하세요. 에이전트에는 Docker 접근 권한이 필요하며 관리 컨테이너에는 보호된 Unix 소켓 폴더만 전달합니다.

폼이 사용 불가를 알리면 표시된 복구 안내를 따르세요. 작업은 한 번에 하나만 진행하며 화면을 다시 열어 단계·경과 시간을 볼 수 있습니다. 새로고침은 취소하지 않지만 에이전트 재시작은 진행 중 작업을 중단으로 표시합니다. 문제 해결 후 **확인 후 다시 시도**, 서버 점검 실패에는 **다시 확인**을 사용하세요. 반복되면 `./bridge doctor`로 진단하세요.

단계 안내는 한국어이며 내부 명령 출력과 오류를 그대로 표시하지 않습니다. 터미널 설정의 원문 진단은 비공개 `.bridge/logs/`에 보관합니다. 작업 기록과 마지막 성공 방식은 별도로 저장하며 실행용 키를 포함하지 않습니다. 점검·실패는 성공한 방식 선택을 바꾸지 않습니다. HTTPS·터널 안내는 현재 설정에서 생성하고 저장하지 않은 폼 편집은 복원하지 않습니다. [웹 설정 보안](security.md#web-connection-setup)

<a id="upgrading-to-the-security-update"></a>
## 보안 업데이트 적용

기존 패스키로 관리 화면에 한 번 다시 로그인하세요. 쿠키 이전으로 오래된 브라우저 세션은 거부하지만 패스키와 승인된 MCP 연결은 유지합니다. 수집기 ADB 키는 자동 준비하므로 웹 사용자에게 추가 토큰을 요구하지 않습니다. 직접 ADB·scrcpy를 사용하려면 승인된 키가 필요합니다.

Iris 바이너리와 Compose 구조도 바뀌므로 다음 순서를 따르세요.

1. 상태 볼륨 7개, 설정, 키를 포함한 전체 암호화 백업을 생성·검증하고 롤백용 이전 이미지 참조·APK 해시를 보관하세요.
2. 서버·기기·게이트웨이 이미지와 Compose 파일을 함께 갱신하세요. 공개 이미지는 세 이미지 다이제스트를 모두 담은 매니페스트를 사용하세요.
3. 수집기가 [Iris를 자동으로 교체](mcp-queries.md#updating-the-iris-component)하며 등록·카카오톡 데이터는 유지됩니다. 로그인된 태블릿에 새 bootstrap을 실행하지 마세요.
4. 갱신된 Compose로 Android를 다시 생성해 `ro.adb.secure=1` 적용 전에 `adb-init`이 수집기 키를 준비하게 하세요. `android-data`, `device-state`, `iris-state`를 함께 유지하세요. Android 재시작 후 휴대폰·태블릿 로그인을 확인하세요.
5. 맞는 버전의 서비스와 `dot-ingress`를 시작하세요. 공개 HTTPS는 기본 루프백 18787로 전달하고 관리 게이트웨이는 비공개로 유지하세요. 진입점 설정은 UID 10001이 읽을 수 있어야 하며 dot-plugin을 직접 공개하지 마세요.
6. 기존 패스키로 로그인해 수집 상태와 연결된 MCP의 프로필·상태를 조회하세요. 인증 없는 `/mcp`는 401이어야 합니다. 관리 경로를 차단한 공개 프록시에서는 `/admin/`이 404인지 확인하세요.

[보안 기록](security.md#security-fixes-2026-10-05)에 ARM64 이전 검증과 제한을 기록했습니다. 자동 설치·릴리스 업데이트의 전체 과정은 모든 호스트에서 검증하지 않았습니다. 오래된 redroid 보안 패치는 별도의 남은 위험입니다.

<a id="stop-and-restart"></a>
## 중지와 재시작

```bash
docker compose down
docker compose up -d --no-build
```

`down`은 볼륨을 유지합니다. **`down -v`는 로그인 상태와 DB를 삭제하므로 일상적인 종료에 사용하지 마세요.**

원격 MCP가 있으면 `--profile dot`, 개인 터널도 있으면 `--profile tunnel`을 추가하세요. `./bridge stop`, `./bridge start`는 저장된 모드를 사용합니다. 공개 HTTPS는 별도 `dot-ingress`를 거쳐야 합니다. 읽기 전용 `docker/Caddyfile.public`에는 비밀값이 없고 UID 10001이 읽을 수 있어야 합니다(일반적으로 0644).

`adb-init`은 Android 생성 전에 수집기 공개 키 두 개만 준비합니다. 승인된 수집기는 root ADB를 사용할 수 있습니다. Android·device-state·iris-state를 함께 백업·복구하고 실행 중 키를 교체하지 마세요. Iris 인증 파일은 자동 관리하며 등록과 함께 교체됩니다.

반복 실패를 피하기 위해 redroid 자동 재시작은 꺼져 있습니다. 필요하면 `docker compose start redroid`를 사용하세요. 다른 장기 실행 서비스는 `unless-stopped`입니다. Linux 자동 복구는 `deploy/kakaocollector-supervisor.service.example`의 경로를 수정해 설치하세요. 감독 서비스는 30분 내 redroid 재시작을 3회로 제한합니다.

<a id="storage-locations"></a>
## 저장 위치

호환성을 위해 Compose 프로젝트·로컬 이미지의 `kakaotalk-collector`, Android 패키지 `dev.kakaocollector.bridge`, 수동 Lima 경로 `/srv/kakaotalk-collector`는 유지합니다. 새 설치의 VM 경로는 `/srv/kakaotalk-bridge`, 릴리스 이미지는 `ghcr.io/rokrokss/kakaotalk-bridge-*`입니다. 이름 변경을 적용해도 기존 `.env`의 `COMPOSE_PROJECT_NAME`을 유지해야 같은 볼륨을 사용합니다.

| 볼륨 | 내용 |
| --- | --- |
| `android-data` | 카카오톡 로그인·로컬 DB·등록 앱 데이터 |
| `collector-data` | 수집된 메시지와 서버 커서 |
| `device-state` | 등록 세대와 ADB 키 |
| `iris-state` | Iris 수집기 ADB 키 |
| `admin-state` | 암호화된 선택적 로컬 비밀번호와 취소 가능한 브라우저 세션 |
| `passkey-state` | 암호화된 공개 인증 정보, RP·출처 설정, 임시 인증 상태 |
| `dot-state` | OAuth·터널 승인, 원격 호출 성공 시각, 대화 이벤트 권한·구독·처리 커서·웹훅 대기열 |

서버는 매시간 기본 30일 이전 메시지를 정리합니다. `RETENTION_DAYS`로 변경하세요. 재전송 중복 제거도 이 기간 안에 적용합니다. Android DB, 이전 알림 격리 데이터, 백업 파일은 정리하지 않습니다. 컨테이너 로그는 각각 10 MB 파일 3개로 제한합니다.

<a id="back-up-the-collection-database"></a>
## 수집 DB 백업

```bash
./scripts/backup.sh
```

SQLite 온라인 백업 API로 일관된 사본을 만들고 AES-256-GCM으로 암호화합니다. `secrets/backup_key`를 백업과 분리해 보관하세요. 키를 잃으면 복구할 수 없습니다. 자동 삭제·원격 복제는 직접 구성해야 합니다.

복구 전에 API를 중지하세요.

```bash
docker compose stop api
./scripts/restore.sh backups/collector-TIMESTAMP.kcb
docker compose start api
./scripts/status.sh
```

인증 태그·DB 무결성·스키마를 검사합니다. `cursor_epoch`가 바뀌므로 API 소비자는 페이지 커서를 초기화해야 합니다. Iris는 복구된 서버 커서부터 이어갑니다.

스크립트가 실행되는 호스트의 Docker Engine을 사용합니다. 수동 Lima에서는 VM 내부에서 실행하세요.

```bash
limactl shell --workdir=/srv/kakaotalk-collector kakaotalk-test sudo ./scripts/backup.sh
```

<a id="back-up-android-and-mcp-state"></a>
## Android·MCP 상태 백업

볼륨 7개와 맞는 설정·키를 함께 보관하는 [전체 백업](onboarding.md#maintain-and-recover)을 권장합니다. 수동 스냅샷은 redroid·admin·수집기 두 개를 중지하고 `android-data`, `device-state`, `iris-state`와 맞는 수집 상태·키를 함께 암호화해 보관하세요. Android에는 Iris bearer, 수집기 볼륨에는 승인된 ADB 식별 정보가 있습니다. 같은 계정으로 원본·복원 인스턴스를 동시에 실행하지 마세요. 새 등록 세대가 필요한 수동 복구에는 다음을 사용합니다.

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

보조 기기 로그인을 다시 확인해야 합니다. 남은 DB 메시지를 새 세대로 다시 읽으므로 기존 기록과 중복될 수 있습니다.

수집 DB 백업에는 `admin-state`, `dot-state`, `passkey-state`가 없습니다. 파일 복사 전에 admin·dot-plugin·dot-control을 중지하거나 SQLite 온라인 백업을 사용하세요. 맞는 `secrets/admin_token`, `secrets/mcp_storage_key`, `secrets/mcp_approval_token`, `secrets/mcp_passkey_token`도 유지하세요. 실행 중 DB 파일만 복사하면 WAL의 데이터가 빠질 수 있습니다. 전체 복원은 패스키를 유지하고 브라우저 세션·OAuth·콜백을 지우지만 수동 파일 복사는 정리 작업을 수행하지 않습니다.

<a id="renew-certificates"></a>
## 인증서 갱신

기본 TLS 인증서는 365일간 유효합니다. 갱신할 때 같은 게이트웨이 IP를 SAN에 넣고 게이트웨이를 재시작하세요. 등록 앱의 신뢰 인증서도 bootstrap으로 갱신해야 하므로 두 기기 로그인을 다시 확인할 시간을 확보하세요. Bridge 서명 키를 바꾸면 앱 업데이트가 불가능합니다.
