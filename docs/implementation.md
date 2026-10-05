# 검증 범위

[개발과 테스트 명령](development.md) · [현재 구조](design.md)

날짜별 항목은 해당 시점의 검증 기록이며 모든 설치 경로를 실행했다는 뜻은 아닙니다. 최근 관리 화면·연결 설정 검사는 [아래](#admin-ux-and-connection-setup-2026-10-05)에 있습니다. 명령과 실제 진단 출력은 원문을 유지합니다.

<a id="public-release-2026-10-06"></a>

## 공개 릴리스와 사전 빌드 설치 (2026-10-06)

[`v0.1.0`](https://github.com/rokrokss/kakaotalk-bridge/releases/tag/v0.1.0)은 커밋 `88a19c27ffbd4b0d53748f8e343f63c24c259690`에서 생성했습니다. [GitHub Actions 실행](https://github.com/rokrokss/kakaotalk-bridge/actions/runs/37383947477)이 성공했고 개인 계정 `rokrokss`의 GHCR 서버·기기·게이트웨이 이미지를 공개했습니다. 각 이미지에 Linux amd64·arm64가 포함됩니다.

| 실행한 검사 | 실제 결과 |
| --- | --- |
| 로컬 `uv run pytest -q` (초기 구현) | `389 passed, 1 warning in 23.59s` |
| 추가 수정 후 `uv run pytest -q tests/test_releases.py tests/test_onboarding.py tests/test_web_connection_setup.py` | `87 passed, 1 warning in 4.35s` |
| 최종 커밋의 CI `uv run pytest -q` | `392 passed, 2 skipped, 1 warning in 17.10s`; Caddy 실행 파일이 없는 러너에서 로컬 프록시 테스트 2개 생략 |
| `uv run ruff check .` | `All checks passed!` |
| `actionlint`, `bash -n install.sh`, `git diff --check` | 종료 코드 0 |
| `python3 scripts/verify-release-images.py <release.json>` | 세 이미지 모두 `공개 다운로드 및 amd64·arm64 확인 완료` |
| `gh release download v0.1.0` 및 `SHA256SUMS` 대조 | 설치 번들·Unix/Windows 진입점·매니페스트·체크섬 파일 5개 다운로드, 모든 페이로드 SHA-256 일치 |
| `gh attestation verify bridge-install.tar.gz --repo rokrokss/kakaotalk-bridge --format json` | 종료 코드 0, 검증 결과 1개 |
| 커밋에서 설치 번들 생성·압축 해제 | 실행 권한·업데이터·매니페스트·체크섬 확인, 로컬 상태·인증 키 미포함 |

새 Ubuntu 24.04.5 arm64 VM은 Docker가 설치되지 않았고 Binder가 로드되지 않은 상태에서 시작했습니다. 디스플레이와 호스트 홈 공유 없이 공개 `install.sh --no-browser --admin-url http://localhost:39789`를 실행했습니다. Docker·커널 모듈 준비, GHCR 이미지 다운로드, 서비스 시작, SSH 포워딩 안내까지 종료 코드 0으로 완료했습니다. 설치된 이미지는 공개 Bridge 이미지 3개와 redroid뿐이며 Android SDK/Gradle 소스 빌드는 수행하지 않았습니다.

`bridge doctor`는 누락된 인증 키 0개를 보고했고, Android의 `getprop sys.boot_completed`는 `1`을 반환했습니다. 호스트에서 전달된 localhost 관리 주소는 HTTP 200과 한국어 HTML을 반환했습니다. 설치 명령 재실행과 `sudo reboot` 후에도 인증 키 12개의 해시가 모두 일치했고, 별도의 `bridge up` 없이 서비스가 복구됐습니다.

업데이트는 테스트 VM에서 릴리스 메타데이터를 별도 보관한 뒤 `bridge upgrade --version v0.1.0`으로 같은 릴리스를 다시 적용했습니다. 암호화 백업(`.kcs`, 약 25 MiB), 이전 코드 보관, 상태 확인, 인증 키 유지가 모두 성공했습니다. 다시 같은 버전을 요청하면 `이미 v0.1.0 릴리스를 사용하고 있습니다.`로 종료했습니다. 단위 테스트는 다운로드 해시 불일치·경로 이탈·잘못된 버전 거부와 업데이트 실패 시 코드 복구도 확인합니다.

Apple Silicon Mac에서는 공개 설치 번들을 받아 `bash install.sh --no-browser --vm kakaotalk-release-mac-20261006 --admin-port 39444 --mcp-port 39788`로 새 전용 Lima VM을 만들었습니다. 소스 빌드 없이 설치가 완료됐고 호스트의 localhost 관리 화면에서 HTTP 200·한국어 HTML을 확인했습니다. VM을 완전히 정지한 뒤 `bridge up --no-browser`로 다시 실행하고 `bridge doctor`가 종료 코드 0을 반환하는 것도 확인했습니다. Mac에서도 같은 릴리스를 재적용해 호스트·VM의 코드가 함께 갱신되고, VM의 암호화 백업·이전 코드 보관·업데이트 후 상태 검사가 성공하는 것을 확인했습니다.

이번 실환경 검증은 Ubuntu arm64 VM과 Apple Silicon Mac의 설치·운영 경로를 대상으로 했습니다. amd64 이미지는 빌드와 공개 다운로드를 검증했으며, 독립 amd64 서버에서 카카오톡 로그인·수집까지 실행한 검증은 아닙니다. 테스트 VM에는 개인 카카오톡 계정을 연결하지 않았고 기존 운영 VM과 로그인 데이터는 변경하지 않았습니다. Windows·Intel Mac의 실제 설치는 여전히 미검증입니다. 검증에 사용한 두 VM은 종료 후 정지했습니다.

<a id="korean-user-guidance-2026-10-06"></a>

## 한국어 사용자 안내 (2026-10-06)

README·사용 문서, 관리·OAuth 화면, MCP 도구 설명, Android 등록 앱, 터미널 안내를 한국어 중심으로 바꿨습니다. README의 SVG와 편집 원본도 수정하고 가상 데이터의 한국어 관리 화면을 다시 캡처했습니다. 내부 주석·예외·진단과 프로토콜 식별자는 영어를 유지합니다. 설정 stdout·stderr는 비공개 로그로 보내고 단계·완료·경과 시간·실패 후 안내를 한국어로 표시합니다. 인증 링크와 기계 판독 출력은 로그·진행 안내와 분리합니다.

| 실행한 검사 | 실제 결과 |
| --- | --- |
| `uv run pytest -q` | `371 passed, 1 warning in 21.18s` |
| `uv run ruff check .` | `All checks passed!` |
| `node --test tests/connection-guidance.test.cjs tests/setup-flow.test.cjs` | `tests 7`, `pass 7`, `fail 0` |
| `node tests/setup-browser.cjs` | `PASS`: 자동 준비·스토어 설치 감지·구성 요소 설정·수동 확인 경계·재설치 없는 새로고침 |
| `node tests/passkey_browser.cjs` | `PASS`: 패스키 등록·로그인·세션·두 포트 사용·명시적 OAuth 승인/취소·PKCE·갱신·도구 조회·코드 재사용 거부 |
| `node tests/localization-browser.cjs` | `PASS: Korean admin, connection guidance, mobile layout, README capture and SVG canvas bounds` |
| `./bridge --help`, `./bridge up --plan` | 종료 코드 0. 한국어 사용법·설정 단계 출력 |
| JS `node --check`, 설치·운영 셸 `bash -n`, `docker compose --profile dot config --quiet`, `git diff --check` | 모두 종료 코드 0, 출력 없음 |
| 로컬 문서 링크·앵커 검사 | `PASS: local documentation links and anchors` |

Python 추가 검사는 하위 명령의 두 출력 스트림 격리, 실패 진단·0600 로그, 한국어 경과 시간, 인증 링크 비저장, MCP·JSON 출력 보존, CLI 인수 오류를 확인합니다. 브라우저 검사는 합성 기기·인증기를 사용했으며 실제 계정·VM을 조작하지 않았습니다. 폭 390·1168픽셀의 관리 화면과 SVG 글자 영역을 검사하고 영문 내부 오류가 한국어 안내로 표시되는 것도 확인했습니다. 기존 Starlette 테스트 클라이언트 지원 중단 예고 1개가 남았습니다. 이 변경에서는 운영 배포와 Android APK 재빌드를 수행하지 않았습니다.

<a id="verified-with-a-real-account"></a>

## 실제 계정으로 확인한 내용

2026-10-04, Apple Silicon Mac의 Lima·Ubuntu 24.04 arm64에서 확인했습니다.

- Android 14 redroid 시작, SM-T970 태블릿 설정, 밀도 240의 1200 × 1920 해상도.
- 웹 관리 화면에서 화면 보기·조작·한국어 입력.
- 카카오톡 **다른 기기와 함께 사용** 옵션 검사와 보조 기기 로그인.
- 사용자가 휴대폰에서 직접 확인한 기존 로그인 유지. 서버 자동 검사는 아닙니다.
- 승인 후 Iris DB 행 저장과 나에게 보낸 새 메시지 수집.
- 컨테이너·VM 재시작 후 상태 볼륨 유지.
- 공개 HTTPS OAuth와 ChatGPT의 `KakaoTalk Bridge` 연결 성공.

<a id="automated-checks"></a>

## 자동 검사

Python 테스트는 합성 데이터로 인증, CSRF, Origin, 로그인 승인 조건, DB 중복 제거, 커서, 복구, MCP 조회, 이벤트 재시도·철회·만료를 검사합니다. Docker smoke 테스트는 API·gateway·stdio MCP·SQLite·암호화 백업을 검사합니다.

amd64에서 이미지 빌드·API 시작을 확인했지만 amd64 호스트의 redroid·카카오톡 호환성을 입증하지는 않습니다. 재현 명령은 [개발](development.md)에 있습니다.

<a id="mcp-message-queries-2026-10-04"></a>

## MCP 메시지 조회 (2026-10-04)

[조회 API](mcp-queries.md)는 발신·수집 시각을 분리하고 구조화된 발신자·방 정보, 발신자·방·날짜 필터, 안정된 페이지 조회, 대화 목록·앞뒤 문맥을 제공합니다. 원격 도구는 8개이며 숫자 이벤트 커서와 미처리·처리 확인 동작은 유지합니다.

`uv run pytest -q`는 **187 passed**와 기존 Starlette 경고, `uv run ruff check .`는 **All checks passed!**, `git diff --check`는 성공했습니다. 시각 정렬, 문자열 검색, 필터, 서명 커서, 늦은 기록, 방별 이름, 문맥, 메타데이터 갱신, 보관 기간, 복구, 실제 API→MCP 출력 스키마를 검사했습니다. arm64 이미지 둘도 빌드했습니다.

실제 Lima 배포는 인증 암호화 백업 후 Iris와 조회 서비스를 교체했습니다. 두 APK 해시를 검증하고 이전 바이너리를 보관했습니다. redroid·gateway·device-agent·패스키 관리 컨테이너는 재생성하지 않았으며 로그인된 카카오톡·기기 등록도 교체하지 않았습니다.

운영 검사는 최신순 정렬, 중복 없는 페이지, 방·확인된 발신자 이름 필터, 대화 22개, 같은 방 문맥에 통과했습니다. 설치된 연결의 최근 메시지·프로필·수집 상태 호출이 성공했고 발신자·방 이름을 반환했습니다. 수집기는 `collecting_partial`, Iris 연결 상태였습니다. 첫 메타데이터 처리 후 방·발신자 쌍 390개 중 발신자 확인 139개(오픈 멤버 129, 본인 10), 로컬 프로필 없음 236개, 이전 friends 조회 불가 15개였습니다. 사람 수가 아닌 쌍의 수입니다. 수정 배포 후 32회 점검에서 전송 오류는 없었습니다.

처음에는 대량 메타데이터가 GET 요청행 제한을 넘어 제한된 POST JSON으로 바꿨습니다. 이 시점에는 설치 버전에 이전 `friends` 테이블이 없어 일반 발신자 이름이 미확인이었고 아래 암호화 프로필 구현에서 해결했습니다. 검증 중 메시지 전송·대화 열기는 하지 않았습니다. 새 문맥 도구·인수는 클라이언트의 도구 목록 갱신이 필요할 수 있습니다. 에이전트 호출 검증이며 사용자의 Dot 대화 안에서 실행됐다는 뜻은 아닙니다.

<a id="encrypted-profile-names-2026-10-04"></a>

## 암호화 프로필 이름 (2026-10-04)

설치된 카카오톡 26.8.2(versionCode 29260820)는 로컬 검사 APK와 SHA-256이 같았습니다. 스키마·이름 표시 코드를 통해 `crypto_user_database.user`, 로컬 키 설정 형식, 표시 우선순위, `talk_channel`의 별도 ID·대화 ID를 확인했습니다. APK·역컴파일 소스는 저장소에서 배포하지 않습니다.

Iris v3는 고정 라이브러리·스키마 검사·비파괴 손상 처리기를 사용한 읽기 전용 SQLCipher 접근을 추가했습니다. 관측된 정확한 발신자 ID와 오픈채팅 링크·사용자 범위를 사용하고 키는 Android 메모리에만 둡니다. 설정·DB를 생성하거나 이전하지 않습니다. 사용자 지정 닉네임·기존 카카오톡 연락처 이름·프로필 닉네임의 출처를 명시하며 주소록 순회·전화번호 연결은 하지 않습니다.

검증 결과:

- `:app:testReleaseUnitTest :app:assembleRelease`: **BUILD SUCCESSFUL**, **10 profile tests, 0 failures, 0 errors**. PBKDF2 정상·오류 벡터, 대체 키, 잘못된 설정, 이름 우선순위, 비활성 프로필 검사.
- `uv run pytest -q`: **187 passed**, 기존 Starlette 경고. `uv run ruff check .`: **All checks passed!**, `git diff --check` 성공.
- 별도 Android 검사가 실제 암호화 DB를 `read_only=true`로 열었습니다. 본인 외 일반 쌍은 DirectChat **3/3**, MultiChat **9/9**, PlusChat **3/3** 일치했고 채널 3개 모두 해당 방 멤버에도 있었습니다. 집계만 출력했습니다.
- 배포·갱신 후 일반·채널 쌍 **15/15** 확인: 사용자 지정 닉네임 8, 프로필 4, 채널 3. 연락처 대체 이름은 단위·정적 검사가 있지만 이 운영 행에서는 선택되지 않았습니다.
- 기존 MCP 연결이 최근 발신자 **10/10**, 방 **10/10** 이름을 반환했고 새 어댑터 행 3개를 포함했습니다. **22개 방**에서 정렬·페이지·방/발신자 필터·문맥도 통과했습니다.

교체 전 암호화 백업을 하고 이전 Iris APK를 남겼으며 배포 소스·라이선스 해시를 확인했습니다. admin·iris-collector만 재생성하고 redroid·device-agent·API·원격 MCP·gateway·패스키 관리의 ID·시작 시각은 유지했습니다. Iris 연결·수집을 유지했고 테스트 메시지 전송·대화 열기는 하지 않았습니다.

로컬 멤버 기록이 없는 오픈채팅 쌍 236개는 여전히 미확인이었습니다. 해결된 일반 암호화 프로필과 별개입니다. 다른 카카오톡 버전·스키마·키 변경은 미검증이며 추측 대신 조회 불가 상태를 표시합니다.

<a id="open-chat-missing-names-follow-up-investigation-2026-10-04"></a>

## 오픈채팅 미확인 이름 추가 조사 (2026-10-04)

수집기 변경·배포 없는 읽기 전용 조사입니다. 본인 외 오픈채팅 쌍 365개 중 7개 방의 사용자 ID 236개에 해당하는 236쌍은 로컬 open-member가 없었습니다. 다른 링크의 멤버·`open_profile`·링크 소유자와도 일치하지 않았고 저장된 멤버·활성 멤버 배열에도 없었습니다. 배열은 일부일 수 있어 모두 퇴장했다고 단정할 수는 없습니다.

이미 수집한 시스템 메시지에 두 번째 근거가 있었습니다. 설치 APK의 feed 2는 LEAVE(`member.userId`/`member.nickName`), feed 4는 OPENLINK_JOIN(`members[].userId`/`nickName`)입니다. 같은 방·사용자 일치로 **236쌍 중 26쌍**의 과거 이름을 관측 27개(퇴장 21, 입장 6)에서 찾았습니다. 한 쌍에는 다른 과거 닉네임 둘이 있었습니다. 이벤트 당시 근거이므로 현재 프로필로 표시해서는 안 됩니다. feed 14·25·26에서는 이름 경로를 찾지 못했습니다.

앱에는 닉네임을 받고 링크·사용자별 로컬 캐시를 갱신하는 `member(chatId, memberIds)` 요청도 있지만 수집기는 이 앱 세션 인증 프로토콜을 호출하지 않습니다. 조사에서도 실행하지 않아 남은 210쌍의 원격 복구 가능성은 미검증입니다. 방 스냅샷에는 표시 ID·이름 배열이 함께 있을 수 있지만 검사한 로컬 기록에는 ID만 있었습니다.

재현 명령과 실제 결과입니다. 비공개 조사 스크립트는 Git 제외 `artifacts/`에 있으며 개인 값은 출력하지 않았습니다.

```text
python3 artifacts/open-member-research/aggregate.py
  total_pairs=365, missing_pairs=236, affected_rooms=7
  another_link_same_user=0, exact_open_profile=0
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/open-member-research/system_names.py
  missing_pairs=236, matched_missing_pairs=26, multiple_historical_names=1
JAVA_HOME=/opt/homebrew/opt/openjdk@21 bash artifacts/name-storage/jadx/bin/jadx --no-inline-anonymous -d artifacts/open-member-research/agent/feedtype artifacts/name-storage/classes9.dex
  Re-decompiled FeedType constructors expose LEAVE=2 and OPENLINK_JOIN=4.
```

로컬 정적 근거는 `feedtype/sources/defpackage/z3r.java:225`(퇴장), `:397`(입장), `jp80.java:145`(입장 멤버), 이전 역컴파일의 `defpackage/uf9.java:299`(로컬 조회·대체·갱신), `nn9.java:3752`(멤버 응답), `ll9.java:1620`(스냅샷 이름 쌍)입니다. 역컴파일 소스는 배포하지 않습니다. 검사 후 수집기는 `collecting_partial`, Iris 연결 상태를 유지했습니다. 후속 구현은 아래와 같습니다.

<a id="historical-open-chat-nickname-fallback-2026-10-04"></a>

## 과거 오픈채팅 닉네임 보완 (2026-10-04)

API·MCP에 구현·배포했습니다. 현재 확인된 프로필이 우선합니다. `OM`/`OD` 방의 본인 외 발신자에게 현재 프로필이 없으면 별도 색인이 같은 기기·등록 세대·대화·사용자의 최신 보관 입장·퇴장 이름을 선택합니다. 원본 시각을 우선하고 메시지 ID로 동률을 구분합니다. 잘못된·모호한·잘린·미지원·시각 없는 근거는 제외하고 원본 메시지 만료 시 근거도 제거합니다. 현재 프로필 갱신은 독립적으로 계속합니다.

MCP·HTTP는 `historical`/`resolved`를 구분하고 `name_observed_at`, `name_evidence_message_id`를 제공하며 `updated_at`은 프로필 조회 시각으로 유지합니다. 원격·stdio 지시에도 이 구분을 설명합니다. 이름 검색·상태 집계는 같은 보완을 사용합니다. 이름 필터 커서는 표시 정보·근거 변경 시 만료되고 동일한 갱신은 유지됩니다. 다른 메시지 커서·기존 이벤트 형식은 유지합니다.

검증 명령과 실제 결과:

```text
uv run pytest -q
  220 passed, 1 warning in 9.12s
uv run ruff check .
  All checks passed!
git diff --check
  exit 0, no output
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/historical-names-check/verify_snapshot.py
  missing_pairs=238, historical_pairs=28, still_missing_pairs=210
  current_profiles_unchanged=true, observations_unchanged=true, event_progress_unchanged=true
```

실데이터 검사는 운영 DB를 읽기 전용으로 열어 메모리에 복사하고 해당 프로세스에서만 새 구현을 사용했습니다. 조사 후 들어온 새 데이터로 236/26에서 238/28로 바뀌었습니다. 집계·불리언만 출력하고 새 스키마를 검사했으며 운영 DB에는 쓰지 않았습니다. 이는 배포 전 결과로 실행 중인 연결의 사용 증거는 아닙니다.

현재 프로필 우선순위, 정확한 방·사용자·기기·등록 범위, 원본 시각·동률·늦은 수집, 제한된 파싱·큰 ID, MCP 스키마, 이름 검색·집계, 커서 만료, 기존 데이터 색인·재시작·근거 제거, 수집 위치 유지를 검사했습니다. 기존 Starlette 경고가 남았습니다.

<a id="production-deployment-verification"></a>

### 운영 배포 검증

기존 Lima에 `kakaotalk-collector/server:historical-names-20261004`를 배포했습니다. 빌드·소스 해시가 테스트한 소스와 일치했고 이전 이미지와의 차이는 이 기능의 API·MCP 파일 6개뿐이었습니다. `api`, `dot-plugin`만 재생성하고 나머지 6개 컨테이너의 ID·시작 시각, 패스키 설정·인증 정보, 관리 세션, MCP 승인, 프로필을 유지했습니다.

앱 DB 4개·키·배포 설정의 인증 암호화 백업은 호스트의 `/srv/kakaotalk-collector/backups/historical-names-20261004/state.bin`에 0600으로 보관합니다. 첫 시도는 읽기 전용 볼륨에서 SQLite WAL에 접근하지 못해 서비스 변경 전에 멈췄습니다. 완료한 백업은 쓰기 가능한 마운트에서 SQLite `mode=ro`로 연결해 WAL 공유 메모리를 처리했습니다. DB마다 `integrity_check`를 통과하고 저장된 암호화 파일을 메모리에서 복호화해 인증·내용을 검증했습니다.

```text
limactl shell --workdir=/ kakaotalk-test sudo python3 /tmp/historical-names-rollout/deploy.py
  PASS: encrypted four-database/configuration backup authenticated
  PASS: built application source hashes match tested checkout
  PASS: API and MCP healthy; other six containers unchanged
  PASS: passkey credentials, admin sessions, MCP grants and profile preserved
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/historical-names-rollout/verify.py
  historical_pairs=28
  historical_context_and_provenance=true, historical_name_search=true
  current_profile_precedence=true, recent_schema_and_pagination=true
  collector_state=collecting_partial, iris_connected=true
Installed connector: get_recent_messages(limit=100)
  100 rows: 95 resolved current names, 5 historical names
  Historical rows all included name_observed_at and name_evidence_message_id.
Public HTTPS checks
  OAuth resource discovery=200, /admin/=404, unauthenticated POST /mcp=401
```

배포 데이터의 현재 프로필 없는 오픈채팅 쌍 238개 중 28개는 과거 근거, 210개는 미확인이었습니다. 기존 인증 연결로 검사했고 재연결·구독·처리 확인·메시지 전송은 하지 않았습니다. 에이전트 MCP 호출 검증이며 별도 사용자 Dot 대화 조회를 뜻하지 않습니다. 집계만 출력했습니다.

<a id="passkey-authentication-2026-10-04"></a>

## 패스키 인증 (2026-10-04)

소유자가 실제 패스키 등록을 마치고 클라이언트 연결 완료를 알렸습니다. 에이전트의 기존 연결 호출은 `get_profile`에서 `KakaoTalk Bridge`, `get_collector_status`에서 `collecting_partial`·활성 Iris를 반환했습니다. 연결 접근 검증이며 사용자 Dot 대화의 메시지 조회·이벤트 실행 검증은 아닙니다.

Chromium·가상 CTAP2 테스트는 등록·로그인·기억한 세션·새로고침·두 출처의 동일 키·MCP 동의·취소·PKCE·갱신·도구 조회를 검사합니다. Python은 실제 ES256으로 challenge·브라우저·출처·RP·사용자 핸들·사용자 검증·만료·재사용·카운터 역행을 검사합니다. 복구, 마지막 키 보호, 비공개 권한 격리, 세션·승인 보존 이전도 포함합니다.

카카오 OAuth 코드·UI를 제거하고 패스키를 기본으로 했습니다. [설정과 복구](passkeys.md)를 참고하세요. 제거 후 `uv run pytest -q`는 **172 passed**와 기존 경고, Ruff·JS 구문·Compose·로컬 문서 링크·diff 검사는 성공했습니다. `node tests/passkey_browser.cjs`도 통과했습니다. 이전보다 테스트 수가 줄어든 것은 제거한 공급자 테스트 때문입니다.

arm64 기기·서버 이미지를 빌드하고 배포 소스 해시를 검사했습니다. 관리·OAuth·패스키 DB와 설정·키를 인증 암호화 백업했습니다. admin·dot-plugin·dot-control만 재생성하고 패스키 설정·ID·관리 세션·MCP 승인·프로필은 유지했으며 이전 공급자 설정은 제거했습니다. 수집·기기 컨테이너 5개의 ID·시작 시각은 유지했습니다.

운영은 `mode=passkey`, `configured=true`, `owner_registered=true`를 보고했습니다. 당시 공개 OAuth 목록은 200, 공개 관리·비공개 권한·삭제된 공급자 경로는 404였습니다. 배포 후 기존 `get_profile`, `get_collector_status`도 성공했으며 Iris 활성, 경고·대기 행·이벤트 구독 없음이었습니다. 이것도 에이전트 연결 접근 검증입니다.

<a id="earlier-passwordpairing-onboarding-checks-2026-10-04"></a>

## 이전 비밀번호·연결 링크 설정 검사 (2026-10-04)

소유자 로그인, 설정 안내, 비공개 승인, 설치·스냅샷 명령은 실제 계정 배포와 별도로 검사했습니다.

- Python 회귀 검사: 일회용·만료 연결, 비밀번호, 재시작 유지, CSRF, 세션 철회, 비공개 승인, PKCE, 설정 보존, 서명 거부, 인증 스냅샷 복구.
- Docker Desktop arm64의 서버·기기 이미지 빌드, Bridge 릴리스 lint·APK 서명 검증 통과.
- 합성 키의 별도 Compose 프로젝트에서 HTTPS 연결, 관리 재시작, 비공개 승인, OAuth 토큰 교환, MCP, 승인·브라우저 철회 통과. 공개 제어 경로 404.
- 합성 볼륨 전체 스냅샷을 암호화하고 새 볼륨에 복구, 기존 볼륨 유지. Docker Desktop 호스트 바인드의 미지원 xattr 문제도 발견·수정.
- 기기 이미지가 기존 공식 카카오톡 APK의 배포자 인증서를 검증.
- HTTP 가상 브라우저에서 설정·접근 관리 배치 확인. 테스트 CA를 브라우저가 신뢰하지 않아 실제 HTTPS 브라우저 흐름은 미실행. 백엔드 HTTPS 검사는 테스트 인증서만 명시적으로 신뢰.

당시 `uv run pytest -q`는 **152 passed**, Starlette 경고 1개였고 Ruff는 **All checks passed!**였습니다. JS 진입점 둘의 `node --check`, Compose 설정, diff 검사도 통과했습니다. 표준 릴리스 이미지 이름과 Linux의 저장된 비공개 Tailscale 주소 재사용을 포함합니다.

로그인된 redroid를 갱신하거나 다시 로그인하지 않았습니다. 새 CLI의 신규 Lima 설치, 한국어 자동 설정, 두 아키텍처 릴리스, Tailscale 경로, 공개 릴리스 다운로드는 통합 검증이 남았습니다. 앞선 수동 Aurora·한국어 옵션 확인이 전체 설치 도구 검증을 대신하지 않습니다. 당시 Tailscale 신원 로그인은 후속 과제였으며 패스키 검증은 별도 기록입니다.

<a id="security-remediation-deployment-2026-10-05"></a>

## 보안 수정 배포 (2026-10-05)

[보안 보고서](security.md#security-fixes-2026-10-05)에 발견 사항·수정·검사 범위·Android 패치 위험을 기록했습니다. Iris v4 호출자 인증, ADB 인증, 공개·비공개 망 분리, 쿠키 필터 ingress, 관리 쿠키 이전, 상태 비저장 대기 OAuth 등록, 실행 라이브러리 갱신, 컨테이너 제한을 배포했습니다.

`uv run pytest -q`: **227 passed, 1 warning**. Ruff·diff 통과. 기기 빌드의 Kotlin·Netty `4.1.138.Final` 검사 통과. ingress smoke는 쿠키 15개, 비공개 경로 5개, 실제 루프백 포트 검사에 통과했습니다. Chromium 가상 인증기의 등록·관리 로그인·세션 유지·명시적 동의·PKCE·갱신·MCP 조회·재사용 거부도 통과했으며 합성 신원을 사용했습니다.

ARM64 운영에 server/device `security-20261005-r2`, gateway `security-20261005`를 배포했습니다. 이전 전체 암호화 백업을 인증하고 최종 소스·APK 해시, 패스키·MCP 승인·프로필을 확인했습니다. 일시적 ingress 502는 권한 수정과 별도 외부 네트워크의 포트 공개로 해결하고 상태 검사를 추가했습니다. 최종 미인증 MCP는 401, 당시 공개 관리 경로는 404였습니다. 기존 연결의 **get_profile**, **get_collector_status**가 성공했고 `collecting_partial`, Iris 연결, 경고 없음을 반환했습니다. 본문 조회·전송은 하지 않았습니다.

ADB 인증을 위해 기존 볼륨으로 Android를 한 번 재시작했습니다. 마지막 의존성·ingress 배포에서는 Android 실행을 유지했습니다. 패스키·MCP 연결은 남지만 쿠키 이전 후 소유자가 관리 화면에 한 번 다시 로그인해야 합니다. 휴대폰 세션은 자동 확인하지 않습니다. 오래된 Android 패치는 미해결이며 미검증 주요 버전 교체는 포함하지 않았습니다.

<a id="installation-and-restart-2026-10-05"></a>

## 설치와 재시작 (2026-10-05)

2026-10-05 검증은 격리된 Apple Silicon Lima VM에서 소스 빌드 이미지, 실제 Android·Aurora 준비, 공식 카카오톡 APK 가져오기·서명 검증, 한국어 보조 기기 로그인 화면, 가상 인증기의 브라우저 WebAuthn, 실제 OAuth/MCP 서비스를 사용했습니다. MCP 콜백은 브라우저 테스트에서 가로챘습니다. VM을 완전히 중지한 뒤 같은 명령으로 약 27초 만에 재개했고 인증 정보·기기 등록·패스키·OAuth/MCP가 유지되었습니다. Mac 필수 도구는 이미 설치되어 있었습니다. 소스 빌드 재시도에는 약 22분이 걸렸습니다.

카카오톡 계정 로그인, Aurora 익명 다운로드, 신규 Tailscale·Funnel 설정, Intel Mac, Windows는 해당 테스트에 포함하지 않았습니다. 로컬 HTTPS 프록시를 사용해 기존 설치의 Tailscale 경로는 유지했습니다.

<a id="admin-ux-and-connection-setup-2026-10-05"></a>

## 관리 화면과 연결 설정 (2026-10-05)

관리 화면은 수집 현황, 원격 AI 활동, 수동 휴대폰 확인으로 시작합니다. 기존 수집기는 설정·태블릿을 접습니다. 사용처부터 연결 방식을 선택하고 점검·새로고침 후 안내를 유지하며 단계·경과 시간·명시적 확인·재시도를 제공합니다. 점검 유효성, 기록된 승인, 실제 성공 MCP 호출을 구분하고 이벤트 허용·클라이언트 구독도 따로 표시합니다.

자동 검사 명령과 실제 결과:

```text
.venv/bin/pytest -q
  354 passed, 1 warning in 14.13s
node --test tests/connection-guidance.test.cjs tests/setup-flow.test.cjs
  7 passed, 0 failed
.venv/bin/ruff check .
  All checks passed!
node --check webui/static/app.js
node --check webui/static/connection-setup.js
git diff --check
  Each exited 0 with no output.
```

최종 중단 작업 변경 후 `tests/test_web_connection_setup.py tests/test_tunnel.py`는 **56 passed, 1 warning**이었습니다. 강화한 실패 도구 검사는 `test_actual_tool_activity_is_separate_from_approval_and_discovery`에서 별도 통과했습니다. 경고는 기존 Starlette/httpx 지원 중단 예고입니다. 최초 점검 재시도 수정 후 JS 구문·lint도 통과했습니다.

합성 브라우저는 실제 관리 UI·API와 가상 공급자로 활동 없는 승인, 점검·새로고침 후 안내 유지, 전체 `/mcp` 주소 정규화, 의도한 실패 후 수정·재시도 성공, 오래된 점검의 비활성 작업 안내를 확인했습니다. 390 × 844에서 가로 넘침이 없었습니다. 실제 공급자 키나 공개 테스트 주소는 만들지 않았습니다.

실제 Apple Silicon Lima는 일관된 관리·OAuth/터널·패스키 DB 백업 후 관리·MCP·호스트 설정 서비스를 갱신했습니다. redroid·API·device-agent·Iris·gateway·dot-ingress는 ID·이미지·시작 시각을 유지했습니다. 기존 OAuth 승인 2개, 영구 터널 승인, 패스키, 비공개 관리 출처를 보존했습니다. 설정 소켓은 0700 디렉터리의 0600이며 Docker 소켓 없이 관리 화면에 읽기 전용 마운트했습니다.

인증된 실제 브라우저의 **서버 연결 확인**은 저장된 안내와 접힌 기존 설정을 유지하며 완료됐습니다. 새로고침 후 초기 기기 작업 충돌 없이 현황을 표시했습니다. OpenAI 터널의 실제 `get_collector_status`가 **UAE 17:21**에 성공했고 관리 화면의 최근 성공 시각에 반영됐습니다. `collecting_partial`, 활성 리스너, 경고·구독 없음을 보고했습니다. 메시지 전송·이벤트 구독은 하지 않았습니다. 오래된 수동 휴대폰 기록은 재확인 필요로 표시했으며 원격 검증하지 않았습니다.

기존 연결·배포의 검증이며 새 OpenAI 터널 생성·Tailscale 신규 설정 검증은 아닙니다. 앞선 실제 메시지 조회는 [터널 검증 범위](openai-tunnel.md#validation-scope)에 있습니다. 원격 서버의 브라우저 진입 자동화, 고유 테스트 메시지 일치 검사는 후속 과제입니다. 현재 수집 테스트는 아무 새 행이나 수신하면 통과하며 AI 이벤트 전체 실행은 미검증입니다.

<a id="not-yet-verified"></a>

## 아직 검증하지 않은 범위

다른 카카오톡 버전·호스트 호환성, 전체 대화 기록의 완전성, 수집 전후 읽음 상태 전체 비교, 24–72시간 연속 수신은 추가 검증이 필요합니다. 실제 Dot 이벤트 실행은 미검증이며 자동 구독은 요구 사항이 아닙니다.

초기 알림 기반 MVP와 문제 해결 이력은 Git에 남아 있습니다. 현재 동작은 [Iris](iris.md), [관리 화면](web-ui.md), [MCP](dot-plugin.md)를 참고하세요.
