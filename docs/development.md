# 개발

[README](../README.md) · [구조](design.md) · [검증 범위](implementation.md)

<a id="local-checks"></a>

## 로컬 검사

```bash
uv sync --frozen --python 3.12
uv run pytest -q
uv run ruff check .
node --check webui/static/app.js
node --check webui/static/connection-setup.js
node --test tests/setup-flow.test.cjs tests/connection-guidance.test.cjs
node --check dot_plugin/static/approval.js
docker compose --profile dot config --quiet
```

Caddy 실행 파일이 없으면 로컬 프록시 테스트는 건너뜁니다.

설정 화면 브라우저 검사는 Playwright와 Chrome·Chromium이 필요합니다. 한 터미널에서 가상 스토어·기기를 띄우고 다른 터미널에서 검사를 실행하세요.

```bash
uv run python -m tests.setup_preview
node tests/setup-browser.cjs
```

`PLAYWRIGHT_MODULE`에 기존 Playwright 모듈 경로, `CHROME_EXECUTABLE`에 Chrome·Chromium 실행 파일을 지정할 수 있습니다. 포트 19449에서 단계별 설정 화면, 자동 준비, Aurora 로그인 감지와 카카오톡 페이지 열기, 스토어 설치 감지, 구성 요소 설치, 카카오톡 열기, 로그인 자동 감지, 휴대폰 확인 전 수집 시작 비활성, 재설치 없는 새로고침을 검사합니다. 실제 VM이나 카카오톡 로그인은 실행하지 않으며 검사마다 미리보기를 다시 시작하세요.

Python 의존성은 `uv.lock`과 해시를 포함한 `requirements.lock`에 고정합니다. 변경 후 다음으로 맞추세요.

```bash
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
```

<a id="code-layout"></a>

## 코드 구성

| 경로 | 역할 |
| --- | --- |
| `device/` | redroid 준비, 등록과 수집 승인(`enrollment.py`), Iris 수집기, 키보드 앱 갱신, 기기 오류의 한국어 문구(`messages.py`) |
| `iris/` | DB 조회와 인증된 텍스트 전송을 위한 Iris 진입점, 라이선스 고지 |
| `android/` | 웹 입력 키보드 앱(`SetupActivity`, `WebInputMethod`). 코드 패키지 `dev.kakaotalkbridge.android`, 앱 ID `dev.kakaocollector.bridge` |
| `server/` | 저장소, API, stdio MCP, 백업 |
| `webui/` | 관리 인증, 기기 제어, 웹 화면 |
| `dot_plugin/` | OAuth, 원격 MCP, 선택적 이벤트 |
| `bridge`, `ops/cli.py` | 호스트 CLI 진입점과 명령 파서, Compose 호출. Linux에서는 `bridge mcp`를 제외하고 sudo로 다시 실행 |
| `ops/install.py`, `ops/releases.py`, `ops/source.py` | 설치·업데이트, 검증된 릴리스 다운로드, 소스 교체와 롤백 |
| `ops/onboarding.py`, `ops/lima.py` | `./bridge up` 단계, Mac의 Lima VM |
| `ops/doctor.py`, `ops/backup.py`, `ops/snapshot.py` | 상태 점검, 암호화 전체 백업·복구 |
| `ops/access.py`, `ops/connections.py`, `ops/expose.py`, `ops/tunnel.py` | 관리 화면 링크와 패스키 설정, AI 연결 선택, Tailscale HTTPS, OpenAI 터널 |
| `ops/setup_output.py`, `ops/errors.py` | 한국어 진행 표시, 비공개 진단 로그, 하위 명령 보고, `BridgeError` |
| `ops/setup_agent.py`, `server/connection_setup.py`, `webui/setup.py` | 비공개 호스트 설정 작업, 공유 입력 검증, 인증된 관리 프록시 |
| `install.sh`, `install.ps1` | 설치 명령. 설치된 릴리스에서는 `bridge upgrade` 후 `bridge up` 실행 |
| `webui/static/connection-setup.js` | 단계별 AI 연결 화면(사용할 곳 → 서버 준비 → AI 앱에 추가), 진행·재시도 |
| `tests/` | 합성 데이터 테스트와 브라우저 미리보기용 가상 기기 |
| `deploy/`, `scripts/` | Lima VM 템플릿, 감독 서비스 예시, 직접 만든 Lima VM용 스크립트, 키 생성, 릴리스 빌드·검증, smoke 테스트, 휴대폰 APK 가져오기 |

<a id="installer-output"></a>

## 설치·관리 명령 출력

`./bridge up`과 설치·업데이트·백업 같은 관리 명령은 화면에 한국어 단계와 짧은 하위 단계(`  · …`)만 표시합니다. 규칙은 `ops/setup_output.py`에 있습니다.

