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

Python 의존성은 `uv.lock`과 해시를 포함한 `requirements.lock`에 고정합니다. 변경 후 다음으로 맞추세요.

```bash
uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
```

<a id="code-layout"></a>

## 코드 구성

| 경로 | 역할 |
| --- | --- |
| `device/` | redroid 설정, 로그인 확인, Iris 수집기 |
| `iris/` | Iris 조회·제한된 텍스트 전송 진입점과 라이선스 고지 |
| `android/` | 등록 앱·웹 키보드, 이전 알림 수집 코드 |
| `server/` | 저장소, API, stdio MCP, 백업 |
| `webui/` | 관리 인증, 기기 제어, 웹 화면 |
| `dot_plugin/` | OAuth, 원격 MCP, 선택적 이벤트 |
| `ops/`, `bridge` | 호스트 CLI, 격리된 Lima 설치, 이미지 갱신, 암호화 전체 스냅샷 |
| `install.sh`, `install.ps1`, `ops/onboarding.py` | 단일 실행 명령, 의존성 준비, 이어서 설정 |
| `ops/setup_output.py` | 한국어 진행 안내와 비공개 진단 로그, 인증 링크·프로토콜 출력 분리 |
| `ops/setup_agent.py`, `server/connection_setup.py`, `webui/setup.py` | 비공개 호스트 설정 작업, 공유 입력 검증, 인증된 관리 프록시 |
| `webui/static/connection-setup.js` | 사용처·방식 선택, 저장된 안내, 진행·재시도 화면 |
| `tests/` | 합성 데이터 테스트와 브라우저 미리보기용 가상 기기 |
| `deploy/`, `scripts/` | Lima, 감독 서비스, 설치, 진단, 백업 도구 |

<a id="preview-the-web-console"></a>

## 관리 화면 미리보기

ADB·실제 계정에 연결하지 않는 테스트 환경을 사용하세요. 로컬에서 신뢰하는 localhost TLS 인증서가 필요합니다. 기존 설치의 인증서를 신뢰하고 있다면 다음과 같이 실행합니다.

```bash
uv run uvicorn tests.webui_preview:create_preview --factory \
  --host 127.0.0.1 --port 19443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:19443/admin/`의 복구 키 폼에 `preview-only-key-` 뒤에 0을 32개 붙여 입력하세요. `/test/calls`에는 가상 기기로 보낸 작업 이름만 표시합니다. 화면 제어, 로그인 점검, 두 기기 확인, 휴대폰 보고를 지원합니다. Aurora 준비·비공개 승인 서비스는 구현하지 않았으므로 격리된 스택에서 검사하세요. 운영 인스턴스에 설치하거나 승인을 초기화해 UI를 테스트하지 마세요.

위 환경은 명시적으로 로컬 인증을 사용합니다. 기본 패스키 UI·MCP 승인 흐름은 루프백 전용 테스트 환경으로 확인합니다.

```bash
uv run python -m tests.passkey_preview
```

다른 터미널에서 `node tests/passkey_browser.cjs`를 실행하세요. 필요하면 `PLAYWRIGHT_MODULE`에 기존 Playwright 모듈 경로, `CHROME_EXECUTABLE`에 Chromium·Chrome 실행 파일을 지정합니다. 포트 19446·19447, 일회용 TLS 인증서와 임시 상태를 사용하며 브라우저 검사마다 재시작해야 합니다.

가상 CTAP2 인증기와 Chromium의 WebAuthn으로 등록·재로그인·기억한 세션·새로고침·관리/MCP 포트 간 동일 키·명시적 동의·거부·PKCE 교환·갱신 토큰 교체·도구 목록을 검사합니다. 실제 계정·메시지·시스템 신뢰 설정은 사용하거나 변경하지 않습니다. 완료 후 Ctrl-C로 종료하세요. Python 테스트는 실제 ES256 서명과 잘못된 브라우저·출처·challenge·사용자 검증·RP·사용자 핸들 조합을 별도로 검사합니다.

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

