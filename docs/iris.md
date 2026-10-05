# Iris 수집 구현

[README](../README.md) · [운영과 복구](operations.md)

<a id="components-and-assumptions"></a>

## 구성과 전제

Linux 서버의 redroid를 보조 태블릿으로 사용하므로 별도 실물 태블릿은 필요하지 않습니다. 기존 휴대폰이 주 기기입니다. Iris는 redroid 안에서 root `app_process`로, Python `iris-collector`는 별도 Docker 컨테이너로 실행됩니다. Termux나 PC 카카오톡은 사용하지 않습니다.

태블릿 크기와 모델 속성만으로 보조 로그인이 보장되지는 않습니다. 공식 카카오톡 APK의 실제 한국어 로그인 화면에서 **다른 기기와 함께 사용**이 선택됐는지 확인하세요. 로그인 후 운영자가 휴대폰과 redroid의 로그인이 모두 유지되는지 확인해야 합니다. 코드는 휴대폰 로그아웃을 막거나 휴대폰 세션을 감시하지 않습니다. Apple Silicon의 Lima에서 보조 로그인과 새 메시지 수집을 검증했고, 휴대폰 로그인 유지는 사용자가 직접 확인했습니다.

<a id="running-the-collector"></a>

## 수집기 실행

화면 제어, 설치, 로그인 확인은 [웹 관리 화면](web-ui.md)을 기본으로 사용하세요. 아래 CLI는 같은 웹 작업의 대안이므로 동시에 사용하지 마세요.

[Linux 설치](install.md)에 따라 커널·키·공식 카카오톡 APK를 준비한 뒤 실행합니다.

```bash
docker compose build api device-agent gateway
docker compose up -d
docker compose --profile setup run --rm bootstrap
```

관리 화면에서 redroid를 열고 한국어 로그인 화면의 보조 기기 옵션을 선택하세요. 별도 scrcpy 클라이언트는 승인된 ADB 키가 필요하며 포트 포워딩만으로 접근할 수 없습니다. 로그인 버튼을 누르기 전에 실행합니다.

```bash
docker compose --profile setup run --rm bootstrap login-check
```

검사 통과 후 보조 기기로 로그인하고 기존 휴대폰 로그인이 유지되는지 확인하세요. 30분 안에 실행합니다.

