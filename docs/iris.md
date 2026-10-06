# Iris 수집 구현

[README](../README.md) · [운영과 복구](operations.md)

<a id="components-and-assumptions"></a>

## 구성과 전제

Linux 서버의 redroid를 보조 태블릿으로 사용하므로 별도 실물 태블릿은 필요하지 않습니다. 기존 휴대폰이 주 기기입니다. Iris는 redroid 안에서 root `app_process`로, Python `iris-collector`는 별도 Docker 컨테이너로 실행됩니다. Termux나 PC 카카오톡은 사용하지 않습니다.

태블릿 크기와 모델 속성만으로 보조 로그인이 보장되지는 않습니다. 공식 카카오톡 APK의 실제 한국어 로그인 화면에서 **다른 기기와 함께 사용**이 선택됐는지 확인하세요. 로그인 후 운영자가 휴대폰과 redroid의 로그인이 모두 유지되는지 확인해야 합니다. 코드는 휴대폰 로그아웃을 막거나 휴대폰 세션을 감시하지 않습니다. 확인한 환경은 [검증 범위](implementation.md)를 참고하세요.

<a id="running-the-collector"></a>

## 수집기 실행

화면 제어, 설치, 로그인 확인은 [웹 관리 화면](web-ui.md)을 기본으로 사용하세요. 아래 CLI는 같은 웹 작업의 대안이므로 동시에 사용하지 마세요.

