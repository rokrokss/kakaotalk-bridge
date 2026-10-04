# kakaotalk-mcp-events

물리 태블릿 없이 **Linux 서버의 redroid를 가상 보조 태블릿으로 실행하고, Iris로 카카오톡 DB를 읽는** Docker Compose 패키지입니다. Apple Silicon의 Lima Ubuntu 환경에서 보조 로그인과 Iris 메시지 수집을 확인했고, 사용자가 핸드폰 로그인 유지도 직접 확인했습니다. 다른 호스트·카카오톡 버전과 장시간 운영은 별도 검증이 필요합니다.

**필수 인수 조건: 핸드폰의 기존 카카오톡 세션을 유지하는 보조 태블릿 로그인만 허용합니다.** 해상도나 `tablet` 속성만으로 이 조건을 충족했다고 판정하지 않습니다. 설치 직후에는 수집이 잠기며, 보조 기기 로그인 옵션의 선택 여부와 운영자의 양쪽 세션 확인이 필요합니다. 이 소프트웨어가 카카오톡의 로그인 동작을 통제하거나 핸드폰 로그아웃을 절대 방지하는 것은 아닙니다.

## 구성

```text
redroid [가상 보조 태블릿: 카카오톡 + Iris 읽기 전용 프로세스 + 등록 앱]
    → loopback ADB forward → iris-collector → Python API → SQLite
                                               ↳ HTTPS 조회 / MCP(stdio)
브라우저 → HTTPS /admin/ → 관리자 UI → ADB 화면·입력·로그인 확인
device-agent → ADB 상태 점검 → 상태 API
```

- redroid 안의 Iris가 로컬 카카오톡 DB를 읽습니다. 물리 태블릿이나 Termux는 필요하지 않습니다.
- 고정된 Iris 소스에 읽기 전용 진입점을 추가해 빌드합니다. 전송·파일 삭제·토큰 조회 기능은 실행하지 않습니다. [변경 및 소스 제공](iris/NOTICE.md).
- 첫 실행은 redroid DB에 남아 있는 행부터 읽습니다. 이후 서버에 commit된 마지막 `_id` 다음부터 이어 읽습니다. 휴대폰의 전체 과거 대화가 redroid에 동기화된다고 보장하지 않습니다.
- 메시지·방·발신자 ID를 문자열로 보존합니다. 같은 본문을 여러 번 보낸 메시지는 각각 남습니다.
- 메시지 본문과 종류를 수집하며 사진 원본·첨부 복호화·표시 이름·수정/삭제 반영은 이번 구현에 포함하지 않습니다.
- 기존 알림 Bridge는 등록/로그인 확인 UI로 남습니다. 새 bootstrap의 Iris 모드에서는 알림 관찰·업로드를 중단하며 알림 권한도 필요하지 않습니다.
- 관리자 웹 UI에서 화면 클릭·드래그·한글 입력·설치·보조 로그인 확인을 진행합니다. [웹 UI 사용법](docs/web-ui.md).
- 상세 동작과 제한: [Iris 운영 가이드](docs/iris.md).

## 준비

운영 호스트는 Docker Engine·Compose v2와 Android binder 지원 커널을 갖춘 Linux amd64/arm64입니다. 초기 검증 예산은 4 vCPU·8GB RAM이며 최저 사양 보장이 아닙니다. redroid에 필요한 binder/binderfs 구성은 호스트 커널에 맞게 준비하세요. 공유 메모리는 `androidboot.use_memfd=1`을 사용합니다.

호스트에는 Bash와 OpenSSL이 필요합니다. Python/JDK/Android SDK는 이미지 안에 포함됩니다. 선택적인 호스트 supervisor에는 Python 3.12+가 추가로 필요합니다. macOS Docker Desktop에서는 서버·APK 빌드를 할 수 있지만 여기서 전체 redroid 운영 호환성을 검증했다고 간주하지 않습니다.

Apple Silicon Mac에서 실기 테스트를 하려면 [Lima Ubuntu VM 구성](docs/local-redroid.md)을 사용합니다. Docker Desktop의 커널에 Binder가 없어 별도 Linux VM에서 컨테이너를 실행합니다. 실제 Android 14 부팅·admin 화면 조작·카카오톡 보조 로그인·Iris 신규 메시지 수집을 확인했습니다. 핸드폰 로그인 유지는 사용자의 직접 확인 기록이며 자동 감시 결과가 아닙니다.

