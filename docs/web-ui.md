# 웹에서 redroid 조작과 로그인

## 구조

```text
브라우저 ── HTTPS /admin/ ── Caddy ── admin:8080
                                  ├─ ADB → redroid 화면/입력
                                  ├─ 기존 bootstrap/login-check/confirm-secondary
                                  └─ API 상태 조회 (read 토큰)
redroid의 카카오톡 DB ── Iris ── iris-collector ── API/SQLite/MCP
```

물리 태블릿 없이 redroid 화면을 조작한다. 관리 화면은 서버·redroid와 함께 Compose의 `admin` 서비스로 실행된다. 초기 설치·로그인·수집 확인을 위해 운영자 PC에 scrcpy/ADB를 설치할 필요가 없다.

첫 화면의 관리자 키는 `secrets/admin_token`이다. `scripts/init-secrets.sh`가 기존 키를 보존하면서 새 관리자 키를 생성한다. 기존 설치에서도 이 스크립트를 다시 실행해야 한다. 카카오 계정 비밀번호와 다른 자격증명이다.

## 접속과 로그인 순서

1. 기존 Linux 커널/binder 준비, 정식 카카오 APK 배치, 시크릿 초기화를 완료한다.
2. `docker compose build api device-agent`로 이미지를 빌드하고 `docker compose up -d`로 실행한다.
3. 원격이면 `ssh -N -L 18443:127.0.0.1:8443 user@linux-server`로 터널을 연다.
4. `https://localhost:18443/admin/`에 접속한다. 서버 자체에서는 `https://localhost:8443/admin/`이다. 설치 시 생성된 TLS 인증서를 확인하고 브라우저가 신뢰하도록 준비한다.
5. `secrets/admin_token`으로 관리 화면을 연다. 값은 URL이나 채팅에 넣지 않는다.
6. 최초라면 **초기 설치**를 실행한다. `inputs/kakao` APK 세트와 새 등록 APK/Iris를 설치하고 웹 입력기를 선택한다. 기존 설치에 재실행하면 보조 로그인 확인을 초기화한다.
7. **카카오톡 열기**, **입력 연결**을 누른다. 화면에서 카카오톡의 입력칸을 클릭한 뒤 웹의 입력란으로 한글·아이디·비밀번호를 보낸다. 현재 커서 위치에 텍스트를 삽입하며 자동 로그인 제출은 하지 않는다.
8. **‘다른 기기와 함께 사용’**을 선택하고 로그인 버튼을 누르기 전에 **보조 로그인 옵션 검사**를 실행한다.
9. 검사 통과 후 기기 화면에서 로그인한다. 핸드폰 기존 세션과 redroid 세션을 직접 확인하고 두 확인란을 선택한 뒤 **Iris 수집 활성화**를 누른다. 기존 30분 사전 검사 및 기기/앱 일치 조건이 적용된다.
10. 끝나면 **관리 화면 잠금**을 누른다. 이는 웹 관리자 세션 종료이며 카카오톡 로그아웃은 아니다.

원격 포트 대신 직접 공개하려면 인증서와 호스트 HTTPS 바인딩을 운영자가 구성해야 한다. 기본 Compose의 HTTPS/ADB 포트는 loopback에만 게시하며, admin:8080은 호스트에 게시하지 않는다.

## 조작 기능

### 로그인·핸드폰 세션 상태

상단 **현재 상태 검사**는 현재 화면을 이동하지 않고 ADB 연결, 설치 상태, 현재 카카오톡 UI, 사전 검사와 수집 승인 기록을 검사한다. 로그인 폼이 있으면 **로그인 화면 감지**, 지원하는 탭 구조가 있으면 **로그인 후 화면 관찰**로 표시한다. 후자는 카카오 서버에서 세션이 인증되었다는 증거가 아니다. 현재 구현은 한국어 로그인 폼 및 명시적인 Android TabWidget 안의 친구·채팅·더보기 구조만 인식하며, 최신 카카오 UI에서 이 구조가 제공되는지는 실기 검증 전이다. 화면을 인식하지 못하거나 다른 앱/잠금 화면이 보이면 미확인으로 남긴다. DB 존재나 Iris 수집 성공을 로그인 성공의 증거로 사용하지 않는다.