```bash
docker compose --profile setup run --rm bootstrap confirm-secondary \
  --phone-session-active --tablet-session-active
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`--tablet-session-active`는 redroid 세션을 확인합니다. Bridge에는 알림 접근 권한이 필요하지 않습니다. 이전 알림 수집 버전에서 옮길 때는 새 이미지로 bootstrap을 다시 실행해야 하며, 확인 기록이 초기화되므로 운영자가 참여해야 합니다. 검증되지 않은 보조 로그인 절차를 추측하거나 주 기기 이전으로 진행하지 마세요.

<a id="iris-build-and-runtime-boundaries"></a>

## Iris 빌드와 실행 경계

- 원본: [dolidolih/Iris](https://github.com/dolidolih/Iris), 커밋 `ee1dc978ec465df11642596e40f74caff497301d`.
- 빌드 시 압축 파일의 SHA-256 `1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0`을 확인합니다.
- 수정 빌드는 `iris/CollectorMain.kt`를 추가합니다. 원본 `Main`을 실행하지 않고 DB 읽기와 Iris 복호화만 사용합니다. Android SQLite `OPEN_READONLY`로 DB를 엽니다.
- 원본의 메시지 전송, 알림 폴링, 파일 삭제, 대시보드, `/query`, `/reply`, `/aot`는 실행하지 않습니다. 제한된 고정 SELECT용 `/collector/rows`, `/collector/metadata`와 빌드 확인용 `/collector/health`만 제공합니다.
- Android `127.0.0.1:3000`에만 바인딩하고 수집기 내부 루프백 ADB 포워딩으로 접근합니다. Compose는 호스트에 3000 포트를 공개하지 않습니다. root ADB 권한이 있는 호스트·컨테이너는 신뢰 경계 안에 있습니다.
- Iris v4는 DB 접근 전에 등록별 무작위 bearer로 인증합니다. 인증 파일은 `/data/kakaocollector-iris`(0700) 안에 root 소유·0600으로 저장합니다. nonce/HMAC 상태 확인으로 리스너를 검증한 뒤 Python이 bearer를 보냅니다. 키는 로그나 프로세스 인수에 넣지 않습니다.
- `adb-init`이 Android 시작 전에 기존 기기·Iris 수집기 공개 키를 등록합니다. `ro.adb.secure=1`은 미등록 ADB 클라이언트를 거부하고, 승인된 수집기는 Iris에 필요한 root 권한을 사용합니다. 개인 키는 상태 볼륨에 남으므로 Android 데이터와 함께 백업·복구하세요.
- 요청마다 등록 모드, 보조 로그인 확인, Android 지문, 카카오톡 versionCode를 검사합니다. Python도 페이지 조회 전후와 각 행 전송 전에 태블릿 설정과 등록을 검사합니다.
- APK는 앱 설치용 서명 패키지가 아니라 `app_process` 빌드 산출물입니다. bootstrap은 읽기 전용으로 배포하고, 수집기는 시작 시 이미지 안 APK와 SHA-256을 비교합니다.
- GPL·MIT 고지와 대응 소스는 이미지의 `iris/NOTICE.md`, `/opt/iris-source.tar.gz`, `/opt/iris-overlay/`, `/opt/iris-build.Dockerfile`에 포함됩니다. 배포 시 소스와 고지를 함께 제공하세요.
- Netty는 `4.1.138.Final`로 맞췄으며 `/opt/iris-dependencies.txt`에 실제 의존성 그래프를 보관합니다. [보안 수정과 남은 Android 패치 문제](security.md#security-fixes-2026-10-05)를 참고하세요.

<a id="storage-and-recovery"></a>

## 저장과 복구

초기 커서는 0입니다. 수집기는 redroid 카카오톡 DB에 현재 존재하는 행을 `SYNCMSG` 같은 동기화 행을 포함해 한 번에 최대 50개 읽습니다. 휴대폰 전체 기록이나 카카오 서버의 모든 기록에는 접근할 수 없습니다.

`_id`, `chat_id`, `user_id`는 문자열로 전달합니다. 이벤트 ID는 Iris 등록 세대, DB 식별자, 로그 ID로 만듭니다. 본문이 같아도 로그 ID가 다르면 별개이며 관측 시각만 다른 재전송은 중복 응답을 받습니다. 불변 행에는 대화·발신자 ID를 저장합니다. 별도 메타데이터 갱신이 행 식별자와 재전송 다이제스트를 바꾸지 않고 지원되는 표시 이름을 조회합니다. [메시지 조회](mcp-queries.md#names)를 참고하세요.

수집기는 행마다 커밋 응답을 기다리고 서버는 행과 최신 커서를 같은 SQLite 트랜잭션에 저장합니다. 응답 유실·재시작 후에는 로컬 커서 파일 대신 서버 커서를 다시 조회합니다. 잘못된 행을 건너뛰고 다음 커서를 저장하지 않습니다. 앱 DB가 원본 대기열이므로 서버 중단 중 앱에서 삭제된 행은 복구할 수 없습니다.

보관 기간 정리로 메시지를 지워도 Iris 커서는 유지합니다. 암호화 DB 백업에도 커서를 포함하며 복구 후 해당 커서에서 재개합니다. DB 파일의 device/inode가 바뀌거나 최대 ID가 줄면 수집을 멈추고 새 DB를 자동 승인하지 않습니다. 같은 파일·ID를 재사용하는 변경이나 기존 행 수정·삭제는 완전히 감지할 수 없습니다.

초기 범위, 삭제된 행, 늦은 동기화 때문에 `coverage.complete=false`를 유지합니다. 정상 heartbeat는 Iris의 DB 접근 가능 여부이며 카카오 서버 연결이나 휴대폰 로그인 확인이 아닙니다. 이전 알림 메시지는 `source=notification`, 새 DB 메시지는 `source=iris_db`입니다.

<a id="current-limits-and-operational-validation"></a>

## 현재 제한과 운영 검증

본문은 UTF-16 코드 단위 16,384개로 제한하고 잘림 여부를 표시합니다. 행 본문, 종류, ID, 시각, 출처, isMine을 수집하며 표시 이름은 별도로 조회합니다. Iris v4는 카카오톡 26.8.2의 `crypto_user_database`를 SQLCipher로 읽기 전용 접근합니다. 정확한 발신자 ID로 일반 프로필을, 채널·대화 ID 쌍으로 PlusChat 이름을 찾습니다. 암호는 Android의 기존 설정에서 도출하며 생성·기록·외부 전송하지 않습니다.

현재 오픈채팅 프로필이 없으면 API가 같은 방의 보관된 입장·퇴장 이벤트에서 닉네임을 가져오고 과거 이름과 관측 시각임을 명시합니다. 두 근거가 모두 없으면 미확인 상태를 유지합니다. 원본 첨부 파일과 수정·삭제 동기화는 지원하지 않습니다. JSON·복호화 오류는 해당 페이지를 중단시키며 암호문을 정상 본문으로 저장하지 않습니다.

새 환경에서는 다음을 확인해야 하며, 남은 검증 범위이기도 합니다.

1. 커널·binder, 카카오톡 APK ABI, root DB 접근 호환성.
2. 보조 로그인 옵션과 기존 휴대폰 로그인 유지.
3. 일반·알림 끈 방, 화면 꺼짐, 본인 메시지, 동기화 메시지의 수신·복호화.
4. 수집 전후 읽음 상태, 앱·컨테이너 재시작, 네트워크 단절 후 수집 재개.
5. 24–72시간 연속 수신과 디스크 사용량.

로컬 API 테스트와 APK 빌드 성공만으로 이 검증을 대신할 수 없습니다.