- 진행은 `cli.progress()`, 사용자가 반드시 볼 안내는 `cli.notice()`로 출력합니다.
- 보여 줄 실패는 한국어 문구의 `BridgeError`(`ops/errors.py`)로 올립니다. 그 밖의 예외는 일반 안내만 표시하고 상세 내용은 로그에 남깁니다. 화면에 traceback을 출력하지 않습니다.
- Lima·Docker·패키지 관리자 출력은 실행마다 하나인 비공개 로그 `.bridge/logs/setup-*.log`에 저장하고, 실패하면 로그 경로를 한 번 표시합니다. 캡처한 명령 출력은 화면에 그대로 출력하지 않습니다.
- 하위 Bridge 명령(Lima VM 안 포함)은 `bridge_command()`로 실행합니다. 하위 명령은 진행·안내·오류를 `@@kakaotalk-bridge@@ {JSON}` 형식의 stdout 줄로 부모에게 보내고, 나머지 출력은 부모의 로그로 갑니다. 오류는 가장 안쪽 명령의 문구를 표시합니다.
- `--verbose`는 `./bridge up`과 설치 명령에서만 받습니다. 하위 명령을 포함한 원문 출력을 화면에 보여 주며 설치 로그(`setup-*.log`)는 만들지 않습니다.
- 기기 CLI와 관리 화면의 기기 오류는 `device/messages.py`의 한국어 문구로 바꿉니다. 알 수 없는 예외 내용은 개인 정보가 있을 수 있으므로 그대로 표시하지 않습니다.

<a id="preview-the-web-console"></a>

## 관리 화면 미리보기

ADB·실제 계정에 연결하지 않는 테스트 환경을 사용하세요. 로컬에서 신뢰하는 localhost TLS 인증서가 필요합니다. 기존 설치의 인증서를 신뢰하고 있다면 다음과 같이 실행합니다.