검사 결과는 admin 메모리에만 있고, 60초 뒤 또는 화면 조작/기기 작업 후 재검사를 요구한다. 검사 실행 중에는 기존 기기 작업 잠금을 사용한다. 앱 버전/기기 정보가 맞지 않으면 이전 보조 로그인 승인을 유효하게 표시하지 않는다. 연결 실패는 상태 미확인이며 핸드폰 로그아웃으로 추정하지 않는다.

핸드폰은 redroid/서버에 연결되어 있지 않다. **유지됨 · 사용자 직접 확인**은 운영자가 핸드폰을 열어 확인한 기록이며 자동 감시가 아니다. 최초 양쪽 확인 및 이후 **핸드폰 유지 확인 시각 갱신**을 통해 Android 등록 설정에 마지막 시각을 보관한다. 재시작 후에도 **현재 상태 검사**로 다시 조회할 수 있다. 운영 기본값으로 24시간 후 **핸드폰 재확인 필요**를 표시하며, 이 경과만으로 수집을 중지하지는 않는다.

**핸드폰 로그아웃됨 · 수집 중단**을 누르면 보고 시각을 기록하고 `secondary_login_version`을 0으로 변경해 수집 승인을 해제한다. 이어 기존 사전 검사 증거를 삭제하고 자체 Iris 프로세스를 중단한다. 수집기도 업로드 전 승인 상태를 다시 확인한다. 이미 처리 중인 업로드의 취소를 보장하는 기능은 아니다. 이후 단순 핸드폰 재확인으로 수집 승인을 복구할 수 없으며 기존 로그인 전 검사와 양쪽 세션 확인을 다시 수행해야 한다. ADB 단절 등으로 이 작업이 실패하면 완료로 표시하지 않는다. 이 버튼은 핸드폰 자체를 로그아웃시키는 명령이 아니다.

UI 검사의 원본 XML은 개인 정보가 포함될 수 있어 Android의 임시 0700 디렉터리 안에만 만들고 검사 후 삭제한다. API에는 분류와 시각만 반환한다. 비정상 종료 시 임시 파일이 남을 가능성이 있으며 원본 XML/계정/채팅 내용을 로그나 확인 기록에 저장하지 않는다.

### 화면 조작

- 화면 클릭은 Android tap, 드래그/길게 누르기는 swipe로 전달한다.
- 뒤로/홈/화면 켜기/Tab/삭제/Enter는 허용 목록의 Android 키만 전달한다.
- 화면은 약 1.2초 간격으로 PNG를 받아 갱신한다. 동영상 스트리밍 방식이 아니다. 탭을 숨기거나 일시정지하면 자동 갱신을 멈춘다.
- 프레임 ID·해상도·10초 유효시간을 확인한다. 오래된 프레임, 화면 밖 좌표, 임의 키 코드/셸 명령을 거절한다.
- 초기 설치 같은 긴 작업은 백그라운드에서 진행하며, 진행 중 추가 기기 조작을 거절한다. 상태와 결과는 같은 화면에 표시한다.
- 새 관리자 로그인이 이전 관리자 세션을 만료시킨다. 작업은 하나씩 처리한다. 이미 수락한 긴 작업은 웹을 잠가도 끝까지 수행한다.
- 웹 작업과 CLI bootstrap/login-check를 동시에 실행하지 않는다. CLI와 웹 사이의 분산 잠금은 구현하지 않았다.

직접 채팅방을 열면 읽음 표시가 바뀔 수 있다. 웹 조작은 운영자의 명시적인 입력을 실행하는 경로다. 옵션 미선택 상태의 모든 수동 클릭이나 카카오톡 자체의 인증 정책을 소프트웨어가 통제하는 것은 아니다.

## 입력과 인증

관리자 키를 교환하면 30분 고정 만료의 메모리 세션을 만든다. 쿠키는 `Secure`, `HttpOnly`, `SameSite=Strict`, `__Host-` 접두사와 `/` 경로를 사용한다. 세션/CSRF 토큰은 브라우저 localStorage에 보관하지 않는다. 관리자 재시작 시 세션도 사라진다. Origin 일치와 CSRF 헤더를 모든 인증된 변경 요청에 요구한다. 인증 실패는 분당 5회로 제한한다.