Android SDK 빌드 단계는 Linux amd64 도구를 사용합니다. arm64 빌드 머신에서는 Docker의 amd64 실행 지원이 필요합니다(Docker Desktop은 해당 기능을 제공합니다). 일반 arm64 Linux에 이 기능이 없다면 amd64 빌드 머신에서 device 이미지의 arm64 타깃을 빌드한 뒤 전달하세요. 런타임의 Python/ADB는 선택한 타깃 아키텍처의 네이티브 패키지이며 Bridge APK는 공통입니다. 카카오톡 APK는 별도로 ABI가 맞아야 하며, amd64 redroid의 ARM 앱 번역 계층 호환성은 G0에서 확인합니다.

## 설치와 실행

```bash
cp .env.example .env
./scripts/preflight.sh
./scripts/init-secrets.sh
```

`DEVICE_SUBNET`/`GATEWAY_IP`가 LAN·VPN·다른 Docker 네트워크와 겹치면 **키 생성 전에** `.env`에서 바꾸세요. `DEVICE_IP_RANGE`도 해당 서브넷 내부로 맞추되 고정 `GATEWAY_IP`를 포함하지 않도록 설정합니다. Docker 재시작 시 다른 컨테이너가 gateway 주소를 먼저 배정받는 충돌을 방지합니다. 기본 gateway는 Docker 네트워크 내부 `172.29.87.3:8443`이며 Android에 이 IP를 전달합니다. API는 호스트에 직접 노출하지 않고, HTTPS와 ADB는 기본적으로 호스트 loopback에만 게시합니다. `.env`는 제공된 셸 호환 `KEY=value` 형식을 유지하세요.

정식 카카오톡 APK를 `inputs/kakao/`에 넣으세요. split APK인 경우 같은 버전·서명의 전체 설치 세트를 넣습니다. 카카오톡 APK나 계정 정보는 이미지에 포함되지 않습니다. 카카오톡을 redroid에 이미 설치했다면 해당 디렉터리를 비워 둘 수 있습니다.

```bash
docker compose build api device-agent
docker compose up -d
```

웹의 초기 설치(또는 CLI bootstrap)는 제공한 카카오톡 APK와 자체 서명 등록 앱을 설치하고, 빌드된 Iris APK를 redroid에 배치합니다. Iris는 Android 앱 화면으로 설치하지 않고 root `app_process`로 실행합니다. 전용 redroid의 root ADB가 필요하며 로그인·채팅방 열기는 실행하지 않습니다. 실패 시 앱 데이터를 지우지 말고 출력된 단계를 확인하세요. setup은 기존 볼륨과 서명 키를 유지한 상태로 재실행할 수 있습니다.

### 웹에서 설치와 로그인

원격 Linux 서버라면 PC에서 HTTPS 포트를 터널링합니다. PC에 ADB나 scrcpy를 설치할 필요는 없습니다.

```bash
ssh -N -L 18443:127.0.0.1:8443 user@linux-server
```

브라우저에서 `https://localhost:18443/admin/`을 엽니다. 서버 자체 브라우저에서는 `https://localhost:8443/admin/`입니다. 설치 시 생성된 `secrets/tls_cert.pem` 인증서를 확인해 신뢰한 후 접속하세요. HTTPS 인증서 검증을 해제하는 운영 옵션은 제공하지 않습니다.

1. 서버의 `secrets/admin_token` 값을 **관리자 키**에 입력합니다. 이 값은 카카오 비밀번호와 다릅니다. 관리자 키를 채팅이나 URL에 붙여 넣지 않습니다.
2. CLI bootstrap을 아직 하지 않았다면 **초기 설치**를 누릅니다. 제공한 카카오 APK 설치, Iris 배치, 등록 앱/웹 입력기 준비를 수행합니다. 기존 등록에서 재실행하면 수집 확인을 초기화합니다.
3. **카카오톡 열기 → 입력 연결**을 누르고, 화면의 아이디/비밀번호 입력칸을 클릭한 다음 웹 입력칸으로 값을 전달합니다. 입력은 현재 선택된 카카오톡 입력칸에 추가됩니다.
4. 로그인 화면의 **‘다른 기기와 함께 사용’**을 선택한 뒤 **보조 로그인 옵션 검사**를 누릅니다. 검사 통과 후에 화면의 로그인 버튼을 직접 누릅니다. 옵션이 없거나 주 기기 이전을 요구하면 중단합니다.
5. 핸드폰 기존 로그인과 redroid 로그인을 직접 확인하고 두 체크박스를 선택한 뒤 **확인하고 Iris 수집 활성화**를 누릅니다. 사전 검사 후 30분 안에 완료합니다.
6. 사용 후 **관리 화면 잠금**을 누릅니다. 관리자 세션은 로그인부터 30분 뒤 만료됩니다. 카카오톡 자체 로그아웃 버튼이 아닙니다.