[수동 배포](onboarding.md#manual-deployment)에 따라 커널·키·공식 카카오톡 APK를 준비한 뒤 실행합니다.

```bash
docker compose build api device-agent gateway
docker compose up -d
docker compose --profile setup run --rm bootstrap
```

`bootstrap`은 새 태블릿용입니다. 제공된 카카오톡 APK 세트가 있으면 설치하고, 키보드 앱을 설치한 뒤 잠긴 새 등록 정보를 씁니다. 로그인은 하지 않습니다. 이미 승인한 태블릿에서 실행하면 승인이 초기화되므로 일상적인 복구에 사용하지 마세요. 관리 화면의 **수집 구성 요소 설치**는 기존 등록과 승인을 유지합니다.

관리 화면에서 redroid를 열고 한국어 로그인 화면의 **다른 기기와 함께 사용**을 선택한 뒤 로그인하세요. 별도 scrcpy 클라이언트는 승인된 ADB 키가 필요하며 포트 포워딩만으로 접근할 수 없습니다. 로그인 후 휴대폰 로그인이 유지되는지 직접 확인하고 승인하세요.

```bash
docker compose --profile setup run --rm bootstrap approve --phone-session-active
docker compose logs --tail 30 iris-collector
```

승인은 승인 시점에 태블릿에 로그인된 카카오톡 계정에 묶이며 같은 계정이면 카카오톡 업데이트 후에도 유지됩니다. 검증되지 않은 보조 로그인 절차를 추측하거나 주 기기 이전으로 진행하지 마세요.

기기 이미지의 CLI(`python -m device.cli`) 명령은 다음과 같습니다. 오류는 한국어 안내와 사유 코드로 표시합니다.

| 명령 | 용도 |
| --- | --- |
| `bootstrap` | 새 태블릿 등록. `--rotate-epoch`는 Android 상태 복구 후 새 등록 세대를 시작 |
| `approve --phone-session-active` | 휴대폰 로그인 유지를 직접 확인한 뒤 현재 로그인된 계정으로 수집 승인 |
| `probe` | Android·카카오톡·키보드 앱 설치 상태를 JSON으로 출력 |
| `watch`, `iris-watch`, `web-ui` | 각각 `device-agent`, `iris-collector`, `admin` 서비스의 실행 명령 |

<a id="iris-build-and-runtime-boundaries"></a>

## Iris 빌드와 실행 경계

- 원본: [dolidolih/Iris](https://github.com/dolidolih/Iris), 커밋 `ee1dc978ec465df11642596e40f74caff497301d`.
- 빌드 시 압축 파일의 SHA-256 `1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0`을 확인합니다.
- 수정 빌드는 `iris/CollectorMain.kt`를 추가합니다. 원본 `Main`을 실행하지 않고 DB 읽기·Iris 복호화와 제한된 알림 답장 전송 경로를 사용합니다. Android SQLite `OPEN_READONLY`로 DB를 엽니다. 빌드 식별자는 `iris-ee1dc978-collector-v6`입니다.
- 원본의 비동기 전송 큐, 알림 폴링, 파일 삭제, 대시보드, `/query`, `/reply`, `/aot`는 실행하지 않습니다. 고정 SELECT용 `/collector/rows`, `/collector/metadata`, 빌드 확인용 `/collector/health`와 인증된 텍스트 전송용 `/collector/send`를 제공합니다. 전송은 현재 승인 계정·등록 세대·DB·방을 검사하고 카카오톡 알림 답장 서비스를 한 번 호출합니다. [전송 권한과 상태](sending.md)를 참고하세요.
- Android `127.0.0.1:3000`에만 바인딩하고 수집기 내부 루프백 ADB 포워딩으로 접근합니다. Compose는 호스트에 3000 포트를 공개하지 않습니다. root ADB 권한이 있는 호스트·컨테이너는 신뢰 경계 안에 있습니다.
- 태블릿 쪽 파일은 root 전용 `/data/kakaotalk-bridge/`(0700)에 둡니다. 등록 정보 `enrollment.json`(0600), Iris 빌드 `iris.apk`(0444), 프로세스 ID `iris.pid`, 인증 파일 `iris-auth.json`(0600), SQLCipher 네이티브 라이브러리 `native/`(0700)입니다.
- Iris는 DB 접근 전에 등록별 무작위 bearer로 인증합니다. nonce/HMAC 상태 확인으로 리스너를 검증한 뒤 Python이 bearer를 보냅니다. 키는 로그나 프로세스 인수에 넣지 않으며 등록 세대가 바뀌면 새로 만듭니다.
- `adb-init`이 Android 시작 전에 기존 기기·Iris 수집기 공개 키를 등록합니다. `ro.adb.secure=1`은 미등록 ADB 클라이언트를 거부하고, 승인된 수집기는 Iris에 필요한 root 권한을 사용합니다. 개인 키는 상태 볼륨에 남으므로 Android 데이터와 함께 백업·복구하세요.
- Iris는 요청마다 등록 세대, Android 지문, 휴대폰 로그아웃 기록과 LocalUser DataStore의 계정 ID(하나이며 승인한 ID와 같아야 함)를 검사하고 응답 직전에 다시 확인합니다. 카카오톡 버전은 검사하지 않습니다.
- APK는 앱 설치용 서명 패키지가 아니라 `app_process` 빌드 산출물입니다. 수집기는 Iris를 시작할 때 기기의 APK를 이미지 안 APK와 SHA-256으로 비교하고, 다르면 업로드한 파일의 SHA-256을 다시 확인한 뒤 교체합니다. 업데이트·되돌리기 모두 실행 중인 이미지의 Iris를 사용하며 별도 이전 작업이 필요하지 않습니다.
- 0.1.0이 쓰던 기기 파일(`/data/local/tmp/kakaocollector-*`, `/data/kakaocollector-iris`, 키보드 앱 폴더의 등록 정보)은 업데이트가 실패해 이전 버전으로 되돌아갈 때 필요하므로, 새 수집기가 10분 넘게 동작한 뒤 지웁니다.
- GPL·MIT 고지와 대응 소스는 이미지의 `/opt/iris-overlay/`(수정 코드와 `NOTICE.md`), `/opt/iris-source.tar.gz`(원본), `/opt/iris-build.Dockerfile`(빌드 절차)에 포함됩니다. 배포 시 소스와 고지를 함께 제공하세요.
- Netty는 `4.1.138.Final`로 맞췄으며 `/opt/iris-dependencies.txt`에 실제 의존성 그래프를 보관합니다. 오래된 Android 보안 패치는 [남은 위험](security.md#remaining-risks)을 참고하세요.

<a id="storage-and-recovery"></a>

## 저장과 복구

초기 커서는 0입니다. 수집기는 redroid 카카오톡 DB에 현재 존재하는 행을 `SYNCMSG` 같은 동기화 행을 포함해 한 번에 최대 200행(약 2MB) 읽습니다. 남은 행이 있으면 0.2초 뒤, 없으면 3초 뒤 다시 조회합니다. 휴대폰 전체 기록이나 카카오 서버의 모든 기록에는 접근할 수 없습니다.

`_id`, `chat_id`, `user_id`는 문자열로 전달합니다. 이벤트 ID는 Iris 등록 세대, DB 식별자, 로그 ID로 만듭니다. 본문이 같아도 로그 ID가 다르면 별개이며 관측 시각만 다른 재전송은 중복 응답을 받습니다. 불변 행에는 대화·발신자 ID를 저장합니다. 별도 메타데이터 갱신이 행 식별자와 재전송 다이제스트를 바꾸지 않고 지원되는 표시 이름을 조회합니다. [메시지 조회](mcp-queries.md#names)를 참고하세요.

수집기는 페이지를 최대 100행·768KiB 요청으로 나눠 순서대로 보내고, 서버가 저장했다고 응답한 행까지만 커서를 옮깁니다. 서버는 행과 최신 커서를 같은 SQLite 트랜잭션에 저장하며 거부된 첫 행 이후의 행은 처리하지 않습니다. 응답 유실·재시작 후에는 로컬 커서 파일 대신 서버 커서를 다시 조회합니다. 승인 확인은 ADB 호출 한 번으로 하며 페이지 조회 전과 행이 있는 페이지를 받은 뒤 실행합니다. 앱 DB가 원본 대기열이므로 서버 중단 중 앱에서 삭제된 행은 복구할 수 없습니다.

보관 기간 정리로 메시지를 지워도 Iris 커서는 유지합니다. 암호화 백업에도 커서를 포함하며 복구 후 해당 커서에서 재개합니다. DB 파일의 device/inode가 바뀌거나 최대 ID가 줄면 수집을 멈추고 새 DB를 자동 승인하지 않습니다. 같은 파일·ID를 재사용하는 변경이나 기존 행 수정·삭제는 완전히 감지할 수 없습니다.

초기 범위, 삭제된 행, 늦은 동기화 때문에 `coverage.complete=false`를 유지합니다. 정상 heartbeat는 Iris의 DB 접근 가능 여부이며 카카오 서버 연결이나 휴대폰 로그인 확인이 아닙니다. heartbeat에는 태블릿의 카카오톡 버전(`kakao_version`)도 담습니다. Iris로 수집한 메시지는 `source=iris_db`입니다.

<a id="current-limits-and-operational-validation"></a>

## 현재 제한과 운영 검증

본문은 UTF-16 코드 단위 16,384개로 제한하고 잘림 여부를 표시합니다. 행 본문, 종류, ID, 시각, 출처, isMine을 수집하며 표시 이름은 별도로 조회합니다. Iris는 카카오톡의 암호화 프로필 DB `crypto_user_database`를 SQLCipher로 읽기 전용 접근합니다. 이 스키마는 카카오톡 26.8.2에서 확인했습니다. 정확한 발신자 ID로 일반 프로필을, 채널·대화 ID 쌍으로 PlusChat 이름을 찾습니다. 암호는 Android의 기존 설정에서 도출하며 생성·기록·외부 전송하지 않습니다.

본인 ID는 LocalUser DataStore에서 읽고, 암호화된 오픈채팅 닉네임이 있으면 그 ID로 복호화되는지 확인합니다. ID가 없거나 확인에 실패하면 본인이 보낸 최신 메시지의 발신자 ID를 사용합니다. 사용한 근거는 `/v1/status`의 `identity_metadata.self_identity_source`에 `local_account`, `sent_message`, `unavailable`로 표시합니다. 본인은 **나**, 이름이 없는 나와의 채팅방은 **나와의 채팅**으로 표시합니다.

현재 오픈채팅 프로필이 없으면 API가 같은 방의 보관된 입장·퇴장 이벤트에서 닉네임을 가져오고 과거 이름과 관측 시각임을 명시합니다. 두 근거가 모두 없으면 미확인 상태를 유지합니다. 원본 첨부 파일과 수정·삭제 동기화는 지원하지 않습니다.

Iris가 해독하지 못한 행은 이유와 함께 본문 없는 건너뛰기 기록으로 저장하고 다음 행을 계속 수집합니다. 이유는 `decrypt_failed`(복호화 실패), `metadata_unreadable`(행 메타데이터를 읽지 못함), `unreadable`(그 밖의 읽기 오류)입니다. 서버가 형식 오류로 거부한 행은 `invalid_row`로 기록합니다. 암호문을 정상 본문으로 저장하지 않으며 건너뛴 수는 수집 상태의 `coverage.skipped_rows`에 표시됩니다.

새 환경에서는 다음을 확인해야 하며, 남은 검증 범위이기도 합니다.

1. 커널·binder, 카카오톡 APK ABI, root DB 접근 호환성.
2. 보조 로그인 옵션과 기존 휴대폰 로그인 유지.
3. 일반·알림 끈 방, 화면 꺼짐, 본인 메시지, 동기화 메시지의 수신·복호화.
4. 수집 전후 읽음 상태, 앱·컨테이너 재시작, 네트워크 단절 후 수집 재개.
5. 24–72시간 연속 수신과 디스크 사용량.

로컬 API 테스트와 APK 빌드 성공만으로 이 검증을 대신할 수 없습니다. [아직 검증하지 않은 범위](implementation.md#not-yet-verified)를 참고하세요.