화면·응답에는 `Cache-Control: no-store`, 클릭재킹 방지 및 자체 리소스만 허용하는 CSP를 설정한다. 화면 PNG는 서버 디스크에 저장하지 않는다. HTTP 접근 로그와 입력 본문 로그를 기록하지 않는다. 관리자 UI는 조회용 MCP 권한으로 조작할 수 없다.

한글 입력은 자체 Android `WebInputMethod`가 담당한다. `DUMP` 시스템 권한을 가진 shell/root의 고정 broadcast만 받으며, 카카오톡에 포커스된 입력 연결에 `commitText`를 호출한다. 주변 텍스트를 읽거나 키 입력을 수집하지 않는다. 입력값을 ADB 명령행이나 URL에 싣지 않는다.

전달 과정에서 입력값은 컨테이너 `/tmp`(tmpfs)의 0600 임시 파일 및 Android 앱 전용 임시 파일을 잠시 거친다. 성공/실패 후 삭제하며 영구 입력 기록을 남기지 않는다. 갑작스러운 프로세스/호스트 중단 시 임시 파일이 남을 가능성은 있으며, 입력기 시작 시 이전 pending 파일을 삭제한다. 이를 메모리만 사용하는 전달이라고 표현하지 않는다. 입력 결과가 불명확하면 자동 재전송하지 않으므로 화면을 확인한 후 다시 입력한다.

## 검증 범위와 제한

실제 redroid 부팅, Android 입력기 활성화/commitText, 카카오 로그인 화면 및 핸드폰 세션 유지는 이 macOS 호스트에서 검증하지 않았다. Android 보안 화면은 스크린샷이 검게 표시될 수 있다. root ADB 및 설치된 등록 앱이 필요하다. ARM/amd64 카카오 APK 호환성은 기존 Linux 실기 검증에 포함된다.

브라우저 검증은 `tests/webui_preview.py`의 합성 PNG와 가짜 Android 동작을 사용했다. `artifacts/webui-desktop.png`, `artifacts/webui-mobile.png`의 빈 태블릿 화면은 실제 카카오 화면이 아니다. 테스트용 self-signed TLS 연결에서만 Playwright의 인증서 오류 무시를 사용했으며, 배포용 TLS 검사 설정은 변경하지 않았다.

## 로컬 검증 기록 (2026-10-04)

- `uv run pytest -q`: `56 passed, 1 warning in 4.89s`. 기존 47개 및 관리자 인증/CSRF/좌표/입력/작업/만료 테스트 9개다. 경고는 기존 HTTPX TestClient deprecation이다.
- 최종 CSRF 비ASCII 헤더 처리 수정 후 `uv run pytest -q tests/test_webui.py`: `9 passed, 1 warning in 0.36s`.
- `uv run ruff check webui device server tests deploy scripts/smoke.py`: `All checks passed!`
- `docker compose config --quiet`, `git diff --check`: exit 0, 출력 없음.
- `docker compose build device-agent`: exit 0, `kakaotalk-collector/device:0.1.0 Built`. 입력기 포함 Bridge APK의 assembleRelease/lintRelease/서명 검증을 수행했다. Android receiver 등록 Lint 오류를 ContextCompat의 명시적 export 플래그 및 DUMP 권한으로 수정했다.
- `docker buildx build --platform linux/amd64 -f docker/device.Dockerfile --secret id=bridge_keystore,src=secrets/bridge.jks --secret id=bridge_key_password,src=secrets/bridge_key_password -t kakaotalk-collector/device:0.1.0-amd64 --load .`: exit 0. SDK 도구의 고정 amd64 빌드 단계에 대한 기존 Docker 권고 경고가 남아 있다.
- amd64 컨테이너의 관리자 HTML/인증 검증: `PASS: linux/amd64 web console serves UI and authenticates`.
- `./scripts/smoke.sh`: exit 0. 별도 Compose 프로젝트에서 실제 Caddy/API/admin/MCP를 시작했다. redroid를 시작하거나 ADB 작업을 호출하지 않았다. 다음 결과를 확인하고 테스트 컨테이너와 볼륨을 정리했다.

