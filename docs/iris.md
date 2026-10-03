# redroid + Iris 운영 가이드

## 구성과 전제

별도 태블릿 없이 Linux 서버의 redroid가 보조 태블릿 역할을 한다. 기존 핸드폰은 주 기기로 남는다. Iris는 redroid 내부에서 root `app_process`로 실행하며, Python `iris-collector`는 별도 Docker 컨테이너에서 동작한다. Termux나 PC 카카오톡을 사용하지 않는다.

redroid의 태블릿 크기/모델 속성은 보조 로그인 보장이 아니다. 정식 카카오톡 APK의 실제 로그인 화면에서 ‘다른 기기와 함께 사용’ 선택을 확인하고, 로그인 후 휴대폰과 redroid 양쪽 세션이 유지됨을 운영자가 확인해야 한다. 코드가 휴대폰 로그아웃 자체를 막거나 휴대폰 세션을 감시하는 것은 아니다. 이 실기 검증은 아직 수행하지 않았다.

## 실행

기본 운영 방법은 [관리자 웹 UI](web-ui.md)다. 화면 조작과 설치·로그인 확인을 브라우저에서 수행할 수 있다. 아래 CLI/scrcpy는 대체 경로이며 웹 작업과 동시에 실행하지 않는다.

README의 Linux 커널·시크릿 준비와 정식 Kakao APK 배치를 완료한 뒤:

```bash
docker compose build api device-agent
docker compose up -d
docker compose --profile setup run --rm bootstrap
```

scrcpy/SSH 터널로 redroid 화면을 열고, 한국어 로그인 화면에서 보조 기기 옵션을 선택한다. 로그인 버튼을 누르기 전에:

```bash
docker compose --profile setup run --rm bootstrap login-check
```

검사 통과 후 보조 기기로 로그인하고 핸드폰의 기존 세션 유지도 확인한다. 30분 안에:

```bash
docker compose --profile setup run --rm bootstrap confirm-secondary \
  --phone-session-active --tablet-session-active
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`--tablet-session-active`는 redroid 세션 확인이다. 별도 태블릿을 의미하지 않는다. Bridge의 알림 권한은 필요 없다. 이미 등록한 이전 알림 버전에서 전환할 때도 새 이미지로 bootstrap을 다시 실행해야 한다. 이 작업은 확인을 초기화하므로 무인 전환으로 취급하지 않는다. 확인되지 않은 보조 로그인 흐름을 추측하거나 주 기기 이전을 진행하지 않는다.

## Iris 빌드와 실행 경계

- 원본: https://github.com/dolidolih/Iris, commit `ee1dc978ec465df11642596e40f74caff497301d`.
- 아카이브 SHA-256 `1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0`를 빌드 중 확인한다.
- `iris/CollectorMain.kt`를 추가한 수정 빌드다. 원본 `Main`을 실행하지 않으며 DB 읽기·Iris 복호화만 사용한다. DB는 Android SQLite `OPEN_READONLY`로 연다.
- 원본의 메시지 전송, 알림 폴링, 파일 삭제, dashboard, `/query`, `/reply`, `/aot`를 시작하지 않는다. 고정 SELECT를 수행하는 `/collector/rows`와 빌드 확인 `/collector/health`만 제공한다.
- Android `127.0.0.1:3000`에만 바인딩하고 수집기 내부의 loopback ADB forward로 연결한다. Compose는 3000 포트를 호스트에 게시하지 않는다. root ADB 권한을 가진 호스트/컨테이너는 신뢰 경계 안에 있다.
- 매 요청에서 등록 모드·보조 로그인 확인·Android fingerprint·Kakao versionCode를 확인한다. Python 측도 태블릿 설정과 등록 상태를 페이지 조회 전후 및 행 전송 전에 확인한다.
- APK는 앱 설치용 서명 패키지가 아니라 `app_process`용 빌드 산출물이다. bootstrap은 읽기 전용 파일 권한으로 배치하고 수집기는 시작 시 이미지에 포함된 APK와 SHA-256을 비교한다.
- GPL/MIT 고지와 해당 소스는 `iris/NOTICE.md`, 이미지의 `/opt/iris-source.tar.gz`, `/opt/iris-overlay/`, `/opt/iris-build.Dockerfile`에 포함한다. 배포 시 소스와 고지도 함께 제공한다.

## 저장과 복구

최초 커서는 0이다. redroid 카카오톡 DB에 현재 남아 있는 행부터 최대 50개씩 읽으며 `SYNCMSG` 등의 동기화 행도 제외하지 않는다. 휴대폰 전체 이력 또는 서버에 있는 전체 이력에 접근하는 기능은 아니다.

`_id`, `chat_id`, `user_id`를 문자열로 전달한다. 이벤트 ID는 Iris 전용 등록 epoch, DB 식별자, log ID로 결정된다. 본문이 같아도 log ID가 다르면 다른 메시지다. 관찰 시각만 달라진 재전송은 중복 ACK를 반환한다. 방 이름/발신자 이름 대신 ID를 제공한다.

수집기는 한 행씩 commit ACK를 확인한다. 서버는 행과 마지막 커서를 같은 SQLite 트랜잭션에 저장한다. 응답 손실·수집기 재시작 시 서버 커서를 다시 조회하므로 로컬 커서 파일을 신뢰하지 않는다. 잘못된 행을 건너뛰고 이후 커서를 저장하지 않는다. 앱 DB가 원본 대기열 역할을 하므로, 서버 중단 동안 앱에서 지워진 행까지 복구할 수는 없다.

서버의 보관 기간 정리는 메시지를 삭제해도 Iris 커서를 보존한다. 암호화 DB 백업에는 커서도 포함된다. 서버 복원 후에는 복원 시점 커서부터 다시 읽는다. Android DB 교체(파일 device/inode 변경) 또는 최대 ID 역행은 중단하며, 자동으로 새 DB라고 승인하지 않는다. 같은 파일 안에서 같은 ID를 재사용하는 변형이나 기존 행의 수정/삭제를 완전히 감지하는 기능은 없다.

최초 수집 범위, 삭제된 행, 지연 동기화 때문에 항상 `coverage.complete=false`다. heartbeat 연결은 Iris DB 접근 가능성을 의미하며 Kakao 서버 연결이나 핸드폰 세션 유지의 증거가 아니다. 기존 알림 메시지는 `source=notification`, 신규 DB 메시지는 `source=iris_db`로 구분한다.

## 현재 제한과 운영 검증

본문은 16,384 UTF-16 코드 단위로 제한하고 잘림을 표시한다. 현재 수집 대상은 행의 본문·메시지 종류·ID·시간·origin·isMine이다. 첨부 원본, 표시 이름 조회, 메시지 수정/삭제 동기화는 미구현이다. JSON 또는 복호화 오류는 페이지 단위로 중단하며 ciphertext를 정상 본문으로 저장하지 않는다.

실제 Linux/redroid에서 확인할 사항:

1. 커널/binder, 카카오 APK ABI 및 root DB 접근 호환성.
2. 보조 로그인 옵션과 휴대폰 기존 세션 유지.
3. 일반방/음소거방/화면 꺼짐/본인 메시지/동기화 메시지의 DB 수신 및 복호화.
4. 수집 전후 읽음 표시, 앱·컨테이너 재시작, 네트워크 단절 뒤 재수집.
5. 24~72시간 장기 수신과 디스크 사용량.

로컬 API 테스트와 APK 빌드 성공을 위 항목의 성공으로 대신하지 않는다.

## Iris 최초 통합 검증 기록 (2026-10-04)

웹 입력기 추가 전의 기록이다. 현재 Bridge APK와 웹 UI 검증은 [웹 UI 검증 기록](web-ui.md#로컬-검증-기록-2026-10-04)을 따른다.

- `uv run pytest -q`: `47 passed, 1 warning in 1.51s`. 변경된 등록 거절, 서버 commit 후 ACK 유실, 재시작, DB 교체/역행, 미확인 수집 차단, 보관 기간 정리와 암호화 복원 후 커서를 합성 데이터로 검증했다.
- `uv run ruff check server device tests deploy scripts/smoke.py`: `All checks passed!`
- `docker compose config --quiet`, `git diff --check`: exit 0, 출력 없음.
- `./scripts/smoke.sh`: exit 0. 실제 Docker API/gateway/MCP/SQLite를 사용하되 Iris 입력 행은 합성 데이터다.

```text
PASS: synthetic Iris row, durable cursor and scoped conversation ID
PASS: TLS verification, authenticated ingest, duplicate retry, Korean text, read API, partial coverage
PASS: container stdio MCP calls all four read-only tools against the API
PASS: container restart preserves collected data
PASS: encrypted backup and verified restore inside non-root container
```

`./scripts/preflight.sh`는 현재 macOS 환경에서 다음과 같이 exit 1로 종료했다. 실제 redroid 운영 검증은 수행하지 않았다.

```text
Docker Compose version v2.40.3-desktop.1
Docker: linux/aarch64
FAIL: Full redroid deployment requires a prepared Linux host. API/APK builds can run here.
```

Docker/Android 빌드 및 산출물 검증도 완료했다.

- `docker compose build api device-agent`: exit 0, server/device `Built`.
- 최종 Iris 수정 후 `docker compose build device-agent`: exit 0, device `Built`.
- `docker buildx build --platform linux/amd64 -f docker/server.Dockerfile -t kakaotalk-collector/server:0.1.0-amd64 --load .`: exit 0.
- `docker buildx build --platform linux/amd64 -f docker/device.Dockerfile --secret id=bridge_keystore,src=secrets/bridge.jks --secret id=bridge_key_password,src=secrets/bridge_key_password -t kakaotalk-collector/device:0.1.0-amd64 --load .`: exit 0.
- 두 device 이미지에서 `import device.iris` 및 APK dex 안의 `CollectorMain` 존재를 확인했다. `PASS: linux/arm64 collector imports and Iris entrypoint is present in APK`, `PASS: linux/amd64 collector imports and Iris entrypoint is present in APK`.
- amd64 서버의 readiness/인증 조회: `PASS: linux/amd64 API readiness and authenticated status`.

Bridge `assembleRelease`/`lintRelease`/서명 검증, Iris `assembleRelease`를 Docker 빌드에서 실행했다. 최초 병렬 빌드의 Gradle 캐시 잠금 충돌은 BuildKit cache mount의 `sharing=locked`로 해결했다. upstream Iris의 deprecated Android API 컴파일 경고는 남아 있다.

이미지 태그는 server/device 각각 `0.1.0`(로컬 arm64), `0.1.0-amd64`이며 registry에 push하지 않았다. APK와 대응 소스/빌드 파일은 무시되는 `artifacts/`에 추출했다.

```text
bridge.apk SHA256 3a12167cccacda91aa8acb568714b3c8935a1644226f7776775e997b3f1c1453
iris.apk   SHA256 836860111c3c3ec840385cc74c52287bf07f52746e511a4ae77419ccefa2ff7f
```
