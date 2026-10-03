# 현재 구현: redroid + Iris + 웹 관리 UI

물리 보조 태블릿은 필요하지 않다. redroid가 가상 보조 태블릿이고, 그 내부 Iris가 DB를 읽는다. 새 bootstrap의 기본 수집원은 Iris다. HTTPS `/admin/`에서 화면 조작·설치·로그인 확인을 수행하는 웹 UI도 포함한다. [웹 UI 구현과 검증](web-ui.md)을 참조한다. 현재 구성·검증·제한은 [Iris 운영 가이드](iris.md)를 따른다.

---

아래는 **이전 알림 기반 MVP의 구현 및 검증 기록**이다. 아래 APK 해시와 빌드 결과를 현재 Iris 빌드의 검증 결과로 해석하지 않는다.

# 구현과 검증 기록

2026-10-04. 개인 단일 계정용 passive 수집 MVP. 실제 카카오톡 계정·Linux 운영 서버는 아직 연결하지 않았다.

## 핸드폰 로그인 유지 필수 조건

기존 구현은 `tablet` 속성만 설정했고 실제 보조 기기 판정은 미확인이었다. 사용자 요구에 따라 다음을 추가했다.

- bootstrap은 수집 잠금 상태로 설치한다. 오래된 등록 파일에 확인 필드가 없어도 잠근다.
- `login-check`는 태블릿 속성/크기와 카카오톡 한국어 로그인 화면의 ‘다른 기기와 함께 사용’ 체크박스 선택을 검사한다. 클릭·입력·로그인 제출 없이 UI를 읽고 임시 XML을 지운다. 식별 불가·미선택이면 중단한다.
- `confirm-secondary`는 유효한 사전 검사와 앱/기기 일치, 운영자의 핸드폰 및 태블릿 로그인 유지 확인을 모두 요구한다. 30분 지난 사전 검사는 재사용하지 않는다.
- Bridge는 확인 전 관찰 저장/전송을 하지 않는다. 앱 버전·Android fingerprint 변경 시 무효화한다. API도 확인된 최근 heartbeat가 없으면 HTTP 423을 반환한다.
- 이 확인은 운영자 진술이다. 핸드폰 세션 자동 감시, 카카오톡 인증 방식의 강제 변경, 임의 수동 로그인에 의한 로그아웃 방지는 제공하지 않는다.

실제 redroid에서 옵션 노출 및 핸드폰 세션 유지 검증은 아직 수행하지 않았다. **필수 조건을 충족했다고 판정할 수 없으며, 실제 검증 전에는 운영 준비 완료가 아니다.**

## 구현 범위

- Docker Compose: redroid, API, TLS gateway, device-agent, 일회성 bootstrap, stdio MCP.
- Kotlin APK: 카카오톡 알림만 추출, SQLite 트랜잭션 outbox, 동일 event ID 재전송, commit/duplicate ACK 후 제거, 거절 이벤트 quarantine, 명시적인 알림 접근 설정 UI.
- Python API: 수집/조회/기기 관리 토큰 분리, 1MiB 요청 제한, 단일 계정 바인딩, 이벤트 및 source_seq 충돌 검출, 관찰 기반 메시지 후보, cursor 조회·literal 검색, 부분 수집/누락 상태 표시.
- SQLite: WAL, 영속 볼륨, 보관 기간 정리, 온라인 snapshot의 AES-256-GCM 암호화 백업, 무결성 확인 후 offline 복원과 cursor epoch 변경.
- 읽기 전용 MCP 4개, APK 설치/등록 bootstrap, 읽기 전용 ADB 상태 점검, 선택적 Linux host supervisor의 영속 재시작 횟수 제한.
- 앱은 notification action/PendingIntent/RemoteInput을 호출하지 않고, 기기 관리 프로그램은 카카오톡을 실행하거나 채팅방을 열지 않는다.

## 목표 설계와 이번 구현의 차이

| 항목 | 이번 구현 |
| --- | --- |
| UI 수집 | 미포함. 읽음 허용 여부가 미확정이며 기본 passive만 구현 |
| 알림 간 의미상 중복 병합 | 미구현. 재전송만 제거하고 겹치는 관찰은 ambiguity로 표시 |
| 고유 방 ID | 미확인. notification key와 title을 방 식별 후보로만 제공 |
| 검색 | SQLite literal 부분 문자열 검색. FTS 인덱스는 미도입 |
| heartbeat | 연결된 listener는 30초마다 작업 예약, WorkManager 15분 복구; 서버 stale 기준 180초 |
| outbox 보관 | 자동 삭제 없이 payload 100MiB 한도. 72시간은 오래된 대기열 경보 기준 |
| quarantine | 자동 삭제/수정 UI 미포함. reject된 payload는 앱 전용 DB에 보존하며 상태에 표시 |
| 서버 보관 | 기본 30일, 매시간 정리. 중복 제거 기록도 같은 기간 보관 |
| gateway | Docker 내부 고정 IP와 자체 서명 TLS. 호스트 포트는 loopback 기본 |
| snapshot/암호화 | DB backup/restore 자동화. Android 데이터는 정지 후 호스트 암호화 snapshot 운영 절차 |
| 원격 이미지 배포 | 로컬 빌드 이미지 제공. registry 업로드는 수행하지 않음 |
| GMS 및 카카오 APK | 이미지에 번들하지 않음. 실제 앱 수신 호환성은 G0/G1 검증 필요 |