```text
PASS: synthetic Iris row, durable cursor and scoped conversation ID
PASS: TLS verification, authenticated ingest, duplicate retry, Korean text, read API, partial coverage
PASS: container stdio MCP calls all four read-only tools against the API
PASS: HTTPS web console, secure admin session, CSRF rejection and logout (no ADB actions)
PASS: container restart preserves collected data
PASS: encrypted backup and verified restore inside non-root container
```

브라우저 테스트 서버 명령은 `uv run uvicorn tests.webui_preview:create_preview --factory --host 127.0.0.1 --port 19443 --ssl-keyfile secrets/tls_key.pem --ssl-certfile secrets/tls_cert.pem --no-access-log`였다. Playwright에서 관리자 인증 → 화면 클릭 → 한글 입력 → 뒤로가기 → 양쪽 확인 → 잠금을 실행했다.

```text
calls: [tap, text, key, confirm]
inputCleared: true
mobileOverflow: false
logoutWorked: true
consoleHidden: true
screenHasNoSrc: true
```

1360px 데스크톱과 390px 모바일 폭에서 가로 넘침이 없음을 확인했다. 검증 후 mock 서버와 테스트 브라우저를 종료했다. 이 결과는 Android IME가 실제 카카오톡 입력칸에 문자열을 전달했다는 증거가 아니다.

최종 `artifacts/bridge.apk` SHA-256: `6468a775a61c2a47973b22c9254993d53a7e093322410c95a6cd07fe8f06afd2`. Iris APK는 이번 UI 작업으로 변경하지 않았다. 이전 Iris 문서의 Bridge 해시는 웹 입력기 추가 전 기록이다.

## 세션 확인 확장 검증 (2026-10-04)

- `uv run pytest -q`: `65 passed, 1 warning in 1.86s`. 화면 오인식 방지, 확인 시각·만료·기기 변경, 로그아웃 보고 시 수집 승인 해제 및 재확인으로 재활성화 차단, 인증/CSRF/원본 비노출을 검증했다. 기존 TestClient deprecation 경고 1개다.
- `uv run ruff check webui device server tests deploy scripts/smoke.py`: `All checks passed!`
- `node --check webui/static/app.js`, `docker compose config --quiet`, `git diff --check`: exit 0.
- `docker compose build device-agent`: exit 0, `kakaotalk-collector/device:0.1.0 Built`.
- `docker buildx build --platform linux/amd64 -f docker/device.Dockerfile --secret id=bridge_keystore,src=secrets/bridge.jks --secret id=bridge_key_password,src=secrets/bridge_key_password -t kakaotalk-collector/device:0.1.0-amd64 --load .`: exit 0. 기존 Android SDK 빌드 플랫폼 권고 경고 1개다.
- `./scripts/smoke.sh`: exit 0. 위에 기록한 6개 PASS 항목을 새 arm64 이미지로 재검증했다. 실제 redroid/계정은 사용하지 않았다.
- 가짜 Android를 사용한 Playwright: 현재 상태 검사 → 양쪽 확인 → 핸드폰 확인 시각 갱신 → 로그아웃 보고 → 수집 잠김을 확인했다. `phone: 로그아웃됨 · 사용자 보고`, `approval: Iris 수집 잠김`, `recheckDisabled: true`, `mobileOverflow: false`. 처음 잠금 검사는 비동기 응답을 기다리지 않아 false였으며, 응답 후 UI 전환을 기다린 재검증에서 `logoutWorked: true`, `sessionHTTP: 401`, `screenCleared: true`였다.
- 합성 화면: `artifacts/admin-sessions-desktop.png`, `artifacts/admin-sessions-mobile.png`. 실제 카카오 로그인 성공/핸드폰 세션 유지의 증거가 아니다.
- `./scripts/preflight.sh`: exit 1, `FAIL: Full redroid deployment requires a prepared Linux host. API/APK builds can run here.` 현재 호스트는 `Darwin arm64`, Docker는 `linux/aarch64` Docker Desktop이다. 배포할 Linux 서버 접속 정보가 없어 전체 배포와 실기 세션 검증은 미완료다.