수집 활성화는 운영자의 확인을 기록합니다. 핸드폰 로그아웃을 절대 방지하거나 핸드폰 세션을 자동 감시하지는 않습니다. 직접 채팅방을 열거나 Enter를 누르면 카카오톡 동작/읽음 상태에 영향을 줄 수 있습니다. 로그인 및 입력은 자동 제출하지 않습니다.

admin 상단의 **현재 상태 검사**에서 redroid 로그인 화면 관찰, 보조 로그인 사전 검사 유효시간, 수집 승인 상태 및 핸드폰의 마지막 직접 확인 시각을 조회합니다. 화면 검사 결과는 60초가 지나거나 기기를 조작하면 재검사를 요구합니다. 핸드폰은 연결되어 있지 않으므로 현재 세션의 자동 확인 결과로 표시하지 않습니다. 직접 확인 후 **핸드폰 유지 확인 시각 갱신**으로 기록하며, 24시간이 지나면 재확인 필요로 표시합니다. **핸드폰 로그아웃됨 · 수집 중단**은 로그아웃 보고와 수집 승인 해제를 수행합니다. 이 보고 후에는 사전 검사와 양쪽 확인을 다시 거쳐야 합니다.

웹 UI는 약 1.2초 간격의 스크린샷 조작 방식입니다. 실제 화면 갱신 속도는 ADB와 네트워크에 따라 달라집니다. 로그인 UI, 한글 입력기와 핸드폰 세션 유지는 실제 redroid 환경에서 검증해야 합니다.

CLI의 `login-check`, `confirm-secondary`는 계속 사용할 수 있습니다. 웹 설치 작업과 CLI bootstrap을 동시에 실행하지 마세요. `--tablet-session-active`는 물리 태블릿이 아닌 redroid 세션 확인을 뜻합니다. [상세 안내](docs/web-ui.md).

## 조회

HTTPS 인증서는 설치마다 생성하며 hostname 검증을 생략하지 않습니다. 아래 예시는 서버 자체에서 실행합니다. 원격 조회는 HTTPS 포트도 SSH 터널로 연결할 수 있습니다.

```bash
# 인증 헤더를 프로세스 인자로 노출하지 않고 curl 설정을 stdin으로 전달
{ printf 'header = "Authorization: Bearer '; tr -d '\n' < secrets/read_token; printf '"\n'; } |
  curl --config - --cacert secrets/tls_cert.pem https://127.0.0.1:8443/v1/messages
```

| API | 용도 |
| --- | --- |
| `GET /v1/messages?after=0&limit=50` | 관찰한 메시지 후보를 수집 순서로 조회 |
| `GET /v1/search?q=검색어&after=0&limit=50` | 본문의 literal 부분 문자열 검색 |
| `GET /v1/conversations?after=0&limit=50` | 방 식별 후보; 고유 방 목록이 아님 |
| `GET /v1/status` | 수집 상태·누락 구간·대기열 |
| `GET /health/live`, `/health/ready` | 프로세스·DB 상태 |

모든 `/v1/*` 경로에 read 토큰이 필요합니다. ingest와 device 토큰으로 조회할 수 없습니다. 페이지 `next_cursor`를 다음 `after`로 보내고 `has_more`를 확인합니다. `coverage.cursor_epoch`가 바뀌면 백업 복원이 있었으므로 소비자 cursor를 초기화해야 합니다. `pruned_through_cursor` 이하의 데이터는 보관 기간에 따라 삭제되었습니다.