`collecting_partial`은 최근 리스너 연결 상태이지 카카오톡 로그인/서버 연결의 증거가 아니다. 메시지가 없거나 알림이 억제되면 무누락을 판정할 수 없다. 과거 전체 이력·첨부 원본·보낸 메시지 전체 수집을 지원한다고 표시하지 않는다.

## 로컬 검증

검증 환경: macOS arm64 호스트, Docker Desktop의 Linux arm64 엔진, Python 3.12. amd64 이미지는 같은 엔진의 에뮬레이션으로 빌드·기동 확인했다. amd64 물리 서버에서 redroid를 검증한 결과는 아니다.

- `uv run pytest -q`: 30 passed, 1 warning. 선택되지 않은 옵션·다른 앱 화면·만료된 검사·세션 확인 누락·미확인 수집 차단을 추가 검증. HTTPX TestClient 관련 upstream deprecation warning 1개.
- `uv run ruff check server device tests deploy scripts/smoke.py`: All checks passed!
- `docker compose config --quiet`: exit 0, 출력 없음.
- `docker compose build api`: 서버 이미지 빌드 성공.
- `./scripts/smoke.sh`: 아래 네 결과 모두 PASS, exit 0.
- `docker compose build device-agent`: `BUILD SUCCESSFUL in 1m 11s`, `kakaotalk-collector/device:0.1.0 Built`. 빌드 단계에서 `assembleRelease`, `lintRelease`, `apksigner verify` 수행.
- `docker buildx build --platform linux/amd64 -f docker/server.Dockerfile -t kakaotalk-collector/server:0.1.0-amd64 --load .`: exit 0.
- `docker buildx build --platform linux/amd64 -f docker/device.Dockerfile --secret id=bridge_keystore,src=secrets/bridge.jks --secret id=bridge_key_password,src=secrets/bridge_key_password -t kakaotalk-collector/device:0.1.0-amd64 --load .`: exit 0, Android `BUILD SUCCESSFUL in 1m 11s`.
- amd64 서버 컨테이너에서 TestClient로 readiness와 인증 status 확인: `PASS: linux/amd64 server starts and serves authenticated status`.
- 두 device 이미지에서 `adb version` 및 `import device.cli` 실행: `Android Debug Bridge version 1.0.41`, 각 아키텍처의 `PASS: linux/arm64 device runtime imports`, `PASS: linux/amd64 device runtime imports`.

smoke 실제 출력:

```text
PASS: TLS verification, authenticated ingest, duplicate retry, Korean text, read API, partial coverage
PASS: container stdio MCP calls all four read-only tools against the API
PASS: container restart preserves collected data
PASS: encrypted backup and verified restore inside non-root container
```

서명된 APK를 `artifacts/bridge.apk`로 추출했다(약 5MiB). SHA-256:

```text
0ad8daba2cb98f8b28f2f4e8591584f80568c198c0ed4770c76c6ba4b297db2b
```

APK는 설치마다 생성한 자체 키로 서명되므로 다른 키로 재빌드하면 해시가 달라진다. 로컬 실행 이미지 태그는 server/device의 `0.1.0`(arm64), `0.1.0-amd64`다. 다른 호스트에서는 Compose로 네이티브 빌드하거나 배포한 이미지 참조를 `COLLECTOR_IMAGE`/`DEVICE_IMAGE`에 지정한다. registry로 push하지 않았다.

실제 계정으로 G0/G1, screen-off 수신, 읽음 유지, 24~72시간 soak test는 미실행이다. 자체 APK가 컴파일되는 것과 redroid에서 카카오톡이 보조 기기로 인증되는 것은 별개의 검증이다.

## 첫 운영 확인

1. 대상 Linux 호스트에서 `scripts/preflight.sh`와 redroid boot 확인.
2. 정식 APK 설치, 보조 기기 로그인 UI 확인, 스마트폰 동시 로그인 유지.
3. Bridge 알림 권한과 HTTPS 연결 확인, 운영자가 보낸 테스트 메시지의 알림/DB 대조.
4. 화면 꺼짐·방 음소거·다른 기기 사용·네트워크 단절·재부팅 조건을 나눠 coverage 기록.
5. 실제 읽음 영향과 장시간 수신 결과를 확인한 뒤 운영 상태로 승격.

참조: [redroid](https://github.com/remote-android/redroid-doc), [Android 메시지 알림 Bundle API](https://developer.android.com/reference/android/app/Notification.MessagingStyle.Message), [Compose 시작 순서](https://docs.docker.com/compose/how-tos/startup-order/), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