```bash
uv run uvicorn tests.webui_preview:create_preview --factory \
  --host 127.0.0.1 --port 19443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:19443/admin/`의 복구 키 폼에 `preview-only-key-` 뒤에 0을 32개 붙여 입력하세요. `/test/calls`에는 가상 기기로 보낸 작업 이름만 표시합니다. 화면 제어와 로그인 화면 점검을 지원하며, 로그인 감지와 수집 시작은 [설정 화면 브라우저 검사](#local-checks)에서 확인합니다. Aurora 준비·비공개 승인 서비스는 구현하지 않았으므로 격리된 스택에서 검사하세요. 운영 인스턴스에 설치하거나 승인을 초기화해 UI를 테스트하지 마세요.

위 환경은 명시적으로 로컬 인증을 사용합니다. 기본 패스키 UI·MCP 승인 흐름은 루프백 전용 테스트 환경으로 확인합니다.

```bash
uv run python -m tests.passkey_preview
```

다른 터미널에서 `node tests/passkey_browser.cjs`를 실행하세요. 필요하면 `PLAYWRIGHT_MODULE`에 기존 Playwright 모듈 경로, `CHROME_EXECUTABLE`에 Chromium·Chrome 실행 파일을 지정합니다. 포트 19446·19447, 일회용 TLS 인증서와 임시 상태를 사용하며 브라우저 검사마다 재시작해야 합니다.

가상 CTAP2 인증기와 Chromium의 WebAuthn으로 등록·재로그인·기억한 세션·새로고침·관리/MCP 포트 간 동일 키·명시적 동의·거부·PKCE 교환·갱신 토큰 교체·도구 목록·전송 권한 동의·터널 전송 허용과 철회를 검사합니다. 실제 계정·메시지·시스템 신뢰 설정은 사용하거나 변경하지 않습니다. 완료 후 Ctrl-C로 종료하세요. Python 테스트는 실제 ES256 서명과 잘못된 브라우저·출처·challenge·사용자 검증·RP·사용자 핸들 조합을 별도로 검사합니다.

<a id="connection-setup-and-overview-checks"></a>

## 연결 설정과 현황 검사

```bash
uv run pytest -q tests/test_web_connection_setup.py tests/test_connection_setup.py tests/test_tunnel.py tests/test_event_settings.py
node --test tests/connection-guidance.test.cjs tests/setup-flow.test.cjs
```

설정 입력 경계, 작업·키 처리, 방식 저장, 진행 격리, 안내 유지, 터널 승인·성공 호출 기록, 대화 이벤트 권한을 검사합니다. 순수 JavaScript 검사는 실제 브라우저 상호작용을 대신하지 않습니다.

UI 변경 시 격리된 환경의 가상 공급자를 사용해 확인하세요.

- 설정·승인은 있지만 활동이 없는 연결은 첫 성공 호출을 기다립니다. 서버 점검이 활동을 만들면 안 됩니다.
- 점검·실패·새로고침 후 안내를 유지합니다. 중단 작업은 내용을 다시 보여 주고 수정 후 재시도할 수 있어야 합니다.
- HTTPS `/mcp` 입력은 출처로 정규화하고 인증 정보는 폼에서 지웁니다.
- 오래된 점검은 마지막 승인 표시를 유지하고 휴대폰 확인 등 관련 작업을 다시 켜는 방법을 안내합니다.
- 실행 중인 수집기는 설정·태블릿을 접은 상태로 시작합니다. 폭 390픽셀에서도 가로 넘침 없이 메뉴·조작에 접근할 수 있어야 합니다.
- 이벤트 허용과 구독 상태는 구분합니다. 배치 검사만을 위해 실제 구독을 만들지 마세요.

승인받은 실제 배포에서는 기존 인증, **서버 연결 확인**, 성공한 MCP 상태 호출과 해당 시각을 확인하세요. 신규 설치나 공급자 전체 가입 검증과는 다릅니다. [검증 범위](implementation.md)는 실제 검사와 합성 검사를 구분합니다.

<a id="container-checks"></a>

## 컨테이너 검사

```bash
docker compose build api device-agent gateway
./scripts/smoke.sh
uv run python scripts/smoke-ingress.py
```

smoke 테스트는 격리된 `kakaotalk-bridge-smoke-PID` 프로젝트에서 API·gateway·관리 화면만 시작하고 합성 Iris 행으로 HTTPS 인증·재전송·영속 저장·암호화 DB 백업·stdio MCP·관리 화면 세션을 검사합니다. 테스트 프로젝트의 볼륨만 제거하며 실제 redroid·계정은 사용하지 않습니다. 호스트에는 uv 또는 의존성이 준비된 Python 3.12가 필요합니다. 기본 서브넷 `172.29.88.0/24`와 포트 `18443`이 기존 배포와 충돌하지 않아야 합니다.

ingress smoke 테스트는 일회용 Docker 네트워크·echo 서버를 사용하며 운영 키·볼륨은 사용하지 않습니다. 비공개 Cookie·Set-Cookie 제거, OAuth 쿠키 유지, 공용 관리·MCP 라우팅, 내부 경로 차단, 루프백 포트 공개를 확인합니다. 기본 이미지는 `kakaotalk-bridge/server:local`, `kakaotalk-bridge/gateway:local`이며 다른 태그는 `SMOKE_SERVER_IMAGE`, `SMOKE_GATEWAY_IMAGE`로 지정하세요.

Docker 기반 이미지는 다이제스트로 고정합니다. 기기 빌드는 키보드 앱의 `assembleRelease`, `lintRelease`, `apksigner verify`와 Iris Kotlin 테스트·`assembleRelease`를 실행합니다. 오버레이 Gradle 설정으로 Netty 버전을 맞추고 실제 결과를 `/opt/iris-dependencies.txt`에 보관합니다.

ARM 소스 빌드는 컴파일 전에 고정한 amd64 Android 빌드 이미지에서 실행 검사를 합니다. 에뮬레이터가 실패하면 다이제스트로 고정한 `tonistiigi/binfmt` 이미지로 `qemu-x86_64` 처리기만 교체하고 재검사합니다. 특권 Docker 접근이 필요하며 릴리스 이미지 설치·네이티브 실행 컨테이너에는 이 빌드 단계가 필요하지 않습니다. 고정 에뮬레이터는 [Lima 다중 아키텍처 안내](https://lima-vm.io/docs/config/multi-arch/)를 기준으로 합니다.

<a id="contribution-guidelines"></a>

## 기여 지침과 문구 정책

사용자 문서, UI, 도구 설명, 터미널 안내는 **한국어를 기본**으로 작성합니다. 구현 주석·내부 오류·진단 로그·프로토콜 식별자는 영어로 유지합니다. 설정 내부 출력은 [한국어 진행 안내](#installer-output)로 요약하고 원본은 비공개 로그에 보관합니다. 제품명·명령어·외부 서비스의 실제 메뉴명은 필요하면 영문을 병기합니다. 지원 카카오톡 UI를 식별하는 한국어 리터럴과 다국어 테스트 데이터는 유지합니다.

화면 설명은 현재 상태와 다음 행동에 집중합니다. 설치·운영 절차는 해당 안내에, 프로토콜·저장 상세는 구조·API 문서에 둡니다. README에 작업 로그나 문제 해결 시도 이력을 붙이지 마세요.

한국어 화면과 README 이미지는 `uv run python -m tests.localization_preview`로 포트 19450에 가상 현황을 띄운 뒤 `node tests/localization-browser.cjs`로 검증합니다. 한국어 안내, 모바일 가로 넘침, SVG 글자 영역을 확인하고 `docs/assets/admin-overview.png`를 다시 캡처합니다. SVG 미리보기는 Git에서 제외되는 `artifacts/localization/`에 저장합니다.

로그인·인증 변경은 단위 테스트 외에도 실제 브라우저에서 폼 제출을 확인하세요. HTTP 클라이언트에 Origin 헤더를 직접 넣는 것으로 브라우저 검증을 대신할 수 없습니다. 테스트·화면 캡처에 토큰·실제 대화·계정 정보를 넣지 마세요.

OAuth 승인 화면도 실제 계정 없이 미리 볼 수 있습니다.

```bash
uv run uvicorn tests.dot_preview:create_preview --factory \
  --host 127.0.0.1 --port 20443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:20443/test/start`에 같은 미리보기 키를 입력하면 로컬 콜백으로 돌아옵니다. 임시 디렉터리에 상태를 저장하며 수집 API·이벤트 작업자에는 연결하지 않습니다.