Iris 메시지는 `source=iris_db`, `database_ref`에 DB 메시지·방·발신자 ID를 제공합니다. `conversation_ref`는 기기/등록 epoch/방 ID로 범위를 구분합니다. `/v1/conversations`는 관찰 순서의 방 참조로 같은 방이 반복될 수 있습니다. 이전 알림 기록은 계속 조회할 수 있으며 해당 기록의 `conversation_ref`는 `null`입니다.

`collecting_partial`은 최근 DB 조회 및 운영자의 보조 기기 확인이 유효하다는 뜻입니다. 핸드폰 로그인, 메시지 무누락, 읽음 유지의 자동 검증을 의미하지 않습니다. DB에 아직 수신되지 않았거나 이미 삭제된 행은 복구할 수 없습니다.

## ChatGPT Dot / MCP Events

`dot-plugin` Docker 서비스가 OAuth로 보호된 HTTPS MCP 2.0을 제공합니다. 현재 필수 범위는 ChatGPT 플러그인 연결과 요청 시 메시지 조회·검색·수집 상태 확인입니다. **자동 이벤트 구독은 요구사항과 완료 조건에서 제외합니다.** 플러그인 연결이나 서버 시작 시 Dot 작업·구독을 자동 생성하지 않습니다.

구현된 `message.created` 웹훅은 별도 요청으로 구독할 수 있는 선택 기능입니다. 해당 기능을 사용할 때 Dot은 이벤트로 깨어난 뒤 미처리 메시지 도구로 본문을 읽고 처리 완료 커서를 기록합니다. 이벤트 본문이 Dot 실행에 전달되지 않는 경우에도 같은 조회 경로를 사용합니다.

원격 플러그인에는 읽기/검색/상태/처리 커서 도구 7개가 있으며, 카카오톡 전송이나 기기 조작 기능은 없습니다. `docker compose --profile dot up -d dot-plugin`으로 실행하기 전에 공개 HTTPS origin과 전용 secret을 준비해야 합니다. [연결·배포·선택적 구독과 검증 기록](docs/dot-plugin.md)을 참고하세요.

## MCP 연결 (기존 stdio)

API가 실행 중일 때 MCP 클라이언트가 다음 stdio 프로세스를 실행하도록 설정하세요. `/absolute/path/kakaotalk-mcp`는 실제 프로젝트 경로로 바꿉니다.

```json
{
  "mcpServers": {
    "kakaotalk": {
      "command": "docker",
      "args": ["compose", "--project-directory", "/absolute/path/kakaotalk-mcp", "--profile", "mcp", "run", "--rm", "--no-deps", "-T", "mcp"]
    }
  }
}
```

도구: `get_recent_messages`, `search_messages`, `list_conversations`, `get_collector_status`. 원격 서버라면 SSH로 위 명령을 실행하는 stdio 연결을 사용합니다. MCP 서비스는 `up`으로 상시 실행하는 대신 클라이언트가 `run`으로 시작합니다.

## 운영·복구