승인받은 실제 배포에서는 기존 인증, **서버 연결 확인**, 성공한 MCP 상태 호출과 해당 시각을 확인하세요. 신규 설치나 공급자 전체 가입 검증과는 다릅니다. [검증 기록](implementation.md#admin-ux-and-connection-setup-2026-10-05)은 실제 검사와 합성 검사를 구분합니다.

<a id="container-checks"></a>

## 컨테이너 검사

```bash
docker compose build api device-agent gateway
./scripts/smoke.sh
uv run python scripts/smoke-ingress.py
```

smoke 테스트는 격리된 `kakaocollector-smoke-PID` 프로젝트에 합성 Iris 행을 넣고 HTTPS 인증·재전송·영속 저장·백업·stdio MCP를 검사합니다. 테스트 프로젝트의 볼륨만 제거하며 실제 redroid·계정은 사용하지 않습니다. 호스트에는 uv 또는 의존성이 준비된 Python 3.12가 필요합니다. 기본 서브넷 `172.29.88.0/24`와 포트 `18443`이 기존 배포와 충돌하지 않아야 합니다.

ingress smoke 테스트는 일회용 Docker 네트워크·echo 서버를 사용하며 운영 키·볼륨은 사용하지 않습니다. 비공개 Cookie·Set-Cookie 제거, OAuth 쿠키 유지, 공용 관리·MCP 라우팅, 내부 경로 차단, 루프백 포트 공개를 확인합니다. 별도 태그는 `SMOKE_SERVER_IMAGE`, `SMOKE_GATEWAY_IMAGE`로 지정하세요.

Docker 기반 이미지는 다이제스트로 고정합니다. 기기 빌드는 Bridge의 `assembleRelease`, `lintRelease`, `apksigner verify`와 Iris Kotlin 테스트·`assembleRelease`를 실행합니다. 오버레이 Gradle 설정으로 Netty 버전을 맞추고 실제 결과를 `/opt/iris-dependencies.txt`에 보관합니다.

ARM 소스 빌드는 컴파일 전에 고정한 amd64 Android 빌드 이미지에서 실행 검사를 합니다. 에뮬레이터가 실패하면 다이제스트로 고정한 `tonistiigi/binfmt` 이미지로 `qemu-x86_64` 처리기만 교체하고 재검사합니다. 새 Ubuntu VM에서 QEMU의 `cmp` 충돌과 APT 키링 오류가 발생한 문제를 해결합니다. 특권 Docker 접근이 필요하며 릴리스 이미지 설치·네이티브 실행 컨테이너에는 이 빌드 단계가 필요하지 않습니다. 고정 에뮬레이터는 [Lima 다중 아키텍처 안내](https://lima-vm.io/docs/config/multi-arch/)를 기준으로 합니다.

<a id="contribution-guidelines"></a>

## 기여 지침과 문구 정책

사용자 문서, UI, 도구 설명, 터미널 안내는 **한국어를 기본**으로 작성합니다. 구현 주석·내부 오류·진단 로그·프로토콜 식별자는 영어로 유지합니다. 설정 내부 출력은 한국어 진행 안내로 요약하고 원본은 비공개 로그에 보관합니다. 제품명·명령어·외부 서비스의 실제 메뉴명은 필요하면 영문을 병기합니다. 지원 카카오톡 UI를 식별하는 한국어 리터럴과 다국어 테스트 데이터는 유지합니다.

화면 설명은 현재 상태와 다음 행동에 집중합니다. 설치·운영 절차는 해당 안내에, 프로토콜·저장 상세는 구조·API 문서에 둡니다. README에 작업 로그나 문제 해결 시도 이력을 붙이지 마세요.

자동 준비는 `uv run python -m tests.setup_preview`를 실행한 뒤 같은 Playwright·Chrome 옵션으로 `node tests/setup-browser.cjs`를 실행하세요. 포트 19449와 가상 스토어·기기 상태로 준비, 스토어 설치 감지, 구성 요소 자동 설정, 직접 로그인 확인 경계, 재설치 없는 새로고침을 검사합니다. 실제 VM이나 카카오톡 로그인은 실행하지 않습니다.

한국어 화면과 README 이미지는 `uv run python -m tests.localization_preview`로 포트 19450에 가상 현황을 띄운 뒤 `node tests/localization-browser.cjs`로 검증합니다. 한국어 안내, 모바일 가로 넘침, SVG 글자 영역을 확인하고 `docs/assets/admin-overview.png`를 다시 캡처합니다. SVG 미리보기는 Git 제외 경로 `artifacts/localization/`에 남습니다.

로그인·인증 변경은 단위 테스트 외에도 실제 브라우저에서 폼 제출을 확인하세요. HTTP 클라이언트에 Origin 헤더를 직접 넣는 것으로 브라우저 검증을 대신할 수 없습니다. 테스트·화면 캡처에 토큰·실제 대화·계정 정보를 넣지 마세요.

OAuth 승인 화면도 실제 계정 없이 미리 볼 수 있습니다.

```bash
uv run uvicorn tests.dot_preview:create_preview --factory \
  --host 127.0.0.1 --port 20443 \
  --ssl-certfile secrets/tls_cert.pem --ssl-keyfile secrets/tls_key.pem \
  --no-access-log
```

`https://localhost:20443/test/start`에 같은 미리보기 키를 입력하면 로컬 콜백으로 돌아옵니다. 임시 디렉터리에 상태를 저장하며 수집 API·이벤트 작업자에는 연결하지 않습니다.