- `android-data`: 카카오톡 세션과 Bridge outbox. `collector-data`: 수집 DB. `device-state`: 등록 epoch와 ADB 키. `iris-state`: 수집기의 ADB 키(수집 커서는 서버 DB에 보관).
- 이 영속 볼륨에는 메시지와 인증 상태가 저장됩니다. 저장 시 암호화는 호스트 디스크/볼륨에서 제공해야 합니다. Compose가 볼륨 자체를 암호화하지는 않습니다.
- 일반 종료는 `docker compose down`입니다. `down -v`는 계정 상태·DB를 삭제하므로 운영 절차에서 사용하지 않습니다.
- API/gateway/admin/device-agent/iris-collector는 종료 시 재시작합니다. redroid는 무한 재시작을 막기 위해 기본 자동 재시작을 끄고 `docker compose start redroid`로 복구합니다. 자동 복구가 필요하면 `deploy/kakaocollector-supervisor.service.example`의 경로를 맞춰 Linux systemd에 설치합니다. 이 supervisor만 redroid를 재시작하며 30분 내 3회로 제한합니다.
- Iris 수집기는 기본 3초마다 최대 50행씩 조회합니다. 밀린 행이 있으면 계속 읽습니다. 실제 수신 지연은 카카오톡/redroid 환경에 따라 달라집니다.
- 잘못된 행, 복호화 실패, 앱 버전 변경, DB 교체 또는 `_id` 역행은 건너뛰지 않고 수집을 중단합니다. `docker compose logs --tail 30 iris-collector`와 `/v1/status`로 확인합니다. DB가 교체되면 원인을 확인하고 등록 epoch를 새로 만들어 보조 로그인도 다시 확인해야 합니다.
- 서버 관찰/본문은 기본 30일마다가 아니라 **30일 초과 데이터를 매시간** 정리합니다. 재전송 중복 제거도 이 보관 범위 안에서 보장됩니다. Android 카카오톡 자체 데이터, quarantine, 백업 보관은 별도입니다.
- 로그에는 본문·토큰을 기록하지 않습니다. 각 컨테이너 로그는 10MB×3으로 제한합니다.
- `secrets/` 디렉터리는 0700입니다. 파일은 컨테이너 UID가 읽을 수 있게 일부 0444이며 부모 디렉터리 권한으로 호스트의 타 사용자 접근을 제한합니다. 이 디렉터리, 이미지 빌드에 사용한 Bridge 서명 키, `.env`를 안전하게 보관하세요.
- TLS 인증서는 기본 365일입니다. 갱신 시 같은 gateway IP를 SAN에 포함하고 gateway를 재시작한 뒤 bootstrap을 재실행해 Bridge의 신뢰 인증서를 갱신합니다. 서명 키를 바꾸면 APK 업데이트가 실패하므로 기존 키를 유지합니다.

### 암호화 DB 백업

```bash
./scripts/backup.sh
# 복원은 수집 서버를 정지한 후 실행
docker compose stop api
./scripts/restore.sh backups/collector-TIMESTAMP.kcb
docker compose start api
./scripts/status.sh
```

SQLite 온라인 backup API로 일관된 snapshot을 만들고 AES-256-GCM으로 암호화합니다. 복원은 인증 태그·SQLite 무결성·schema를 확인한 후 교체합니다. `secrets/backup_key`를 잃으면 복원할 수 없으므로 백업 파일과 별도로 보관하세요. 백업 자동 삭제/원격 복제는 포함하지 않았습니다. 7일 보관을 초기 운영 정책으로 권장합니다.

Android 볼륨 백업은 redroid를 정지하고 호스트의 암호화된 스냅샷 기능으로 `android-data`와 `device-state`를 함께 보관하세요. 원본과 복원본을 같은 계정으로 동시에 켜지 않습니다. Android snapshot을 복원한 경우 새 관찰 epoch를 부여합니다.

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

Iris는 새 epoch에서 redroid에 남아 있는 DB 행을 다시 읽습니다. 이전 epoch의 기록과 중복될 수 있으며 방 참조 범위도 달라집니다. 보조 로그인 재확인 후에만 수집을 활성화합니다. 기존 알림 outbox는 자동 삭제하지 않지만 Iris 모드에서 전송하지 않습니다.

## 개발과 검증

```bash
uv sync --frozen --python 3.12
uv run pytest -q
uv run ruff check server device tests deploy scripts/smoke.py
docker compose config --quiet
docker compose build api device-agent
./scripts/smoke.sh
```

smoke 테스트는 독립적인 `kakaocollector-smoke-PID` Compose 프로젝트에 합성 Iris DB 행을 넣어 HTTPS·인증·재전송·영속성·암호화 백업·MCP 도구 호출을 확인하고 해당 테스트 볼륨만 제거합니다. redroid나 실제 카카오 계정을 사용하지 않습니다. 테스트에는 uv 또는 프로젝트 의존성을 설치한 호스트 Python 3.12+가 필요합니다. 기본 테스트용 subnet은 `172.29.88.0/24`, 포트는 18443입니다.

Python 의존성은 `uv.lock`과 해시가 포함된 `requirements.lock`으로 고정했습니다. 수정 시 `uv export --frozen --no-dev --no-emit-project --output-file requirements.lock`로 동기화합니다. Docker 기반 이미지는 multi-arch digest로 고정했습니다. Android 빌드는 `assembleRelease`, `lintRelease`, `apksigner verify`를 수행합니다.

설계: [docs/design.md](docs/design.md). 구현/검증 결과는 [docs/implementation.md](docs/implementation.md)에 기록합니다.
